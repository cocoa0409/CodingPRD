"""Request validation: body shape (priority 2), path/FK existence (priority 4).

Schema entries are 4-tuples: (kind, required, enum_values, constraint).
Kinds: string | integer | number | boolean | enum | datetime.
Number constraints: gt0 (> 0), ge0 (>= 0), range0_100 (0 <= v <= 100).
Datetime fields are validated parseable and the parsed value is stored back
into the body under "_<field>_dt" (second precision, UTC).
"""
from flask import request

import db
from errors import ApiError


def _is_number(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and v == v and v not in (float("inf"), float("-inf")))


def _bad(field, why):
    raise ApiError("ERR_INVALID_REQUEST", 400, "Field %s: %s" % (field, why))


def validate_schema(body, schema):
    """Raise ERR_INVALID_REQUEST unless body is a dict matching schema exactly."""
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    for key in body:
        if key not in schema:
            raise ApiError("ERR_INVALID_REQUEST", 400, "Unknown field: %s" % key)
    for field, spec in schema.items():
        kind, required, enum_values, constraint = spec
        if field not in body:
            if required:
                raise ApiError("ERR_INVALID_REQUEST", 400, "Missing required field: %s" % field)
            continue
        value = body[field]
        if kind == "string":
            if not isinstance(value, str):
                _bad(field, "must be a string")
        elif kind == "integer":
            if not (isinstance(value, int) and not isinstance(value, bool)):
                _bad(field, "must be an integer")
        elif kind == "number":
            if not _is_number(value):
                _bad(field, "must be a number")
            if constraint == "gt0" and not value > 0:
                _bad(field, "must be > 0")
            if constraint == "ge0" and not value >= 0:
                _bad(field, "must be >= 0")
            if constraint == "range0_100" and not (0 <= value <= 100):
                _bad(field, "must be between 0 and 100 inclusive")
        elif kind == "boolean":
            if not isinstance(value, bool):
                _bad(field, "must be a boolean")
        elif kind == "enum":
            if not (isinstance(value, str) and value in enum_values):
                _bad(field, "must be one of %s" % ",".join(enum_values))
        elif kind == "datetime":
            body["_%s_dt" % field] = db.parse_dt(value, field)
        else:
            _bad(field, "unknown schema kind")


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
