"""Shared utility helpers: ids, ISO timestamps, business-day arithmetic,
and precision-safe ceiling rounding of percentage-of-notional terms.

These primitives implement the rules in PRD §2.4 (uuid/created_at/updated_at/
version field shapes), §2.6 (business-day calendar Mon-Fri, no holidays),
and §2.7 (per-term ceiling rounding before summation).
"""
from __future__ import annotations

import secrets
import string
import uuid
from datetime import date, datetime, timedelta, timezone


# ── IDs ─────────────────────────────────────────────────────────────────────


def new_uuid() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


# ── Timestamps ──────────────────────────────────────────────────────────────


def iso_utc(dt: datetime) -> str:
    """Format a UTC datetime as ISO 8601 with millisecond precision + 'Z'."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    ms = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def parse_iso_date(value):
    """Parse YYYY-MM-DD into a `date`. Returns None on bad input."""
    if value is None or not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip())
    except Exception:
        return None


def parse_iso_datetime(value):
    """Parse an ISO 8601 string (Z or offset) into a UTC-aware datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def age_years(dob: date, today: date) -> int:
    """Whole-year age of someone born `dob` as of `today` (UTC)."""
    yrs = today.year - dob.year
    # Subtract one if today hasn't reached the birthday this year.
    if (today.month, today.day) < (dob.month, dob.day):
        yrs -= 1
    return yrs


# ── Business-day calendar (Mon–Fri, no holidays) ────────────────────────────


def is_business_day(d: date) -> bool:
    """Weekday() returns 0=Monday .. 6=Sunday."""
    return d.weekday() < 5


def add_business_days(start: date, n: int) -> date:
    """Add `n` business days to `start`. Each loop iteration adds one
    calendar day; if it lands on Mon-Fri, the counter decrements.
    Matches the SCAFFOLD acat_completion_eta algorithm exactly.
    """
    if n <= 0:
        return start
    cur = start
    remaining = n
    while remaining > 0:
        cur = cur + timedelta(days=1)
        if is_business_day(cur):
            remaining -= 1
    return cur


def subtract_business_days(start: date, n: int) -> date:
    """Mirror of add_business_days going backwards."""
    if n <= 0:
        return start
    cur = start
    remaining = n
    while remaining > 0:
        cur = cur - timedelta(days=1)
        if is_business_day(cur):
            remaining -= 1
    return cur


def business_days_between(start_dt: datetime, end_dt: datetime) -> int:
    """Count business days strictly between start_dt's calendar date and
    end_dt's calendar date, inclusive of crossings. The PRD's
    business_days_elapsed counts how many business-day boundaries the
    clock has crossed since `initiated_at`: if initiated at 09:00 UTC
    Monday and queried at 09:00 UTC Tuesday, that's 1 business day
    elapsed. We implement it as the count of business days strictly
    between start_dt.date() and end_dt.date() (exclusive of start,
    inclusive of end).
    """
    if end_dt <= start_dt:
        return 0
    sd = start_dt.date()
    ed = end_dt.date()
    if ed <= sd:
        return 0
    count = 0
    cur = sd
    while cur < ed:
        cur = cur + timedelta(days=1)
        if is_business_day(cur):
            count += 1
    return count


# ── Precision-safe arithmetic (PRD §2.7) ────────────────────────────────────


def ceil_term(notional_cents: int, num: int, denom: int) -> int:
    """Compute ceil(notional * num / denom) using integer math.

    Used for margin terms: notional × (rate as a fraction num/denom) is
    rounded UP to the next whole cent before being summed with other
    terms. The PRD pins ceiling rounding per-term, never on the final
    sum, so this helper is the only path that should compute a margin
    contribution.
    """
    if denom <= 0:
        raise ValueError("denom must be positive")
    if notional_cents < 0:
        # Notional is always non-negative in our domain; guard anyway.
        return 0
    product = notional_cents * num
    q, r = divmod(product, denom)
    if r != 0:
        q += 1
    return q
