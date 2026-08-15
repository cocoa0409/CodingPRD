"""Request validation: JSON body shape, field kinds, path/FK existence."""
from datetime import datetime, date, timezone
from flask import request

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


def parse_datetime(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    raw = value
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse a YYYY-MM-DD date string into a date, or None."""
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _is_datetime(v):
    return parse_datetime(v) is not None


def _is_date(v):
    return parse_date(v) is not None


def _is_list(v):
    return isinstance(v, list)


_KIND_CHECKS = {
    "string": _is_string,
    "integer": _is_integer,
    "number": _is_number,
    "boolean": _is_boolean,
    "datetime": _is_datetime,
    "date": _is_date,
    "list": _is_list,
}


def is_integer(v):
    return _is_integer(v)


def validate_schema(body, schema):
    """Raise ERR_INVALID_REQUEST unless body is a dict matching schema.

    schema maps field -> (kind, required, enum_values). Unknown fields are
    ignored (PRD: client-supplied computed/system fields cannot override
    server-managed defaults).
    """
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    for field, (kind, required, enum_values) in schema.items():
        if field not in body:
            if required:
                raise ApiError("ERR_INVALID_REQUEST", 400, "Missing required field: %s" % field)
            continue
        value = body[field]
        if not _KIND_CHECKS[kind](value):
            raise ApiError("ERR_INVALID_REQUEST", 400, "Field %s has wrong type or value" % field)
        if kind == "string" and enum_values is not None and value not in enum_values:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "Field %s must be one of %s" % (field, ",".join(enum_values)))


def json_object():
    """Return the request JSON body if it is an object, else 400."""
    body = request.get_json(silent=True, force=True)
    if body is None or not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return body


def parse_body(schema, allow_empty=True):
    """Parse and validate the JSON request body against schema.

    allow_empty=True permits a missing body only when no required fields exist.
    """
    has_required = any(req for _, req, _ in schema.values())
    body = request.get_json(silent=True, force=True)
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


def require_min_length(body, field, minimum):
    value = body.get(field)
    if not isinstance(value, str) or len(value) < minimum:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field %s must be a string of at least %d characters" % (field, minimum))
    return value
