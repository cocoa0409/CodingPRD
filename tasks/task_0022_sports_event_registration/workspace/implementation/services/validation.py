"""Common body-validation helpers."""
from errors import err


def require_field(body: dict, field: str):
    if field not in body:
        raise err("ERR_VALIDATION", f"Missing required field: {field}")


def require_str(body: dict, field: str, min_len: int = 1, max_len: int = None) -> str:
    require_field(body, field)
    val = body[field]
    if not isinstance(val, str):
        raise err("ERR_VALIDATION", f"{field} must be a string")
    if len(val) < min_len:
        raise err("ERR_VALIDATION", f"{field} too short")
    if max_len is not None and len(val) > max_len:
        raise err("ERR_VALIDATION", f"{field} too long")
    return val


def require_int(body: dict, field: str, ge: int = None, le: int = None) -> int:
    require_field(body, field)
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_VALIDATION", f"{field} must be an integer")
    if ge is not None and val < ge:
        raise err("ERR_VALIDATION", f"{field} must be >= {ge}")
    if le is not None and val > le:
        raise err("ERR_VALIDATION", f"{field} must be <= {le}")
    return val


def require_bool(body: dict, field: str) -> bool:
    require_field(body, field)
    val = body[field]
    if not isinstance(val, bool):
        raise err("ERR_VALIDATION", f"{field} must be a boolean")
    return val


def require_enum(body: dict, field: str, choices) -> str:
    require_field(body, field)
    val = body[field]
    if val not in choices:
        raise err("ERR_VALIDATION", f"{field} must be one of {sorted(choices)}")
    return val


def require_country(body: dict, field: str) -> str:
    val = require_str(body, field)
    if len(val) != 2 or not val.isalpha() or not val.isupper():
        raise err("ERR_VALIDATION", f"{field} must be a 2-letter uppercase ISO code")
    return val


def opt_team(body: dict, field: str):
    if field not in body:
        return None
    val = body[field]
    if val is None:
        return None
    if not isinstance(val, str):
        raise err("ERR_VALIDATION", f"{field} must be a string or null")
    if len(val) != 3 or not val.isalpha() or not val.isupper():
        raise err("ERR_VALIDATION", f"{field} must be 3 uppercase letters or null")
    return val


def check_version(stored: dict, body: dict):
    """Optimistic concurrency check. If body has 'version', it must match stored."""
    if body and "version" in body and body["version"] is not None:
        v = body["version"]
        if isinstance(v, bool) or not isinstance(v, int):
            raise err("ERR_VALIDATION", "version must be an integer")
        if v != stored.get("version"):
            raise err("ERR_VERSION_CONFLICT", "version mismatch")


def get_body() -> dict:
    """Return the JSON body or empty dict, never None."""
    from flask import request
    if request.data:
        body = request.get_json(silent=True)
        if body is None:
            raise err("ERR_VALIDATION", "Body must be valid JSON")
    else:
        body = {}
    if not isinstance(body, dict):
        raise err("ERR_VALIDATION", "Body must be a JSON object")
    return body
