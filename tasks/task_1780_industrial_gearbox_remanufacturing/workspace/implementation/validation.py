"""Request validation: JSON body shape (ERR_INVALID_REQUEST) and path existence."""
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


def _is_date_string(v):
    if not isinstance(v, str):
        return False
    try:
        db.parse_iso_date(v)
        return True
    except ValueError:
        return False


def _is_datetime_string(v):
    if not isinstance(v, str):
        return False
    try:
        db.parse_iso_dt(v)
        return True
    except ValueError:
        return False


def _is_version(v):
    """OCC expected_*_version: an integer version (digit strings tolerated)."""
    if _is_integer(v):
        return True
    return isinstance(v, str) and v.isdigit()


_CHECKERS = {
    "string": lambda v, enum: _is_string(v),
    "integer": lambda v, enum: _is_integer(v),
    "number": lambda v, enum: _is_number(v),
    "boolean": lambda v, enum: _is_boolean(v),
    "enum": lambda v, enum: _is_string(v) and v in enum,
    "date": lambda v, enum: _is_date_string(v),
    "datetime": lambda v, enum: _is_datetime_string(v),
    "version": lambda v, enum: _is_version(v),
}


def validate_schema(body, schema):
    """Raise ERR_INVALID_REQUEST unless body is a dict matching schema exactly."""
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    for key in body:
        if key not in schema:
            raise ApiError("ERR_INVALID_REQUEST", 400, "Unknown field: %s" % key)
    for field, (kind, required, enum_values, extra) in schema.items():
        if field not in body:
            if required:
                raise ApiError("ERR_INVALID_REQUEST", 400,
                               "Missing required field: %s" % field)
            continue
        value = body[field]
        if not _CHECKERS[kind](value, enum_values):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "Field %s has wrong type or value" % field)
        if extra is not None and not extra(value):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "Field %s has wrong type or value" % field)


def parse_body(schema, allow_empty=True):
    """Parse and validate the JSON request body against schema.

    allow_empty=True permits a missing body only when no required fields exist.
    """
    has_required = any(req for _, req, _, _ in schema.values())
    body = request.get_json(silent=True)
    if body is None:
        if allow_empty and not has_required:
            body = {}
        else:
            raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    validate_schema(body, schema)
    return body


def no_body():
    """Action endpoints take no fields; a missing body is fine, junk is not."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    validate_schema(body, {})
    return body


def require_path_entity(table, entity_id):
    entity = table.get(entity_id)
    if entity is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found: %s" % entity_id)
    return entity


def resolve_fk(table, fk_id, field_name):
    entity = table.get(fk_id)
    if entity is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced %s does not exist" % field_name)
    return entity


def schema_field(kind, required=True, enum=None, extra=None):
    return (kind, required, enum, extra)


def severity_ok(v):
    return 1 <= v <= 5
