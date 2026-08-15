"""Shared helpers: ids, timestamps, date/datetime parsing, exact decimal math.

PRD 2.4/2.5: created_at / updated_at are ISO 8601 UTC with three fractional
digits; weights are compared exactly as given (no rounding); the single
rounding event in the system is metered practice billing (round half-up to
whole cents once per booking at check-out).
"""
import math
import random
import string
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


_LAST_TS_MS = 0


def now_ts() -> str:
    """Wall-clock ISO 8601 UTC timestamp with three fractional digits.

    Monotonic per process so resources created in a burst still order
    correctly under created_at-ascending list sorts (PRD 2.3).
    """
    global _LAST_TS_MS
    ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    if ms <= _LAST_TS_MS:
        ms = _LAST_TS_MS + 1
    _LAST_TS_MS = ms
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms % 1000:03d}Z"


def parse_datetime(value):
    """Parse an ISO 8601 datetime string; returns aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse an ISO 8601 calendar date (YYYY-MM-DD); returns date or None."""
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def age_years_at(dob: date, at: datetime) -> int:
    """calculations.class_eligibility: floor((event_date - dob) / 365.25 days).

    Ages are reckoned in whole years, always rounded down (PRD 2.5).
    """
    days = (at.date() - dob).days
    return math.floor(Decimal(days) / Decimal("365.25"))


def weight_outcome(measured, minimum) -> str:
    """calculations.weight_compliance: PASS iff measured >= minimum.

    Weights compared exactly as given via Decimal; no rounding (PRD 2.5).
    """
    try:
        m = Decimal(str(measured))
        lo = Decimal(str(minimum))
    except Exception:
        return "FAIL"
    return "PASS" if m >= lo else "FAIL"


# --- practice_billing constants (calculations.practice_billing) -------------
FLAT_SESSION_FEE_CENTS = 4000
RATE_CENTS_PER_MINUTE = 150
TAX_RATE = Decimal("0.0825")


def metered_fee_cents(minutes_used: int) -> int:
    """round_half_up(minutes * RATE * (1 + TAX_RATE)) — per booking, at check-out."""
    val = Decimal(minutes_used) * Decimal(RATE_CENTS_PER_MINUTE) * (Decimal(1) + TAX_RATE)
    return int(val.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def whole_minutes(start: datetime, end: datetime) -> int:
    """(end_time - start_time) in whole minutes."""
    return int((end - start).total_seconds() // 60)
