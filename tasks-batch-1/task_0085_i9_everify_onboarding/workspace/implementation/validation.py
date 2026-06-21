"""Request-body parsing helpers that map to ERR_INVALID_REQUEST (priority 15).

These are the lowest-priority generic checks (PRD §2.8): required body fields
present and well-typed, enum values within declared domains. They run AFTER all
the higher-priority business checks, so callers invoke them at the position the
priority order dictates, not eagerly.
"""

from errors import err
from clock import parse_iso8601


def get_json_body():
    """Return the JSON body as a dict. A non-object / unparseable body is an
    ERR_INVALID_REQUEST (400)."""
    from flask import request
    if request.method in ("GET", "DELETE"):
        return {}
    # silent=True so a malformed body does not 400 at the framework layer.
    body = request.get_json(silent=True)
    if body is None:
        # An empty body is allowed for endpoints with no required fields.
        if not (request.data or b"").strip():
            return {}
        raise err("ERR_INVALID_REQUEST", "Request body is not valid JSON")
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def require_str(body, field, allow_empty=False):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
    val = body[field]
    if not isinstance(val, str):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a string" % field)
    if not allow_empty and val.strip() == "":
        raise err("ERR_INVALID_REQUEST", "Field %s must be non-empty" % field)
    return val


def optional_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a string" % field)
    return val


def require_enum(body, field, domain):
    val = require_str(body, field)
    if val not in domain:
        raise err("ERR_INVALID_REQUEST",
                  "Field %s must be one of %s" % (field, sorted(domain)))
    return val


def optional_enum(body, field, domain, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str) or val not in domain:
        raise err("ERR_INVALID_REQUEST",
                  "Field %s must be one of %s" % (field, sorted(domain)))
    return val


def optional_bool(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean" % field)
    return val


def require_int(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
    val = body[field]
    # bool is a subclass of int; reject it explicitly.
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % field)
    return val


def optional_int(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % field)
    return val


def require_datetime(body, field):
    val = require_str(body, field)
    try:
        return parse_iso8601(val)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "Field %s must be ISO 8601" % field)


def optional_datetime(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    try:
        parsed = parse_iso8601(val)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "Field %s must be ISO 8601" % field)
    if parsed is None:
        return default
    return parsed
