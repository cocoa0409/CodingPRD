"""Time, id, and decimal helpers for the Airport Rates & Charges API.

All business-rule time is driven by a logical clock (see db.store). Resource
timestamps are stamped from the logical clock, formatted as ISO 8601 UTC with
three fractional digits. The meta envelope timestamp uses the wall clock.
"""
import re
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_iso(value):
    """Parse an ISO 8601 string (date-only or datetime, 'Z' or offset).

    Returns an aware UTC datetime, or None if unparseable.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if ISO_DATE_RE.match(s):
        s = s + "T00:00:00Z"
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_iso(dt):
    """Format an aware datetime as ISO 8601 UTC with 3 fractional digits."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{dt.microsecond // 1000:03d}Z"


def wall_now_iso():
    return fmt_iso(datetime.now(timezone.utc))


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + uuid.uuid4().hex[:24]


def rhu_div(numer, denom):
    """round_half_up(numer / denom) to a whole cent, integer result."""
    q = (Decimal(numer) / Decimal(denom)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


def rhu_div_2dp(numer, denom):
    """round_half_up(numer / denom) to two decimal places, returned as string-safe number."""
    q = (Decimal(numer) / Decimal(denom)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(q)


def ceil_pct_div(base, pct, denom):
    """ceil(base * pct / denom) as an integer (round toward +infinity)."""
    q = (Decimal(base) * Decimal(pct) / Decimal(denom)).quantize(Decimal("1"), rounding=ROUND_CEILING)
    return int(q)


def days_later(dt, days):
    return dt + timedelta(days=days)
