"""Request validation: raw body access, schema shape checks, existence helpers."""
from flask import request

import db
from errors import ApiError


def _is_string(v):
    return isinstance(v, str)


def _is_integer(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and v == v and v not in (float("inf"), float("-inf")))


def _is_boolean(v):
    return isinstance(v, bool)


INGREDIENT_ROW_SCHEMA = {
    "ingredient_type": ("enum", True, ["SEMOLINA", "DURUM_SEMOLINA", "RICE_FLOUR"]),
    "percentage": ("number", True, None),
    "min_protein_pct": ("number", False, None),
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
    if kind == "date":
        return db.parse_date(value) is not None
    if kind == "datetime":
        return db.parse_datetime(value) is not None
    if kind == "ingredients":
        if not isinstance(value, list):
            return False
        for item in value:
            validate_schema(item, INGREDIENT_ROW_SCHEMA)
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


def raw_body():
    """Return the request JSON object or raise ERR_INVALID_REQUEST."""
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return body


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


def require_path_entity(table, entity_id, error_id):
    entity = table.get(entity_id)
    if entity is None:
        raise ApiError(error_id, 404, "Resource not found: %s" % entity_id)
    return entity


def fk_exists(table, body, field, error_id):
    """Existence (priority 4) for a body-referenced FK, checked when present.

    Returns the resolved entity or None when the field is absent (the schema
    pass later decides whether absence is an error).
    """
    if field not in body or body[field] is None:
        return None
    value = body[field]
    if isinstance(value, (list, dict)):
        return None
    entity = table.get(value)
    if entity is None:
        raise ApiError(error_id, 404, "Referenced %s does not exist" % field)
    return entity
