"""JSON body parsing helpers. Strict on type; unknown fields are tolerated.

A basic malformed body (missing required field, bad enum, type mismatch) yields
ERR_VALIDATION at HTTP 400 (PRD §3.8).
"""

from flask import request
from errors import raise_api


def get_json_body() -> dict:
    """Return a dict from the request JSON body, or {} when absent.

    Raises ERR_VALIDATION when a body is present but not a JSON object.
    """
    if request.content_length in (0, None):
        return {}
    try:
        data = request.get_json(silent=False, force=True)
    except Exception:
        raise_api("ERR_VALIDATION", "Body is not valid JSON")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise_api("ERR_VALIDATION", "Body must be a JSON object")
    return data


def require_string(body: dict, key: str, min_len: int = None, max_len: int = None) -> str:
    if key not in body or body[key] is None:
        raise_api("ERR_VALIDATION", f"Missing required field: {key}")
    val = body[key]
    if not isinstance(val, str):
        raise_api("ERR_VALIDATION", f"{key} must be a string")
    if min_len is not None and len(val) < min_len:
        raise_api("ERR_VALIDATION", f"{key} must be at least {min_len} characters")
    if max_len is not None and len(val) > max_len:
        raise_api("ERR_VALIDATION", f"{key} must be at most {max_len} characters")
    return val


def require_nonempty_string(body: dict, key: str, max_len: int = None) -> str:
    val = require_string(body, key, max_len=max_len)
    if val.strip() == "":
        raise_api("ERR_VALIDATION", f"{key} must be non-empty")
    return val


def optional_string(body: dict, key: str, default=None):
    if key not in body or body[key] is None:
        return default
    val = body[key]
    if not isinstance(val, str):
        raise_api("ERR_VALIDATION", f"{key} must be a string")
    return val


def require_int(body: dict, key: str) -> int:
    if key not in body or body[key] is None:
        raise_api("ERR_VALIDATION", f"Missing required field: {key}")
    val = body[key]
    if isinstance(val, bool) or not isinstance(val, int):
        raise_api("ERR_VALIDATION", f"{key} must be an integer")
    return val


def optional_int(body: dict, key: str, default=None):
    if key not in body or body[key] is None:
        return default
    val = body[key]
    if isinstance(val, bool) or not isinstance(val, int):
        raise_api("ERR_VALIDATION", f"{key} must be an integer")
    return val


def require_enum(body: dict, key: str, allowed: set) -> str:
    val = require_string(body, key)
    if val not in allowed:
        raise_api("ERR_VALIDATION", f"{key} must be one of {sorted(allowed)}")
    return val


def optional_enum(body: dict, key: str, allowed: set, default=None):
    if key not in body or body[key] is None:
        return default
    val = body[key]
    if not isinstance(val, str):
        raise_api("ERR_VALIDATION", f"{key} must be a string")
    if val not in allowed:
        raise_api("ERR_VALIDATION", f"{key} must be one of {sorted(allowed)}")
    return val


def require_bool(body: dict, key: str) -> bool:
    if key not in body or body[key] is None:
        raise_api("ERR_VALIDATION", f"Missing required field: {key}")
    val = body[key]
    if not isinstance(val, bool):
        raise_api("ERR_VALIDATION", f"{key} must be a boolean")
    return val


def optional_bool(body: dict, key: str, default=False) -> bool:
    if key not in body or body[key] is None:
        return default
    val = body[key]
    if not isinstance(val, bool):
        raise_api("ERR_VALIDATION", f"{key} must be a boolean")
    return val


def require_datetime(body: dict, key: str):
    """Require an ISO-8601 string and return the parsed aware UTC datetime."""
    from db import parse_iso
    val = require_string(body, key)
    try:
        return parse_iso(val)
    except ValueError:
        raise_api("ERR_VALIDATION", f"{key} must be an ISO 8601 datetime")


def require_string_array(body: dict, key: str):
    if key not in body or body[key] is None:
        raise_api("ERR_VALIDATION", f"Missing required field: {key}")
    val = body[key]
    if not isinstance(val, list):
        raise_api("ERR_VALIDATION", f"{key} must be an array")
    for item in val:
        if not isinstance(item, str):
            raise_api("ERR_VALIDATION", f"{key} must be an array of strings")
    return val
