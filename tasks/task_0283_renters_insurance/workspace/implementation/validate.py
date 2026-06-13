"""Body parsing / type / enum validation helpers (PRD §2.5).

A malformed body — missing required field, wrong type, invalid enum value —
raises ERR_INVALID_REQUEST (400).
"""
from datetime import datetime, timezone

from errors import err


def get_body():
    """Return the JSON body as a dict. Non-object / unparseable -> ERR_INVALID_REQUEST."""
    from flask import request
    if request.content_length in (None, 0) and not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Malformed JSON body")
    if data is None:
        # No body provided; treat as empty object for endpoints with no required fields.
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Body must be a JSON object")
    return data


def require(body, key):
    if key not in body or body[key] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: {}".format(key))
    return body[key]


def opt(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    return body[key]


def as_str(value, field):
    if not isinstance(value, str) or value == "":
        raise err("ERR_INVALID_REQUEST", "Field {} must be a non-empty string".format(field))
    return value


def as_int(value, field):
    # bool is a subclass of int; reject it explicitly.
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_INVALID_REQUEST", "Field {} must be an integer".format(field))
    return value


def as_bool(value, field):
    if not isinstance(value, bool):
        raise err("ERR_INVALID_REQUEST", "Field {} must be a boolean".format(field))
    return value


def as_enum(value, field, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise err("ERR_INVALID_REQUEST",
                  "Field {} must be one of {}".format(field, sorted(allowed)))
    return value


def as_datetime(value, field):
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", "Field {} must be an ISO 8601 datetime string".format(field))
    dt = parse_iso(value)
    if dt is None:
        raise err("ERR_INVALID_REQUEST", "Field {} is not a valid ISO 8601 datetime".format(field))
    return dt


def parse_iso(value):
    """Parse an ISO 8601 datetime string into a timezone-aware UTC datetime.
    Returns None if unparseable."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
