"""Shared helpers: timestamps, decimals, pagination, serialization."""

import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import validation


ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)


def new_id() -> str:
    return str(uuid.uuid4())


def now_iso_ms() -> str:
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s, field: str) -> datetime:
    if not isinstance(s, str) or not ISO_RE.match(s):
        raise validation(f"Invalid ISO 8601 timestamp for {field}")
    try:
        v = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        raise validation(f"Invalid ISO 8601 timestamp for {field}")


def dec_to_1dp(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def round_cents(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def to_decimal(x, field: str) -> Decimal:
    try:
        return Decimal(str(x))
    except Exception:
        raise validation(f"Invalid numeric value for {field}")


def fmt_decimal_1dp(d: Decimal) -> float:
    """Format a Decimal at 1dp as a JSON number."""
    return float(d.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def fmt_number(d) -> float:
    """Format a Decimal for JSON output; keep 1dp for lbs."""
    if isinstance(d, Decimal):
        return float(d)
    return d


def get_pagination(args):
    """Read limit/offset query params with defaults; validate range."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise validation("limit must be an integer")
        if limit < 1 or limit > 100:
            raise validation("limit out of range 1..100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise validation("offset must be an integer")
        if offset < 0:
            raise validation("offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    return items[offset: offset + limit], total


def is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def is_number(v) -> bool:
    return (isinstance(v, (int, float)) and not isinstance(v, bool))
