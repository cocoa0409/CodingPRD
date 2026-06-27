"""Request body parsing & field validation helpers (PRD §2.6).

All shape/type/enum/range failures raise ERR_INVALID_REQUEST (400).
"""
from datetime import datetime, timezone

from flask import request

from errors import err


def get_body():
    if request.method in ("POST", "PUT", "PATCH"):
        data = request.get_json(silent=True)
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise err("ERR_INVALID_REQUEST", "Body must be a JSON object")
        return data
    return {}


def require_present(body, name):
    if name not in body or body[name] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
    return body[name]


def as_string(value, name):
    if not isinstance(value, str) or value == "":
        raise err("ERR_INVALID_REQUEST", "Field %s must be a non-empty string" % name)
    return value


def opt_string(body, name):
    if name not in body or body[name] is None:
        return None
    return as_string(body[name], name)


def as_int(value, name, minimum=None):
    # bool is a subclass of int — reject it explicitly.
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % name)
    if minimum is not None and value < minimum:
        raise err("ERR_INVALID_REQUEST", "Field %s must be >= %s" % (name, minimum))
    return value


def as_number(value, name, minimum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a number" % name)
    if minimum is not None and value < minimum:
        raise err("ERR_INVALID_REQUEST", "Field %s must be >= %s" % (name, minimum))
    return value


def as_enum(value, name, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise err("ERR_INVALID_REQUEST",
                  "Field %s must be one of %s" % (name, sorted(allowed)))
    return value


def as_datetime(value, name):
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an ISO8601 string" % name)
    return parse_iso(value, name)


def parse_iso(value, name="datetime"):
    s = value.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "Field %s is not a valid ISO8601 instant" % name)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
