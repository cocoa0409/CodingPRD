"""JSON body parsing helpers. Strict on type — unknown fields are tolerated."""

from flask import request
from errors import raise_api


def get_json_body() -> dict:
    """Return a dict from the request JSON body, or {} if absent.

    Raises ERR_INVALID_REQUEST when the body is present but not a JSON object.
    """
    if request.content_length in (0, None):
        # No body provided — treat as empty for endpoints that accept no input
        return {}
    try:
        data = request.get_json(silent=False, force=True)
    except Exception:
        raise_api("ERR_INVALID_REQUEST", "Body is not valid JSON")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise_api("ERR_INVALID_REQUEST", "Body must be a JSON object")
    return data


def require_string(body: dict, key: str, min_len: int = None, max_len: int = None) -> str:
    if key not in body:
        raise_api("ERR_INVALID_REQUEST", f"Missing required field: {key}")
    val = body[key]
    if not isinstance(val, str):
        raise_api("ERR_INVALID_REQUEST", f"{key} must be a string")
    if min_len is not None and len(val) < min_len:
        raise_api("ERR_INVALID_REQUEST", f"{key} must be at least {min_len} characters")
    if max_len is not None and len(val) > max_len:
        raise_api("ERR_INVALID_REQUEST", f"{key} must be at most {max_len} characters")
    return val


def require_int(body: dict, key: str) -> int:
    if key not in body:
        raise_api("ERR_INVALID_REQUEST", f"Missing required field: {key}")
    val = body[key]
    if isinstance(val, bool) or not isinstance(val, int):
        raise_api("ERR_INVALID_REQUEST", f"{key} must be an integer")
    return val


def optional_int(body: dict, key: str, default=None):
    if key not in body or body[key] is None:
        return default
    val = body[key]
    if isinstance(val, bool) or not isinstance(val, int):
        raise_api("ERR_INVALID_REQUEST", f"{key} must be an integer")
    return val


def require_enum(body: dict, key: str, allowed: set) -> str:
    val = require_string(body, key)
    if val not in allowed:
        raise_api("ERR_INVALID_REQUEST", f"{key} must be one of {sorted(allowed)}")
    return val


def optional_enum(body: dict, key: str, allowed: set, default=None):
    if key not in body or body[key] is None:
        return default
    val = body[key]
    if not isinstance(val, str):
        raise_api("ERR_INVALID_REQUEST", f"{key} must be a string")
    if val not in allowed:
        raise_api("ERR_INVALID_REQUEST", f"{key} must be one of {sorted(allowed)}")
    return val


def optional_string(body: dict, key: str, default=None):
    if key not in body or body[key] is None:
        return default
    val = body[key]
    if not isinstance(val, str):
        raise_api("ERR_INVALID_REQUEST", f"{key} must be a string")
    return val
