"""Generic request validation helpers — used everywhere for ERR_VALIDATION_FAILED."""

from core.errors import raise_error


def require_body(req):
    if not req.is_json:
        body = req.get_json(silent=True)
        if body is None:
            raise_error("ERR_VALIDATION_FAILED", "Request body must be JSON")
        return body
    body = req.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_error("ERR_VALIDATION_FAILED", "Request body must be a JSON object")
    return body


def require_field(body, name, kind=None, allow_zero=True):
    if name not in body or body[name] is None:
        raise_error("ERR_VALIDATION_FAILED", f"Missing required field '{name}'")
    val = body[name]
    if kind == "int":
        if isinstance(val, bool) or not isinstance(val, int):
            raise_error("ERR_VALIDATION_FAILED", f"Field '{name}' must be an integer")
    elif kind == "positive_int":
        if isinstance(val, bool) or not isinstance(val, int) or val <= 0:
            raise_error("ERR_VALIDATION_FAILED", f"Field '{name}' must be a positive integer")
    elif kind == "non_neg_int":
        if isinstance(val, bool) or not isinstance(val, int) or val < 0:
            raise_error("ERR_VALIDATION_FAILED", f"Field '{name}' must be a non-negative integer")
    elif kind == "string":
        if not isinstance(val, str) or not val.strip():
            raise_error("ERR_VALIDATION_FAILED", f"Field '{name}' must be a non-empty string")
    elif kind == "bool":
        if not isinstance(val, bool):
            raise_error("ERR_VALIDATION_FAILED", f"Field '{name}' must be a boolean")
    return val


def require_enum(body, name, allowed):
    v = require_field(body, name, kind="string")
    if v not in allowed:
        raise_error("ERR_VALIDATION_FAILED", f"Field '{name}' must be one of {sorted(allowed)}")
    return v


def require_state_code(body, name):
    v = require_field(body, name, kind="string")
    if len(v) != 2 or not v.isupper() or not v.isalpha():
        raise_error("ERR_VALIDATION_FAILED", f"Field '{name}' must be exactly two uppercase letters")
    return v


def require_ssn_last_four(body, name):
    v = require_field(body, name, kind="string")
    if len(v) != 4 or not v.isdigit():
        raise_error("ERR_VALIDATION_FAILED", f"Field '{name}' must be exactly four digits")
    return v


def require_full_name(body, name, max_len=200):
    v = require_field(body, name, kind="string")
    if len(v) > max_len:
        raise_error("ERR_VALIDATION_FAILED", f"Field '{name}' exceeds maximum length")
    return v


def parse_pagination(req):
    """Parse limit/offset query args. Defaults limit=10, offset=0; limit in [1,100]."""
    limit_raw = req.args.get("limit")
    offset_raw = req.args.get("offset")
    try:
        limit = int(limit_raw) if limit_raw is not None else 10
    except (ValueError, TypeError):
        raise_error("ERR_VALIDATION_FAILED", "limit must be an integer")
    try:
        offset = int(offset_raw) if offset_raw is not None else 0
    except (ValueError, TypeError):
        raise_error("ERR_VALIDATION_FAILED", "offset must be an integer")
    if limit < 1 or limit > 100:
        raise_error("ERR_VALIDATION_FAILED", "limit must be between 1 and 100")
    if offset < 0:
        raise_error("ERR_VALIDATION_FAILED", "offset must be >= 0")
    return limit, offset
