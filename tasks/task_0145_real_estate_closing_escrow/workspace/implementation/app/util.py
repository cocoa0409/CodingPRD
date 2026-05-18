"""Small utilities: ids, timestamps, decimal rounding, validation helpers."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable

from app.errors import ApiError


def new_uuid() -> str:
    return str(uuid.uuid4())


def now_ts(dt: datetime | None = None) -> str:
    """ISO 8601 UTC with millisecond precision and Z suffix."""
    d = dt or datetime.now(timezone.utc)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    else:
        d = d.astimezone(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def parse_iso_dt(s: str) -> datetime:
    """Parse an ISO 8601 string (Z or +00:00 suffix) into an aware UTC datetime."""
    if not isinstance(s, str):
        raise ApiError("ERR_BAD_REQUEST", "Expected ISO 8601 string.")
    candidate = s.strip()
    # Python's fromisoformat does not natively accept 'Z' suffix before 3.11
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ApiError("ERR_BAD_REQUEST", f"Invalid ISO 8601 instant: {s}") from exc
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def round_half_up_money(value: Any) -> Decimal:
    """Round a decimal to 2 dp using half-up rounding."""
    return _to_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        # bool is a subclass of int; guard against accidental True/False.
        raise ApiError("ERR_BAD_REQUEST", "Expected numeric, got boolean.")
    if isinstance(value, (int,)):
        return Decimal(value)
    if isinstance(value, float):
        # Convert via str to avoid binary-float drift.
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value)
        except Exception as exc:
            raise ApiError("ERR_BAD_REQUEST", f"Invalid decimal: {value}") from exc
    raise ApiError("ERR_BAD_REQUEST", "Expected a numeric value.")


def to_money_float(value: Decimal | float | int) -> float:
    """Convert a 2-dp Decimal to a JSON-friendly float."""
    d = _to_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(d)


def require_field(body: dict, key: str) -> Any:
    if key not in body:
        raise ApiError("ERR_BAD_REQUEST", f"Missing required field: {key}")
    return body[key]


def require_str(body: dict, key: str, *, allow_empty: bool = False) -> str:
    v = require_field(body, key)
    if not isinstance(v, str) or (not allow_empty and not v):
        raise ApiError("ERR_BAD_REQUEST", f"Field {key} must be a non-empty string.")
    return v


def require_number(body: dict, key: str) -> Decimal:
    v = require_field(body, key)
    if isinstance(v, bool):
        raise ApiError("ERR_BAD_REQUEST", f"Field {key} must be numeric.")
    if not isinstance(v, (int, float, str, Decimal)):
        raise ApiError("ERR_BAD_REQUEST", f"Field {key} must be numeric.")
    try:
        return _to_decimal(v)
    except ApiError:
        raise ApiError("ERR_BAD_REQUEST", f"Field {key} must be numeric.")


def optional_number(body: dict, key: str, default: Decimal | int | float = 0) -> Decimal:
    if key not in body or body[key] is None:
        return _to_decimal(default)
    return require_number(body, key)


def require_int(body: dict, key: str) -> int:
    v = require_field(body, key)
    if isinstance(v, bool):
        raise ApiError("ERR_BAD_REQUEST", f"Field {key} must be an integer.")
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str):
        try:
            return int(v)
        except ValueError:
            raise ApiError("ERR_BAD_REQUEST", f"Field {key} must be an integer.")
    raise ApiError("ERR_BAD_REQUEST", f"Field {key} must be an integer.")


def require_enum(body: dict, key: str, allowed: Iterable[str]) -> str:
    v = require_str(body, key)
    allowed_set = set(allowed)
    if v not in allowed_set:
        raise ApiError("ERR_BAD_REQUEST", f"Field {key} must be one of {sorted(allowed_set)}.")
    return v


def optional_enum(body: dict, key: str, allowed: Iterable[str], default: str | None = None) -> str | None:
    if key not in body or body[key] is None:
        return default
    return require_enum(body, key, allowed)


def require_bool(body: dict, key: str) -> bool:
    v = require_field(body, key)
    if not isinstance(v, bool):
        raise ApiError("ERR_BAD_REQUEST", f"Field {key} must be a boolean.")
    return v


def optional_bool(body: dict, key: str, default: bool = False) -> bool:
    if key not in body or body[key] is None:
        return default
    return require_bool(body, key)


def canonical_payload_hash(body: Any) -> str:
    blob = json.dumps(body or {}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
