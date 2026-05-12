"""Common request validation helpers."""
from flask import request

from errors import err


def get_body(required: bool = True) -> dict:
    """Return JSON body or empty dict; never None."""
    if not request.data:
        if required:
            return {}
        return {}
    try:
        body = request.get_json(silent=True)
    except Exception:
        raise err("ERR_BAD_REQUEST", "Invalid JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_BAD_REQUEST", "Body must be a JSON object")
    return body


def require_field(body: dict, name: str):
    if name not in body or body[name] is None:
        raise err("ERR_BAD_REQUEST", f"Missing required field: {name}")
    return body[name]


def require_str(body: dict, name: str, *, min_len: int = 1, max_len: int = 4096) -> str:
    v = require_field(body, name)
    if not isinstance(v, str):
        raise err("ERR_BAD_REQUEST", f"{name} must be a string")
    if len(v) < min_len or len(v) > max_len:
        raise err("ERR_BAD_REQUEST", f"{name} length out of range")
    return v


def require_int(body: dict, name: str, *, ge=None, le=None) -> int:
    v = require_field(body, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_BAD_REQUEST", f"{name} must be an integer")
    if ge is not None and v < ge:
        raise err("ERR_BAD_REQUEST", f"{name} must be >= {ge}")
    if le is not None and v > le:
        raise err("ERR_BAD_REQUEST", f"{name} must be <= {le}")
    return v


def optional_int(body: dict, name: str, *, default=None, ge=None, le=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_BAD_REQUEST", f"{name} must be an integer")
    if ge is not None and v < ge:
        raise err("ERR_BAD_REQUEST", f"{name} must be >= {ge}")
    if le is not None and v > le:
        raise err("ERR_BAD_REQUEST", f"{name} must be <= {le}")
    return v


def require_enum(body: dict, name: str, allowed) -> str:
    v = require_field(body, name)
    if v not in allowed:
        raise err("ERR_BAD_REQUEST", f"{name} must be one of {sorted(allowed)}")
    return v


def optional_enum(body: dict, name: str, allowed, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if v not in allowed:
        raise err("ERR_BAD_REQUEST", f"{name} must be one of {sorted(allowed)}")
    return v


def require_bool(body: dict, name: str, default=None) -> bool:
    if name not in body or body[name] is None:
        if default is None:
            raise err("ERR_BAD_REQUEST", f"Missing required field: {name}")
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise err("ERR_BAD_REQUEST", f"{name} must be boolean")
    return v


def require_reason(body: dict) -> str:
    """For audit-bearing actions, reason must be non-empty."""
    if "reason" not in body or body["reason"] is None or not isinstance(body["reason"], str) or not body["reason"].strip():
        raise err("ERR_REASON_REQUIRED", "Non-empty reason is required")
    return body["reason"]


def check_version(body: dict, current_version: int):
    """Optimistic concurrency check.

    Per PRD §2.5: the version may come from the body or from the If-Match header.
    When neither is provided, the OCC check is skipped.
    Mismatch => ERR_VERSION_CONFLICT.
    """
    supplied = None
    # Body wins if present
    if "version" in body and body["version"] is not None:
        v = body["version"]
        if isinstance(v, bool) or not isinstance(v, int):
            raise err("ERR_BAD_REQUEST", "version must be an integer")
        supplied = v
    else:
        if_match = request.headers.get("If-Match")
        if if_match is not None and if_match != "":
            try:
                supplied = int(if_match)
            except (TypeError, ValueError):
                raise err("ERR_VERSION_CONFLICT", "If-Match header must equal current version")
    if supplied is None:
        return  # OCC skipped
    if supplied != current_version:
        raise err("ERR_VERSION_CONFLICT", "version mismatch")
