"""Request validation: body shape, path/FK existence, field helpers."""
from flask import request

from errors import ApiError


def _is_string(v):
    return isinstance(v, str)


def _is_integer(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_boolean(v):
    return isinstance(v, bool)


def _is_number(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and v == v and v not in (float("inf"), float("-inf")))


CONDITION_SCHEMA = {
    "condition_kind": ("enum", True, ["RESTORATION_REQUIRED", "ADDITIONAL_SECURITY",
                                       "RENT_RESET_TO_MARKET", "RECAPTURE_RIGHT"]),
    "detail": ("string", True, None),
}

ALLOCATION_SCHEMA = {
    "responsible_party": ("enum", True, ["TENANT", "SUBTENANT_OR_ASSIGNEE", "SHARED"]),
    "escrow_amount_cents": ("integer", True, None),
}


def _check(kind, value, enum_values):
    if kind == "string":
        return _is_string(value)
    if kind == "integer":
        return _is_integer(value)
    if kind == "number":
        return _is_number(value)
    if kind == "boolean":
        return _is_boolean(value)
    if kind == "enum":
        return _is_string(value) and value in enum_values
    if kind == "conditions":
        if not isinstance(value, list):
            return False
        for item in value:
            validate_schema(item, CONDITION_SCHEMA)
        return True
    if kind == "allocations":
        if not isinstance(value, list):
            return False
        for item in value:
            validate_schema(item, ALLOCATION_SCHEMA)
        return True
    return False


def validate_schema(body, schema):
    """Raise ERR_INVALID_REQUEST unless body is a dict matching schema exactly."""
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    for key in body:
        if key not in schema:
            raise ApiError("ERR_INVALID_REQUEST", 400, "Unknown field: %s" % key)
    for field, (kind, required, enum_values) in schema.items():
        if field not in body:
            if required:
                raise ApiError("ERR_INVALID_REQUEST", 400, "Missing required field: %s" % field)
            continue
        if not _check(kind, body[field], enum_values):
            raise ApiError("ERR_INVALID_REQUEST", 400, "Field %s has wrong type or value" % field)


def parse_body(schema, allow_empty=True):
    """Parse and validate the JSON request body against schema.

    allow_empty=True permits a missing body only when no required fields exist.
    """
    has_required = any(req for _, req, _ in schema.values())
    body = request.get_json(silent=True)
    if body is None:
        if allow_empty and not has_required:
            body = {}
        else:
            raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    validate_schema(body, schema)
    return body


def require_path_entity(table, entity_id):
    entity = table.get(entity_id)
    if entity is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found: %s" % entity_id)
    return entity
