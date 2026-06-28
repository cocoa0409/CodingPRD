"""Shared helpers: clock, timestamps, UUIDs, datetime parsing, rounding."""
import uuid
import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4): default 2026-01-01T00:00:00Z, never falls back to
# real wall-clock. Reset to default on every fresh process boot.
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = DEFAULT_CLOCK

    def get(self):
        return self.now

    def set(self, dt):
        self.now = dt


clock = Clock()


def new_uuid():
    return str(uuid.uuid4())


def now_iso():
    """Server wall-clock ISO timestamp with 3 fractional digits (for created_at/
    updated_at/meta). These audit timestamps use real time; only domain temporal
    rules use the logical clock."""
    return _fmt_ms(datetime.now(timezone.utc))


def _fmt_ms(dt):
    # ISO 8601 UTC with exactly three fractional digits and a trailing Z.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def request_id():
    rnd = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + rnd


def parse_dt(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.
    Returns None on failure."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def round_half_up(value):
    """Round a numeric value to a whole number, half-up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_to_int(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_FLOOR))


def days_between_floor(start_dt, end_dt, seconds_per_day=86400):
    delta = (end_dt - start_dt).total_seconds()
    if delta <= 0:
        return 0
    return int(delta // seconds_per_day)
