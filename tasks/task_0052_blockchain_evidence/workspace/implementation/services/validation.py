"""Body parsing + generic validation helpers."""
from flask import request

from errors import err


def get_body(required_object: bool = True) -> dict:
    """Parse the JSON body; return {} for missing bodies on POSTs that allow it."""
    if not request.data:
        if required_object:
            return {}
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_VALIDATION_FAILED", "Request body is not valid JSON")
    if body is None:
        if required_object:
            return {}
        return {}
    if not isinstance(body, dict):
        raise err("ERR_VALIDATION_FAILED", "Request body must be a JSON object")
    return body


def require_str(body: dict, key: str, *, max_len: int = None, non_empty: bool = True) -> str:
    v = body.get(key)
    if not isinstance(v, str):
        raise err("ERR_VALIDATION_FAILED", f"{key} must be a string")
    if non_empty and not v:
        raise err("ERR_VALIDATION_FAILED", f"{key} must be non-empty")
    if max_len is not None and len(v) > max_len:
        raise err("ERR_VALIDATION_FAILED", f"{key} exceeds max length {max_len}")
    return v


def require_int(body: dict, key: str, *, min_val: int = None, max_val: int = None) -> int:
    v = body.get(key)
    if not isinstance(v, int) or isinstance(v, bool):
        raise err("ERR_VALIDATION_FAILED", f"{key} must be an integer")
    if min_val is not None and v < min_val:
        raise err("ERR_VALIDATION_FAILED", f"{key} must be >= {min_val}")
    if max_val is not None and v > max_val:
        raise err("ERR_VALIDATION_FAILED", f"{key} must be <= {max_val}")
    return v


def require_enum(body: dict, key: str, allowed: set) -> str:
    v = body.get(key)
    if not isinstance(v, str) or v not in allowed:
        raise err("ERR_VALIDATION_FAILED",
                  f"{key} must be one of {sorted(list(allowed))}")
    return v


def maybe_check_version(body: dict, stored: dict) -> None:
    """If body supplies `version`, compare to stored entity's version.

    No-op when the field is omitted (per PRD §2.5).
    """
    if "version" not in body:
        return
    supplied = body.get("version")
    if not isinstance(supplied, int) or isinstance(supplied, bool):
        raise err("ERR_VERSION_CONFLICT", "version must be integer")
    if supplied != stored.get("version"):
        raise err("ERR_VERSION_CONFLICT",
                  f"version mismatch: expected {stored.get('version')}, got {supplied}")


def is_hex_lower(s: str, length: int) -> bool:
    if not isinstance(s, str) or len(s) != length:
        return False
    for ch in s:
        if ch not in "0123456789abcdef":
            return False
    return True
