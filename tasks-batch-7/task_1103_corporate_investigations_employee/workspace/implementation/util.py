"""Datetime, decimal and id helpers.

All persisted datetimes are whole-second UTC and serialize as
`YYYY-MM-DDTHH:MM:SSZ` — the logical clock canonical form used throughout the
PRD's examples (e.g. `2026-05-01T00:00:00Z`). Comparisons are at second
precision per §2.9.
"""
import re
import secrets
import uuid
from datetime import datetime, timezone

from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

_CLOCK_DEFAULT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + secrets.token_hex(8)


def request_timestamp():
    """meta.api_request_timestamp: ISO 8601 UTC with three fractional digits."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO8601 string to an aware UTC datetime truncated to seconds.

    Returns None when the value is not a valid datetime string.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def fmt_dt(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def round2(value):
    """Round half-up to 2 decimal places -> float."""
    return float(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def round0(value):
    """Round half-up to an integer -> int."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_int(value):
    return int(Decimal(value).to_integral_value(rounding=ROUND_CEILING))


def dec(x):
    return x if isinstance(x, Decimal) else Decimal(str(x))
