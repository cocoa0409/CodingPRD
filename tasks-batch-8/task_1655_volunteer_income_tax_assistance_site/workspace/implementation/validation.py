"""Request body schema validation (pipeline tier 4) and existence helpers (tier 3)."""
from flask import request

import db
from errors import ApiError


def _is_string(v):
    return isinstance(v, str)


def _is_integer(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_boolean(v):
    return isinstance(v, bool)


def get_body():
    """Return the JSON request body as a dict; 400 when it is not a JSON object."""
    body = request.get_json(silent=True)
    if body is None:
        raw = (request.data or b"").strip()
        if raw:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "Request body must be a JSON object")
        body = {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Request body must be a JSON object")
    return body


def _check(spec, value):
    kind = spec["kind"]
    if value is None:
        return spec.get("allow_null", False)
    if kind == "string":
        return _is_string(value)
    if kind == "integer":
        if not _is_integer(value):
            return False
        if "min" in spec and value < spec["min"]:
            return False
        if "max" in spec and value > spec["max"]:
            return False
        return True
    if kind == "boolean":
        return _is_boolean(value)
    if kind == "enum":
        return _is_string(value) and value in spec["values"]
    if kind == "datetime":
        return db.parse_iso(value) is not None
    if kind == "array_enum":
        if not isinstance(value, list):
            return False
        return all(_is_string(item) and item in spec["values"] for item in value)
    if kind == "any":
        return True
    return False


def parse_body(schema):
    """Validate the request body against schema; return a cleaned copy.

    schema maps field name -> {
        kind: string|integer|boolean|enum|datetime|array_enum|any,
        required: bool (default False),
        values: [...] for enum/array_enum,
        min/max: for integer,
        allow_null: bool (None accepted; kept as None),
    }
    Unknown fields are rejected; datetime fields are converted to aware datetimes.
    """
    body = get_body()
    for key in body:
        if key not in schema:
            raise ApiError("ERR_INVALID_REQUEST", 400, "Unknown field: %s" % key)
    cleaned = {}
    for field, spec in schema.items():
        if field not in body:
            if spec.get("required"):
                raise ApiError("ERR_INVALID_REQUEST", 400,
                               "Missing required field: %s" % field)
            continue
        value = body[field]
        if not _check(spec, value):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "Field %s has a wrong type or value" % field)
        if spec["kind"] == "datetime" and value is not None:
            value = db.parse_iso(value)
        cleaned[field] = value
    return cleaned


def require_entity(table, entity_id):
    entity = table.get(entity_id)
    if entity is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found: %s" % entity_id)
    return entity
