"""Generic request-body parsing and field validation (ERR_VALIDATION, priority 16).

These helpers enforce required-field presence, type correctness, and enum
membership. They raise ERR_VALIDATION (422) on structural problems, which is the
lowest-priority business check and runs only after auth/existence/ownership/state.
"""
from errors import err


def get_body():
    from flask import request
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_VALIDATION", "request body must be a JSON object")
    return body


def require(body, key):
    if key not in body or body[key] is None:
        raise err("ERR_VALIDATION", f"missing required field: {key}")
    return body[key]


def req_str(body, key):
    v = require(body, key)
    if not isinstance(v, str) or v == "":
        raise err("ERR_VALIDATION", f"field {key} must be a non-empty string")
    return v


def opt_str(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not isinstance(v, str):
        raise err("ERR_VALIDATION", f"field {key} must be a string")
    return v


def req_int(body, key):
    v = require(body, key)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_VALIDATION", f"field {key} must be an integer")
    return v


def opt_int(body, key, default):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_VALIDATION", f"field {key} must be an integer")
    return v


def req_bool_default(body, key, default):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not isinstance(v, bool):
        raise err("ERR_VALIDATION", f"field {key} must be a boolean")
    return v


def req_enum(body, key, allowed):
    v = require(body, key)
    if not isinstance(v, str) or v not in allowed:
        raise err("ERR_VALIDATION", f"field {key} must be one of {sorted(allowed)}")
    return v


def opt_enum(body, key, allowed, default):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not isinstance(v, str) or v not in allowed:
        raise err("ERR_VALIDATION", f"field {key} must be one of {sorted(allowed)}")
    return v


def check_range(value, key, lo=None, hi=None):
    if lo is not None and value < lo:
        raise err("ERR_VALIDATION", f"field {key} must be >= {lo}")
    if hi is not None and value > hi:
        raise err("ERR_VALIDATION", f"field {key} must be <= {hi}")
    return value


def parse_pagination():
    """Parse limit/offset query params (PRD §2.3). limit default 10, min 1, max 100;
    offset default 0. Invalid values are ERR_VALIDATION."""
    from flask import request

    def _int_param(name, default):
        raw = request.args.get(name)
        if raw is None or raw == "":
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", f"query param {name} must be an integer")

    limit = _int_param("limit", 10)
    offset = _int_param("offset", 0)
    if limit < 1 or limit > 100:
        raise err("ERR_VALIDATION", "limit must be between 1 and 100")
    if offset < 0:
        raise err("ERR_VALIDATION", "offset must be >= 0")
    return limit, offset
