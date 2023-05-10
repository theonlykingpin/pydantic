"""
Types and utility functions used by various other internal tools.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Dict

from pydantic_core import core_schema

from pydantic._internal._core_utils import CoreSchemaOrField

if TYPE_CHECKING:
    from pydantic.json_schema import GenerateJsonSchema, JsonSchemaMode

JsonSchemaValue = Dict[str, Any]


class GetJsonSchemaHandler:
    """
    Handler to call into the next JSON schema generation function
    """

    mode: JsonSchemaMode

    def __call__(self, __core_schema: CoreSchemaOrField) -> JsonSchemaValue:
        """Call the inner handler and get the JsonSchemaValue it returns.
        This will call the next JSON schema modifying function up until it calls
        into `pydantic.json_schema.GenerateJsonSchema`, which will raise a
        `pydantic.errors.PydanticInvalidForJsonSchema` error if it cannot generate
        a JSON schema.

        Args:
            __core_schema (CoreSchemaOrField): A `pydantic_core.core_schema.CoreSchema`.

        Returns:
            JsonSchemaValue: the JSON schema generated by the inner JSON schema modify
            functions.
        """
        raise NotImplementedError

    def resolve_ref_schema(self, __maybe_ref_json_schema: JsonSchemaValue) -> JsonSchemaValue:
        """Get the real schema for a `{"$ref": ...}` schema.
        If the schema given is not a `$ref` schema, it will be returned as is.
        This means you don't have to check before calling this function.

        Args:
            __maybe_ref_json_schema (JsonSchemaValue): A JsonSchemaValue, ref based or not.

        Raises:
            LookupError: if the ref is not found.

        Returns:
            JsonSchemaValue: A JsonSchemaValue that has no `$ref`.
        """
        raise NotImplementedError


GetJsonSchemaFunction = Callable[[CoreSchemaOrField, GetJsonSchemaHandler], JsonSchemaValue]


class UnpackedRefJsonSchemaHandler(GetJsonSchemaHandler):
    """
    A GetJsonSchemaHandler implementation that automatically unpacks `$ref`
    schemas so that the caller doesn't have to worry about that.

    This is used for custom types and models that implement `__get_pydantic_core_schema__`
    so they they always get a `non-$ref` schema.

    Used internally by Pydantic, please do not rely on this implementation.
    See `GetJsonSchemaHandler` for the handler API.
    """

    original_schema: JsonSchemaValue | None = None

    def __init__(self, handler: GetJsonSchemaHandler) -> None:
        self.handler = handler
        self.mode = handler.mode

    def resolve_ref_schema(self, __maybe_ref_json_schema: JsonSchemaValue) -> JsonSchemaValue:
        return self.handler.resolve_ref_schema(__maybe_ref_json_schema)

    def __call__(self, __core_schema: CoreSchemaOrField) -> JsonSchemaValue:
        self.original_schema = self.handler(__core_schema)
        return self.resolve_ref_schema(self.original_schema)

    def update_schema(self, schema: JsonSchemaValue) -> JsonSchemaValue:
        if self.original_schema is None:
            # handler / our __call__ was never called
            return schema
        original_schema = self.resolve_ref_schema(self.original_schema)
        if original_schema is not self.original_schema and schema is not original_schema:
            # a new schema was returned
            original_schema.clear()
            original_schema.update(schema)
        # return self.original_schema, which may be a ref schema
        return self.original_schema


def wrap_json_schema_fn_for_model_or_custom_type_with_ref_unpacking(
    fn: GetJsonSchemaFunction,
) -> GetJsonSchemaFunction:
    def wrapped(schema_or_field: CoreSchemaOrField, handler: GetJsonSchemaHandler) -> JsonSchemaValue:
        wrapped_handler = UnpackedRefJsonSchemaHandler(handler)
        json_schema = fn(schema_or_field, wrapped_handler)
        json_schema = wrapped_handler.update_schema(json_schema)
        return json_schema

    return wrapped


HandlerOverride = Callable[[CoreSchemaOrField], JsonSchemaValue]


class GenerateJsonSchemaHandler(GetJsonSchemaHandler):
    """
    JsonSchemaHandler implementation that doesn't do ref unwrapping by default.

    This is used for any Annotated metadata so that we don't end up with conflicting
    modifications to the definition schema.

    Used internally by Pydantic, please do not rely on this implementation.
    See `GetJsonSchemaHandler` for the handler API.
    """

    def __init__(self, generate_json_schema: GenerateJsonSchema, handler_override: HandlerOverride | None) -> None:
        self.generate_json_schema = generate_json_schema
        self.handler = handler_override or generate_json_schema.generate_inner
        self.mode = generate_json_schema.mode

    def __call__(self, __core_schema: CoreSchemaOrField) -> JsonSchemaValue:
        return self.handler(__core_schema)

    def resolve_ref_schema(self, __maybe_ref_json_schema: JsonSchemaValue) -> JsonSchemaValue:
        if '$ref' not in __maybe_ref_json_schema:
            return __maybe_ref_json_schema
        ref = __maybe_ref_json_schema['$ref']
        json_schema = self.generate_json_schema.get_schema_from_definitions(ref)
        if json_schema is None:
            raise LookupError(
                f'Could not find a ref for {ref}.'
                ' Maybe you tried to call resolve_ref_schema from within a recursive model?'
            )
        return json_schema


class GetCoreSchemaHandler:
    """
    Handler to call into the next CoreSchema schema generation function
    """

    def __call__(self, __source_type: Any) -> core_schema.CoreSchema:
        """
        Call the inner handler and get the CoreSchema it returns.
        This will call the next CoreSchema modifying function up until it calls
        into Pydantic's internal schema generation machinery, which will raise a
        `pydantic.errors.PydanticSchemaGenerationError` error if it cannot generate
        a CoreSchema for the given source type.

        Args:
            __source_type (Any): The input type.

        Returns:
            CoreSchema: the `pydantic-core` CoreSchema generated.
        """
        raise NotImplementedError


class CallbackGetCoreSchemaHandler(GetCoreSchemaHandler):
    """
    Wrapper to use an arbitrary function as a `GetCoreSchemaHandler`.

    Used internally by Pydantic, please do not rely on this implementation.
    See `GetCoreSchemaHandler` for the handler API.
    """

    def __init__(self, handler: Callable[[Any], core_schema.CoreSchema]) -> None:
        self._handler = handler

    def __call__(self, __source_type: Any) -> core_schema.CoreSchema:
        return self._handler(__source_type)
