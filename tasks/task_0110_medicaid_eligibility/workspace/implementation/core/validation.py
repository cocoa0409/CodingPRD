"""Generic request validation helpers (ERR_INVALID_REQUEST)."""

from core.errors import raise_error


def require_body(req):
    """Parse JSON body, return dict ({} if absent)."""
    if req.content_length is None or req.content_length == 0:
        return {}
    body = req.get_json(silent=True)
    if body is None:
        raise_error("ERR_INVALID_REQUEST", "Request body must be valid JSON")
    if not isinstance(body, dict):
        raise_error("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def require_field(body, name, kind=None):
    if name not in body or body[name] is None:
        raise_error("ERR_INVALID_REQUEST", f"Missing required field '{name}'")
    val = body[name]
    if kind == "string":
        if not isinstance(val, str) or not val.strip():
            raise_error("ERR_INVALID_REQUEST", f"Field '{name}' must be a non-empty string")
    elif kind == "int":
        if isinstance(val, bool) or not isinstance(val, int):
            raise_error("ERR_INVALID_REQUEST", f"Field '{name}' must be an integer")
    elif kind == "number":
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise_error("ERR_INVALID_REQUEST", f"Field '{name}' must be a number")
        if val < 0:
            raise_error("ERR_INVALID_REQUEST", f"Field '{name}' must be non-negative")
    elif kind == "bool":
        if not isinstance(val, bool):
            raise_error("ERR_INVALID_REQUEST", f"Field '{name}' must be a boolean")
    return val


def require_enum(body, name, allowed):
    v = require_field(body, name, kind="string")
    if v not in allowed:
        raise_error("ERR_INVALID_REQUEST", f"Field '{name}' must be one of {sorted(allowed)}")
    return v


def optional_enum(body, name, allowed, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, str) or v not in allowed:
        raise_error("ERR_INVALID_REQUEST", f"Field '{name}' must be one of {sorted(allowed)}")
    return v


def parse_pagination(req):
    """limit/offset (default 10/0, limit in [1,100])."""
    limit_raw = req.args.get("limit")
    offset_raw = req.args.get("offset")
    try:
        limit = int(limit_raw) if limit_raw is not None else 10
    except (ValueError, TypeError):
        raise_error("ERR_INVALID_REQUEST", "limit must be an integer")
    try:
        offset = int(offset_raw) if offset_raw is not None else 0
    except (ValueError, TypeError):
        raise_error("ERR_INVALID_REQUEST", "offset must be an integer")
    if limit < 1 or limit > 100:
        raise_error("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset < 0:
        raise_error("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset
