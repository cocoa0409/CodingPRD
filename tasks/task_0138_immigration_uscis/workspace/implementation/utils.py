"""Shared utilities: ids, timestamps, parsing helpers, rounding."""
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
    alphabet = string.ascii_uppercase + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"req_{suffix}"


# ── Timestamp formatting / parsing ──────────────────────────────────────────


def iso_now(dt: datetime) -> str:
    """Format a UTC datetime as ISO 8601 with three fractional digits + Z.

    PRD §2.5 specifies that timestamps are ISO 8601 UTC with three fractional
    digits. The format string is exactly `YYYY-MM-DDTHH:MM:SS.mmmZ`.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    ms = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def parse_iso_datetime(value):
    """Parse an ISO 8601 timestamp into a UTC-aware datetime. Returns None on
    invalid input — callers turn that into ERR_VALIDATION.
    """
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
    """Parse an ISO 8601 calendar date (YYYY-MM-DD) into a `date` object.
    Returns None when the value is None, not a string, or malformed.
    """
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


# Strict YYYY-MM (used for VisaBulletin.bulletin_month).
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def is_valid_bulletin_month(value) -> bool:
    if not isinstance(value, str):
        return False
    return _MONTH_RE.match(value) is not None


def date_iso(d) -> str | None:
    """Format a `date` (or `datetime`) as YYYY-MM-DD."""
    if d is None:
        return None
    if isinstance(d, datetime):
        d = d.astimezone(timezone.utc).date() if d.tzinfo else d.date()
    return d.strftime("%Y-%m-%d")


# ── Rounding ────────────────────────────────────────────────────────────────


def round_half_up(value, places: int):
    """Half-up rounding to a given number of decimal places. Returns Decimal."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    q = Decimal("1").scaleb(-places) if places > 0 else Decimal("1")
    return value.quantize(q, rounding=ROUND_HALF_UP)


# ── Email validation ────────────────────────────────────────────────────────


# A minimal RFC-5322-ish sanity check: local@domain.tld, no spaces, single @.
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def is_valid_email(value) -> bool:
    if not isinstance(value, str):
        return False
    return _EMAIL_RE.match(value.strip()) is not None


# ── A-number validation ─────────────────────────────────────────────────────


_A_NUMBER_RE = re.compile(r"^A\d{9}$")


def is_valid_a_number(value) -> bool:
    return isinstance(value, str) and _A_NUMBER_RE.match(value) is not None


# ── ISO 3166-1 alpha-3 (3 uppercase letters) ────────────────────────────────


_COUNTRY_RE = re.compile(r"^[A-Z]{3}$")


def is_valid_country_code(value) -> bool:
    return isinstance(value, str) and _COUNTRY_RE.match(value) is not None


# ── ASC location codes (4..6 uppercase alphanumeric) ────────────────────────


_ASC_RE = re.compile(r"^[A-Z0-9]{4,6}$")


def is_valid_location_code(value) -> bool:
    return isinstance(value, str) and _ASC_RE.match(value) is not None


# ── Field office codes (3..5 uppercase letters) ─────────────────────────────


_FIELD_OFFICE_RE = re.compile(r"^[A-Z]{3,5}$")


def is_valid_field_office_code(value) -> bool:
    return isinstance(value, str) and _FIELD_OFFICE_RE.match(value) is not None


# ── Fiscal-year day arithmetic (for receipt number minting) ─────────────────


def fiscal_year_start(now: datetime) -> int:
    """Return the calendar year whose October-1 starts the fiscal year that
    contains `now`. October..December → that calendar year; otherwise prior
    year (per PRD §2.7).
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.year if now.month >= 10 else now.year - 1


def day_of_fiscal_year(now: datetime) -> int:
    """1..366 — counting from October 1 of fiscal_year_start(now)."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    fy_start = date(fiscal_year_start(now), 10, 1)
    today = now.date()
    return (today - fy_start).days + 1
