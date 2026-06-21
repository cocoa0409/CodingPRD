"""Input parsing / validation helpers.

These produce ERR_INVALID_REQUEST (422) for missing/ill-typed/out-of-range
fields and enum violations (PRD §2.9 priority 5). Foreign-key existence
(ERR_REFERENCE_NOT_FOUND) and uniqueness checks live in the route handlers,
because validation ordering requires FK existence (priority 4) to run BEFORE
field validation (priority 5).
"""
from __future__ import annotations

from typing import Any, Optional

from db import parse_iso
from errors import APIError, ERR_INVALID_REQUEST


def _bad(msg: str):
    raise APIError(ERR_INVALID_REQUEST, 422, msg)


def get_body() -> dict:
    from flask import request

    if request.data and request.data.strip():
        try:
            body = request.get_json(force=True, silent=True)
        except Exception:
            body = None
        if body is None:
            _bad("Request body must be valid JSON")
    else:
        body = {}
    if not isinstance(body, dict):
        _bad("Request body must be a JSON object")
    return body


def require_str(body: dict, key: str, *, non_empty: bool = True) -> str:
    if key not in body or body[key] is None:
        _bad(f"Missing required field: {key}")
    val = body[key]
    if not isinstance(val, str):
        _bad(f"Field {key} must be a string")
    if non_empty and val.strip() == "":
        _bad(f"Field {key} must be non-empty")
    return val


def optional_str(body: dict, key: str, default: Optional[str] = None) -> Optional[str]:
    if key not in body or body[key] is None:
        return default
    val = body[key]
    if not isinstance(val, str):
        _bad(f"Field {key} must be a string")
    return val


def require_int(body: dict, key: str, *, minimum: Optional[int] = None,
                maximum: Optional[int] = None) -> int:
    if key not in body or body[key] is None:
        _bad(f"Missing required field: {key}")
    return _coerce_int(body[key], key, minimum, maximum)


def optional_int(body: dict, key: str, default: Optional[int] = None, *,
                 minimum: Optional[int] = None, maximum: Optional[int] = None) -> Optional[int]:
    if key not in body or body[key] is None:
        return default
    return _coerce_int(body[key], key, minimum, maximum)


def _coerce_int(val: Any, key: str, minimum, maximum) -> int:
    # Booleans are not acceptable integers.
    if isinstance(val, bool) or not isinstance(val, int):
        _bad(f"Field {key} must be an integer")
    if minimum is not None and val < minimum:
        _bad(f"Field {key} must be >= {minimum}")
    if maximum is not None and val > maximum:
        _bad(f"Field {key} must be <= {maximum}")
    return val


def optional_bool(body: dict, key: str, default: bool = False) -> bool:
    if key not in body or body[key] is None:
        return default
    val = body[key]
    if not isinstance(val, bool):
        _bad(f"Field {key} must be a boolean")
    return val


def require_enum(body: dict, key: str, choices) -> str:
    val = require_str(body, key)
    if val not in choices:
        _bad(f"Field {key} must be one of {sorted(choices)}")
    return val


def optional_enum(body: dict, key: str, choices, default: Optional[str] = None) -> Optional[str]:
    if key not in body or body[key] is None:
        return default
    val = body[key]
    if not isinstance(val, str) or val not in choices:
        _bad(f"Field {key} must be one of {sorted(choices)}")
    return val


def require_datetime(body: dict, key: str):
    val = require_str(body, key)
    try:
        return parse_iso(val)
    except Exception:
        _bad(f"Field {key} must be a valid ISO 8601 datetime")


def require_date(body: dict, key: str) -> str:
    """ISO date YYYY-MM-DD. Returns the original string; caller parses as needed."""
    import datetime as _dt

    val = require_str(body, key)
    try:
        _dt.date.fromisoformat(val)
    except Exception:
        _bad(f"Field {key} must be an ISO date YYYY-MM-DD")
    return val
