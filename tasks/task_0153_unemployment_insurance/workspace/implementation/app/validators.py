"""Input validation helpers used across routes."""
from __future__ import annotations

import re
from typing import Any, List, Optional

from flask import request

from .errors import APIError


def get_json_body() -> dict:
    if not request.data:
        return {}
    try:
        body = request.get_json(silent=False, force=True)
    except Exception:
        raise APIError("ERR_VALIDATION_FAILED", "Body must be valid JSON", 422)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise APIError("ERR_VALIDATION_FAILED", "Body must be a JSON object", 422)
    return body


def require_string(body: dict, key: str, *, min_len: int = 1, max_len: Optional[int] = None) -> str:
    if key not in body:
        raise APIError("ERR_VALIDATION_FAILED", f"'{key}' is required", 422)
    val = body[key]
    if not isinstance(val, str):
        raise APIError("ERR_VALIDATION_FAILED", f"'{key}' must be a string", 422)
    if len(val) < min_len:
        raise APIError("ERR_VALIDATION_FAILED", f"'{key}' must have at least {min_len} characters", 422)
    if max_len is not None and len(val) > max_len:
        raise APIError("ERR_VALIDATION_FAILED", f"'{key}' must have at most {max_len} characters", 422)
    return val


def optional_string(body: dict, key: str, *, max_len: Optional[int] = None) -> Optional[str]:
    if key not in body or body[key] is None:
        return None
    val = body[key]
    if not isinstance(val, str):
        raise APIError("ERR_VALIDATION_FAILED", f"'{key}' must be a string", 422)
    if max_len is not None and len(val) > max_len:
        raise APIError("ERR_VALIDATION_FAILED", f"'{key}' must have at most {max_len} characters", 422)
    return val


def require_int(body: dict, key: str, *, min_val: Optional[int] = None, max_val: Optional[int] = None) -> int:
    if key not in body:
        raise APIError("ERR_VALIDATION_FAILED", f"'{key}' is required", 422)
    val = body[key]
    if isinstance(val, bool) or not isinstance(val, int):
        raise APIError("ERR_VALIDATION_FAILED", f"'{key}' must be an integer", 422)
    if min_val is not None and val < min_val:
        raise APIError("ERR_VALIDATION_FAILED", f"'{key}' must be >= {min_val}", 422)
    if max_val is not None and val > max_val:
        raise APIError("ERR_VALIDATION_FAILED", f"'{key}' must be <= {max_val}", 422)
    return val


def optional_int(body: dict, key: str, *, default: Optional[int] = None,
                 min_val: Optional[int] = None, max_val: Optional[int] = None) -> Optional[int]:
    if key not in body or body[key] is None:
        return default
    val = body[key]
    if isinstance(val, bool) or not isinstance(val, int):
        raise APIError("ERR_VALIDATION_FAILED", f"'{key}' must be an integer", 422)
    if min_val is not None and val < min_val:
        raise APIError("ERR_VALIDATION_FAILED", f"'{key}' must be >= {min_val}", 422)
    if max_val is not None and val > max_val:
        raise APIError("ERR_VALIDATION_FAILED", f"'{key}' must be <= {max_val}", 422)
    return val


def require_bool(body: dict, key: str) -> bool:
    if key not in body:
        raise APIError("ERR_VALIDATION_FAILED", f"'{key}' is required", 422)
    val = body[key]
    if not isinstance(val, bool):
        raise APIError("ERR_VALIDATION_FAILED", f"'{key}' must be a boolean", 422)
    return val


def require_list(body: dict, key: str) -> List[Any]:
    if key not in body:
        raise APIError("ERR_VALIDATION_FAILED", f"'{key}' is required", 422)
    val = body[key]
    if not isinstance(val, list):
        raise APIError("ERR_VALIDATION_FAILED", f"'{key}' must be a list", 422)
    return val


def require_enum(body: dict, key: str, choices) -> str:
    val = require_string(body, key)
    if val not in choices:
        raise APIError("ERR_VALIDATION_FAILED", f"'{key}' must be one of {sorted(choices)}", 422)
    return val


_SSN4_RE = re.compile(r"^\d{4}$")
_EIN_RE = re.compile(r"^\d{9}$")
_STATE_RE = re.compile(r"^[A-Z]{2}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate_ssn_last4(s: str) -> str:
    if not _SSN4_RE.match(s):
        raise APIError("ERR_VALIDATION_FAILED", "ssn_last4 must be exactly 4 digits", 422)
    return s


def validate_ein(s: str) -> str:
    if not _EIN_RE.match(s):
        raise APIError("ERR_VALIDATION_FAILED", "ein must be exactly 9 digits", 422)
    return s


def validate_state_code(s: str) -> str:
    if not _STATE_RE.match(s):
        raise APIError("ERR_VALIDATION_FAILED", "state_residence must match /^[A-Z]{2}$/", 422)
    return s


def validate_iso_date(s: str, field: str) -> str:
    from .util import parse_iso_date

    if not _DATE_RE.match(s) or parse_iso_date(s) is None:
        raise APIError("ERR_VALIDATION_FAILED", f"'{field}' must be a valid ISO date (YYYY-MM-DD)", 422)
    return s
