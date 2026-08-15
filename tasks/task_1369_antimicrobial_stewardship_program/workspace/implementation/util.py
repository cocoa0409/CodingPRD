"""Shared helpers: identifiers, timestamps, decimal math, JSON-safe coercion."""

import re
import uuid
from datetime import datetime, timezone, timedelta

from decimal import Decimal, ROUND_HALF_UP

from errors import err_invalid_request

INITIAL_CLOCK_ISO = "2026-08-01T00:00:00Z"


def new_id() -> str:
    return uuid.uuid4().hex


def new_request_id() -> str:
    return "req_" + uuid.uuid4().hex[:20]


def now_iso() -> str:
    """Wall-clock UTC timestamp with exactly three fractional digits (PRD 2.5)."""
    return _format_ms(datetime.now(timezone.utc))


def _format_ms(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value, field="timestamp"):
    """Parse an ISO-8601 timestamp into an aware UTC datetime."""
    if not isinstance(value, str) or not value.strip():
        raise err_invalid_request(f"{field} must be an ISO 8601 timestamp string")
    text = value.strip()
    try:
        if text.endswith("Z"):
            dt = datetime.fromisoformat(text[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(text)
    except ValueError:
        raise err_invalid_request(f"{field} is not a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_clock(dt: datetime, with_ms: bool) -> str:
    """Serialize a logical-clock timestamp, mirroring the precision style the
    clock was last set with (bare seconds by default)."""
    dt = dt.astimezone(timezone.utc)
    if with_ms:
        return _format_ms(dt)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def clock_has_ms(iso_text: str) -> bool:
    return bool(re.search(r"\.\d+", iso_text))


def round2(value) -> Decimal:
    """Round to exactly 2 decimal places, half-up (PRD 2.6)."""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def to_number(dec: Decimal):
    """Serialize a 2dp Decimal as a JSON number (int when integral)."""
    if dec == dec.to_integral_value():
        return int(dec)
    return float(dec)


def full_years_between(start: datetime, end: datetime) -> int:
    """Whole (anniversary-based) years elapsed from start to end, clamped >= 0."""
    if end <= start:
        return 0
    years = end.year - start.year
    if (end.month, end.day) < (start.month, start.day):
        years -= 1
    return max(0, years)


def month_label(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m")


PERIOD_LABEL_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def valid_period_label(value) -> bool:
    return isinstance(value, str) and bool(PERIOD_LABEL_RE.match(value))


def month_bounds(label: str):
    """Return (start, end) aware datetimes for a YYYY-MM label."""
    year = int(label[:4])
    month = int(label[5:7])
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


def fnv1a_32_hex(text: str) -> str:
    """FNV-1a 32-bit hash rendered as 8 lowercase hex characters."""
    h = 2166136261
    for byte in text.encode("utf-8"):
        h ^= byte
        h = (h * 16777619) & 0xFFFFFFFF
    return f"{h:08x}"


def body_json():
    """Extract a JSON object body; missing/invalid JSON -> ERR_INVALID_REQUEST."""
    from flask import request

    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        raise err_invalid_request("Request body must be valid JSON")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise err_invalid_request("Request body must be a JSON object")
    return payload


def require_fields(payload: dict, fields):
    for field in fields:
        if field not in payload or payload[field] is None:
            raise err_invalid_request(f"Missing required field: {field}")


def require_string(payload: dict, field: str, min_len: int = 1) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or len(value) < min_len:
        raise err_invalid_request(f"{field} must be a string of at least {min_len} characters")
    return value


def require_bool(payload: dict, field: str) -> bool:
    value = payload.get(field)
    if not isinstance(value, bool):
        raise err_invalid_request(f"{field} must be a boolean")
    return value


def require_int(payload: dict, field: str, minimum=None, maximum=None) -> int:
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise err_invalid_request(f"{field} must be an integer")
    if minimum is not None and value < minimum:
        raise err_invalid_request(f"{field} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise err_invalid_request(f"{field} must be <= {maximum}")
    return value


def require_number(payload: dict, field: str, minimum=None, exclusive_minimum=None):
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise err_invalid_request(f"{field} must be a number")
    if minimum is not None and value < minimum:
        raise err_invalid_request(f"{field} must be >= {minimum}")
    if exclusive_minimum is not None and value <= exclusive_minimum:
        raise err_invalid_request(f"{field} must be > {exclusive_minimum}")
    return value


def require_enum(payload: dict, field: str, allowed) -> str:
    value = payload.get(field)
    if value not in allowed:
        raise err_invalid_request(f"{field} must be one of {sorted(allowed)}")
    return value


def optional_bool(payload: dict, field: str, default: bool) -> bool:
    if field not in payload or payload[field] is None:
        return default
    return require_bool(payload, field)


def optional_int(payload: dict, field: str, default: int, minimum=None) -> int:
    if field not in payload or payload[field] is None:
        return default
    return require_int(payload, field, minimum=minimum)


def pagination_params():
    """limit/offset query params per PRD 2.3: limit default 10, 1..100; offset >= 0."""
    from flask import request

    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None or raw_limit == "":
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_invalid_request("limit out of range (1..100)")
    if raw_offset is None or raw_offset == "":
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_invalid_request("offset must be an integer")
        if offset < 0:
            raise err_invalid_request("offset must be >= 0")
    return limit, offset
