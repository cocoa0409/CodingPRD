"""Shared utilities: ids, timestamps, parsing helpers, rounding.

Conforms to PRD §2.4-2.5 (resource identity, timestamps, money/precision).
"""
from __future__ import annotations

import re
import secrets
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP


# ── ID helpers ──────────────────────────────────────────────────────────────


def new_uuid() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    """Generate a request id of the form `req_<20 ALPHANUM chars>` (PRD §2.2)."""
    alphabet = string.ascii_uppercase + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"req_{suffix}"


# ── Timestamp formatting / parsing ──────────────────────────────────────────


def iso_now(dt: datetime) -> str:
    """Format a UTC datetime as ISO 8601 with three fractional digits + Z.

    PRD §2.4-2.5: timestamps are ISO 8601 UTC with three fractional digits.
    Format: `YYYY-MM-DDTHH:MM:SS.mmmZ`.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    ms = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def parse_iso_datetime(value):
    """Parse an ISO 8601 timestamp to a UTC-aware datetime. None on failure."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
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


# Strict YYYY-MM-DD calendar date.
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_iso_date(value):
    """Parse an ISO 8601 calendar date (YYYY-MM-DD) into a `date`. None on failure."""
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def date_iso(d) -> str | None:
    """Format a `date` (or `datetime`) as YYYY-MM-DD."""
    if d is None:
        return None
    if isinstance(d, datetime):
        d = d.astimezone(timezone.utc).date() if d.tzinfo else d.date()
    return d.strftime("%Y-%m-%d")


def add_years(d: date, years: int) -> date:
    """Add `years` whole years to a date, clamping Feb 29 → Feb 28 in non-leap years."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        # Feb 29 in non-leap year → Feb 28
        return d.replace(month=2, day=28, year=d.year + years)


# ── Rounding ────────────────────────────────────────────────────────────────


def round_half_up_int(value) -> int:
    """Round a numeric value (int / float / Decimal / str) half-up to integer."""
    if isinstance(value, int):
        return value
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ── Email validation ────────────────────────────────────────────────────────


# Minimal email sanity check: local@domain.tld, no spaces, single @.
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def is_valid_email(value) -> bool:
    if not isinstance(value, str):
        return False
    return _EMAIL_RE.match(value.strip()) is not None


# ── US state code validation ───────────────────────────────────────────────


_STATE_RE = re.compile(r"^[A-Z]{2}$")


def is_valid_state_code(value) -> bool:
    return isinstance(value, str) and _STATE_RE.match(value) is not None
