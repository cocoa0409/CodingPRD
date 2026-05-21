"""Input validation helpers used across routes."""
from __future__ import annotations

import re
from typing import Any, Optional

from flask import request

from .errors import APIError


def get_json_body() -> dict:
    if not request.data:
        return {}
    try:
        body = request.get_json(silent=False, force=True)
    except Exception:
        raise APIError("ERR_VALIDATION", "Body must be valid JSON", 422)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise APIError("ERR_VALIDATION", "Body must be a JSON object", 422)
    return body


def require_string(body: dict, key: str, *, min_len: int = 1, max_len: Optional[int] = None) -> str:
    val = body.get(key)
    if not isinstance(val, str):
        raise APIError("ERR_VALIDATION", f"'{key}' must be a string", 422)
    if len(val) < min_len:
        raise APIError("ERR_VALIDATION", f"'{key}' must have at least {min_len} characters", 422)
    if max_len is not None and len(val) > max_len:
        raise APIError("ERR_VALIDATION", f"'{key}' must have at most {max_len} characters", 422)
    return val


def optional_string(body: dict, key: str, *, max_len: Optional[int] = None) -> Optional[str]:
    if key not in body or body[key] is None:
        return None
    val = body[key]
    if not isinstance(val, str):
        raise APIError("ERR_VALIDATION", f"'{key}' must be a string", 422)
    if max_len is not None and len(val) > max_len:
        raise APIError("ERR_VALIDATION", f"'{key}' must have at most {max_len} characters", 422)
    return val


def require_int(body: dict, key: str, *, min_val: Optional[int] = None, max_val: Optional[int] = None) -> int:
    if key not in body:
        raise APIError("ERR_VALIDATION", f"'{key}' is required", 422)
    val = body[key]
    if isinstance(val, bool) or not isinstance(val, int):
        raise APIError("ERR_VALIDATION", f"'{key}' must be an integer", 422)
    if min_val is not None and val < min_val:
        raise APIError("ERR_VALIDATION", f"'{key}' must be >= {min_val}", 422)
    if max_val is not None and val > max_val:
        raise APIError("ERR_VALIDATION", f"'{key}' must be <= {max_val}", 422)
    return val


def optional_int(body: dict, key: str, *, default: Optional[int] = None,
                 min_val: Optional[int] = None, max_val: Optional[int] = None) -> Optional[int]:
    if key not in body or body[key] is None:
        return default
    val = body[key]
    if isinstance(val, bool) or not isinstance(val, int):
        raise APIError("ERR_VALIDATION", f"'{key}' must be an integer", 422)
    if min_val is not None and val < min_val:
        raise APIError("ERR_VALIDATION", f"'{key}' must be >= {min_val}", 422)
    if max_val is not None and val > max_val:
        raise APIError("ERR_VALIDATION", f"'{key}' must be <= {max_val}", 422)
    return val


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_email(s: str) -> str:
    if not _EMAIL_RE.match(s):
        raise APIError("ERR_VALIDATION", f"'{s}' is not a valid email", 422)
    return s


_PARK_CODE_RE = re.compile(r"^[A-Z0-9]+$")


def validate_park_code(s: str) -> str:
    if not _PARK_CODE_RE.match(s):
        raise APIError("ERR_VALIDATION", "code must match ^[A-Z0-9]+$", 422)
    if not (2 <= len(s) <= 10):
        raise APIError("ERR_VALIDATION", "code must be 2..10 chars", 422)
    return s
