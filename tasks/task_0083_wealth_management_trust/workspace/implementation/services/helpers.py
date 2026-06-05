"""Shared request helpers: body parsing, field extraction, FK existence."""
from flask import request

import db
from errors import err


def get_json_body():
    """Return the parsed JSON body as a dict, or {} if empty. ERR_VALIDATION if malformed."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_VALIDATION", "Request body is not valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_VALIDATION", "Request body must be a JSON object.")
    return body


def require_str(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_VALIDATION", "Missing required field: " + field)
    val = body[field]
    if not isinstance(val, str) or val == "":
        raise err("ERR_VALIDATION", "Field must be a non-empty string: " + field)
    return val


def require_int(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_VALIDATION", "Missing required field: " + field)
    val = body[field]
    # Reject booleans (bool is subclass of int) and non-ints.
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_VALIDATION", "Field must be an integer: " + field)
    return val


def optional_int(body, field, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_VALIDATION", "Field must be an integer: " + field)
    return val


def optional_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise err("ERR_VALIDATION", "Field must be a boolean: " + field)
    return val


def require_enum(body, field, allowed):
    val = require_str(body, field)
    if val not in allowed:
        raise err("ERR_VALIDATION", "Invalid enum value for " + field)
    return val


def require_datetime(body, field):
    """Require an ISO 8601 datetime string; returns the raw string plus a comparable key."""
    val = require_str(body, field)
    parse_datetime(val, field)  # validate
    return val


def parse_datetime(value, field="datetime"):
    """Parse an ISO 8601 datetime to a comparable float. ERR_VALIDATION on bad input."""
    from datetime import datetime, timezone
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise err("ERR_VALIDATION", "Invalid datetime for " + field)
    # Normalize: treat naive datetimes as UTC so all comparisons are on one scale.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


# ---- FK existence lookups (ERR_NOT_FOUND) ----
def lookup(store, _id):
    return store.get(_id)


def must_exist(store, _id):
    e = store.get(_id)
    if e is None:
        raise err("ERR_NOT_FOUND")
    return e
