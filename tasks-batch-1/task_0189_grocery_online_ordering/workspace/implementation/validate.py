"""Request body parsing + field-level validation (ERR_VALIDATION, PRD §2.10).

Malformed bodies, missing required fields, and invalid enum/type values all
surface as ERR_VALIDATION (400).
"""
from flask import request

from errors import err, ERR_VALIDATION


def get_body():
    """Return the JSON body as a dict. Missing body is treated as empty (for
    transition endpoints with no input). A present-but-non-object body is a
    malformed request."""
    if request.content_length in (None, 0) and not (request.data or b"").strip():
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        err(ERR_VALIDATION, "Request body is not valid JSON")
    if data is None:
        return {}
    if not isinstance(data, dict):
        err(ERR_VALIDATION, "Request body must be a JSON object")
    return data


def require(body, field):
    if field not in body or body[field] is None:
        err(ERR_VALIDATION, "Missing required field: %s" % field)
    return body[field]


def require_str(body, field):
    v = require(body, field)
    if not isinstance(v, str) or not v.strip():
        err(ERR_VALIDATION, "Field %s must be a non-empty string" % field)
    return v


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        err(ERR_VALIDATION, "Field %s must be a string" % field)
    return v


def require_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        err(ERR_VALIDATION, "Field %s must be a boolean" % field)
    return v


def require_int(body, field, minimum=None):
    v = require(body, field)
    v = _as_int(v, field)
    if minimum is not None and v < minimum:
        err(ERR_VALIDATION, "Field %s must be >= %s" % (field, minimum))
    return v


def opt_int(body, field, default, minimum=None):
    if field not in body or body[field] is None:
        return default
    v = _as_int(body[field], field)
    if minimum is not None and v < minimum:
        err(ERR_VALIDATION, "Field %s must be >= %s" % (field, minimum))
    return v


def _as_int(v, field):
    # bool is a subclass of int; reject it explicitly.
    if isinstance(v, bool) or not isinstance(v, int):
        err(ERR_VALIDATION, "Field %s must be an integer" % field)
    return v


def require_number(body, field, positive=False, minimum=None):
    v = require(body, field)
    return _as_number(v, field, positive=positive, minimum=minimum)


def opt_number(body, field, default=None, positive=False, minimum=None):
    if field not in body or body[field] is None:
        return default
    return _as_number(body[field], field, positive=positive, minimum=minimum)


def _as_number(v, field, positive=False, minimum=None):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        err(ERR_VALIDATION, "Field %s must be a number" % field)
    if positive and not (v > 0):
        err(ERR_VALIDATION, "Field %s must be > 0" % field)
    if minimum is not None and v < minimum:
        err(ERR_VALIDATION, "Field %s must be >= %s" % (field, minimum))
    return v


def require_enum(body, field, choices):
    v = require(body, field)
    if v not in choices:
        err(ERR_VALIDATION, "Field %s must be one of %s" % (field, sorted(choices)))
    return v


def opt_enum(body, field, choices, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if v not in choices:
        err(ERR_VALIDATION, "Field %s must be one of %s" % (field, sorted(choices)))
    return v
