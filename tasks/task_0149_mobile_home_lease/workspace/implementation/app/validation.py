"""Request body validation primitives. Raises ApiError on failure."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from flask import request

from .errors import ApiError


def get_json_body() -> dict[str, Any]:
    if request.method in ("GET", "DELETE"):
        return {}
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_VALIDATION", "Request body is not valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object.")
    return body


def require_field(body: dict[str, Any], name: str) -> Any:
    if name not in body or body[name] is None:
        raise ApiError("ERR_VALIDATION", f"Missing required field: {name}")
    return body[name]


def require_string(body: dict[str, Any], name: str, *, min_len: int = 1, max_len: Optional[int] = None) -> str:
    val = require_field(body, name)
    if not isinstance(val, str):
        raise ApiError("ERR_VALIDATION", f"Field {name} must be a string.")
    if len(val) < min_len:
        raise ApiError("ERR_VALIDATION", f"Field {name} must be at least {min_len} characters.")
    if max_len is not None and len(val) > max_len:
        raise ApiError("ERR_VALIDATION", f"Field {name} must be at most {max_len} characters.")
    return val


def require_int(
    body: dict[str, Any],
    name: str,
    *,
    minimum: Optional[int] = None,
    maximum: Optional[int] = None,
    strict_positive: bool = False,
) -> int:
    val = require_field(body, name)
    if isinstance(val, bool) or not isinstance(val, int):
        raise ApiError("ERR_VALIDATION", f"Field {name} must be an integer.")
    if strict_positive and val <= 0:
        raise ApiError("ERR_VALIDATION", f"Field {name} must be strictly positive.")
    if minimum is not None and val < minimum:
        raise ApiError("ERR_VALIDATION", f"Field {name} must be at least {minimum}.")
    if maximum is not None and val > maximum:
        raise ApiError("ERR_VALIDATION", f"Field {name} must be at most {maximum}.")
    return val


def require_number(
    body: dict[str, Any],
    name: str,
    *,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
) -> float:
    val = require_field(body, name)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise ApiError("ERR_VALIDATION", f"Field {name} must be a number.")
    val_f = float(val)
    if minimum is not None and val_f < minimum:
        raise ApiError("ERR_VALIDATION", f"Field {name} must be at least {minimum}.")
    if maximum is not None and val_f > maximum:
        raise ApiError("ERR_VALIDATION", f"Field {name} must be at most {maximum}.")
    return val_f


def require_enum(body: dict[str, Any], name: str, allowed: Iterable[str]) -> str:
    val = require_string(body, name)
    if val not in set(allowed):
        raise ApiError("ERR_VALIDATION", f"Field {name} must be one of {sorted(allowed)}.")
    return val


def optional_int(body: dict[str, Any], name: str, default: Optional[int] = None, **kwargs) -> Optional[int]:
    if name not in body or body[name] is None:
        return default
    return require_int(body, name, **kwargs)


def optional_number(body: dict[str, Any], name: str, default: Optional[float] = None, **kwargs) -> Optional[float]:
    if name not in body or body[name] is None:
        return default
    return require_number(body, name, **kwargs)


def optional_string(body: dict[str, Any], name: str, default: Optional[str] = None, **kwargs) -> Optional[str]:
    if name not in body or body[name] is None:
        return default
    return require_string(body, name, **kwargs)


def parse_datetime(body: dict[str, Any], name: str, *, required: bool = True) -> Optional[datetime]:
    if name not in body or body[name] is None:
        if required:
            raise ApiError("ERR_VALIDATION", f"Missing required field: {name}")
        return None
    val = body[name]
    if not isinstance(val, str):
        raise ApiError("ERR_VALIDATION", f"Field {name} must be an ISO 8601 string.")
    return _parse_iso8601(val, name)


def _parse_iso8601(val: str, field_name: str) -> datetime:
    s = val.strip()
    # Normalise trailing 'Z' to +00:00 for fromisoformat compatibility
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError("ERR_VALIDATION", f"Field {field_name} must be an ISO 8601 timestamp.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


# RFC 5322-ish e-mail validation: permissive but rejects obvious garbage
_EMAIL_RE = re.compile(
    r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$"
)


def require_email(body: dict[str, Any], name: str) -> str:
    val = require_string(body, name)
    if not _EMAIL_RE.match(val):
        raise ApiError("ERR_VALIDATION", f"Field {name} is not a valid email.")
    return val


_VIN_RE = re.compile(r"^[A-Z0-9]{17}$")


def require_vin(body: dict[str, Any], name: str) -> str:
    val = require_string(body, name)
    if not _VIN_RE.match(val):
        raise ApiError("ERR_VALIDATION", f"Field {name} must be exactly 17 uppercase letters/digits.")
    return val


def parse_pagination(default_limit: int = 10, min_limit: int = 1, max_limit: int = 100) -> tuple[int, int]:
    limit_raw = request.args.get("limit", str(default_limit))
    offset_raw = request.args.get("offset", "0")
    try:
        limit = int(limit_raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", "Query parameter 'limit' must be an integer.")
    try:
        offset = int(offset_raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", "Query parameter 'offset' must be an integer.")
    if limit < min_limit or limit > max_limit:
        raise ApiError(
            "ERR_VALIDATION",
            f"Query parameter 'limit' must be between {min_limit} and {max_limit}.",
        )
    if offset < 0:
        raise ApiError("ERR_VALIDATION", "Query parameter 'offset' must be >= 0.")
    return limit, offset


__all__ = [
    "get_json_body",
    "require_field",
    "require_string",
    "require_int",
    "require_number",
    "require_enum",
    "optional_int",
    "optional_number",
    "optional_string",
    "parse_datetime",
    "require_email",
    "require_vin",
    "parse_pagination",
]
