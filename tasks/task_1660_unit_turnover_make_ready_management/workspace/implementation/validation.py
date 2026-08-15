"""Request shape validation — validation chain step 3 (PRD §2.8)."""
from datetime import datetime, timezone

from flask import request

import db
from errors import ApiError


def _is_string(v):
    return isinstance(v, str)


def _is_integer(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_enum(v, enum_values):
    return isinstance(v, str) and v in enum_values


def _is_date(v):
    return db.is_date_string(v)


def _is_datetime(v):
    return parse_iso_datetime(v) is not None


def _is_str_list(v):
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


def parse_iso_datetime(value):
    """Parse an ISO 8601 datetime (Z or offset) to an aware UTC datetime."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _check(kind, value, enum_values):
    if kind == "string":
        return _is_string(value)
    if kind == "integer":
        return _is_integer(value)
    if kind == "enum":
        return _is_enum(value, enum_values)
    if kind == "date":
        return _is_date(value)
    if kind == "datetime":
        return _is_datetime(value)
    if kind == "str_list":
        return _is_str_list(value)
    return False


def get_body():
    """Return the JSON request body as a dict; empty body counts as {}."""
    raw = request.get_data(cache=True)
    if not raw or not raw.strip():
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be valid JSON")
    if not isinstance(parsed, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Request body must be a JSON object")
    return parsed


def validate_schema(body, schema):
    """Raise ERR_INVALID_REQUEST unless body matches schema exactly:
    required fields present, types valid, enums in domain, unknown fields
    rejected."""
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Request body must be a JSON object")
    for key in body:
        if key not in schema:
            raise ApiError("ERR_INVALID_REQUEST", 400, "Unknown field: %s" % key)
    for field, (kind, required, enum_values) in schema.items():
        if field not in body:
            if required:
                raise ApiError("ERR_INVALID_REQUEST", 400,
                               "Missing required field: %s" % field)
            continue
        if not _check(kind, body[field], enum_values):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "Field %s has an invalid value" % field)
