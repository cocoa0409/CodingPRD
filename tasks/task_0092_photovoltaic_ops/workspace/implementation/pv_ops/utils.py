"""Validation helpers, decimal arithmetic, datetime parsing."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable, Optional

from pv_ops.errors import APIError, ERR_VALIDATION


# ---- Decimal helpers ----
def D(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value: Any, places: int) -> Decimal:
    quant = Decimal("1").scaleb(-places)  # 10^-places
    return D(value).quantize(quant, rounding=ROUND_HALF_UP)


def to_float(value: Decimal) -> float:
    return float(value)


def round_to_float(value: Any, places: int) -> float:
    return float(round_half_up(value, places))


# ---- Datetime helpers ----
def parse_dt(raw: Any, field: str) -> datetime:
    if raw is None:
        raise APIError(ERR_VALIDATION, 422, f"Missing datetime field {field}")
    if isinstance(raw, datetime):
        if raw.tzinfo is None:
            raw = raw.replace(tzinfo=timezone.utc)
        return raw.astimezone(timezone.utc)
    if not isinstance(raw, str):
        raise APIError(ERR_VALIDATION, 422, f"Invalid datetime for {field}")
    s = raw.strip()
    # Normalize trailing Z
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise APIError(ERR_VALIDATION, 422, f"Invalid datetime for {field}: {raw}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_dt_opt(raw: Any, field: str) -> Optional[datetime]:
    if raw is None:
        return None
    return parse_dt(raw, field)


def fmt_dt(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


# ---- Body / type helpers ----
def get_body() -> dict:
    from flask import request

    try:
        data = request.get_json(silent=True, force=True) or {}
    except Exception:
        data = {}
    if not isinstance(data, dict):
        raise APIError(ERR_VALIDATION, 422, "Request body must be a JSON object")
    return data


def require_field(body: dict, name: str) -> Any:
    if name not in body or body[name] is None:
        raise APIError(ERR_VALIDATION, 422, f"Missing required field {name}")
    return body[name]


def require_str(body: dict, name: str, *, min_len: int = 1, max_len: int = 10**9) -> str:
    val = require_field(body, name)
    if not isinstance(val, str):
        raise APIError(ERR_VALIDATION, 422, f"{name} must be a string")
    if not (min_len <= len(val) <= max_len):
        raise APIError(ERR_VALIDATION, 422, f"{name} length out of range")
    return val


def opt_str(body: dict, name: str) -> Optional[str]:
    if name not in body or body[name] is None:
        return None
    val = body[name]
    if not isinstance(val, str):
        raise APIError(ERR_VALIDATION, 422, f"{name} must be a string")
    return val


def require_number(body: dict, name: str, *, ge: Optional[float] = None, le: Optional[float] = None) -> float:
    val = require_field(body, name)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise APIError(ERR_VALIDATION, 422, f"{name} must be a number")
    if ge is not None and val < ge:
        raise APIError(ERR_VALIDATION, 422, f"{name} must be >= {ge}")
    if le is not None and val > le:
        raise APIError(ERR_VALIDATION, 422, f"{name} must be <= {le}")
    return float(val)


def opt_number(body: dict, name: str, *, ge: Optional[float] = None, le: Optional[float] = None) -> Optional[float]:
    if name not in body or body[name] is None:
        return None
    return require_number(body, name, ge=ge, le=le)


def require_int(body: dict, name: str, *, ge: Optional[int] = None, le: Optional[int] = None) -> int:
    val = require_field(body, name)
    if isinstance(val, bool) or not isinstance(val, int):
        raise APIError(ERR_VALIDATION, 422, f"{name} must be an integer")
    if ge is not None and val < ge:
        raise APIError(ERR_VALIDATION, 422, f"{name} must be >= {ge}")
    if le is not None and val > le:
        raise APIError(ERR_VALIDATION, 422, f"{name} must be <= {le}")
    return val


def opt_int(body: dict, name: str, *, ge: Optional[int] = None, le: Optional[int] = None) -> Optional[int]:
    if name not in body or body[name] is None:
        return None
    return require_int(body, name, ge=ge, le=le)


def require_bool(body: dict, name: str) -> bool:
    val = require_field(body, name)
    if not isinstance(val, bool):
        raise APIError(ERR_VALIDATION, 422, f"{name} must be boolean")
    return val


def opt_bool(body: dict, name: str, default: bool = False) -> bool:
    if name not in body or body[name] is None:
        return default
    if not isinstance(body[name], bool):
        raise APIError(ERR_VALIDATION, 422, f"{name} must be boolean")
    return body[name]


def require_enum(body: dict, name: str, allowed: Iterable[str]) -> str:
    val = require_str(body, name)
    if val not in allowed:
        raise APIError(ERR_VALIDATION, 422, f"{name} must be one of {sorted(allowed)}")
    return val


def opt_enum(body: dict, name: str, allowed: Iterable[str]) -> Optional[str]:
    if name not in body or body[name] is None:
        return None
    val = body[name]
    if not isinstance(val, str) or val not in allowed:
        raise APIError(ERR_VALIDATION, 422, f"{name} must be one of {sorted(allowed)}")
    return val


def require_list(body: dict, name: str, *, min_len: int = 0, max_len: int = 10**9) -> list:
    val = require_field(body, name)
    if not isinstance(val, list):
        raise APIError(ERR_VALIDATION, 422, f"{name} must be a list")
    if not (min_len <= len(val) <= max_len):
        raise APIError(ERR_VALIDATION, 422, f"{name} length out of range")
    return val


def opt_list(body: dict, name: str) -> Optional[list]:
    if name not in body or body[name] is None:
        return None
    if not isinstance(body[name], list):
        raise APIError(ERR_VALIDATION, 422, f"{name} must be a list")
    return body[name]


def parse_pagination(args) -> tuple[int, int]:
    """Parse `limit` (default 10, 1..100) and `offset` (default 0, >= 0)."""
    try:
        limit = int(args.get("limit", 10))
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        raise APIError(ERR_VALIDATION, 422, "Invalid pagination parameters")
    if limit < 1 or limit > 100:
        raise APIError(ERR_VALIDATION, 422, "limit must be in [1, 100]")
    if offset < 0:
        raise APIError(ERR_VALIDATION, 422, "offset must be >= 0")
    return limit, offset
