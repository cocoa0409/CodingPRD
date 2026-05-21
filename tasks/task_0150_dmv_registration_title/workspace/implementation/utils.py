"""Shared utilities — UUID generation, ISO timestamps, decimal half-up rounding.

Per PRD §2.4, ids are UUIDs without prefix and timestamps are ISO 8601 UTC
with three fractional digits. Per PRD §2.6, all monetary math uses Decimal
with ROUND_HALF_UP.
"""

import re
import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

_ALPHANUM = string.ascii_letters + string.digits

VIN_REGEX = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
PLATE_REGEX = re.compile(r"^[A-Z0-9]{2,8}$")
ISO_DATE_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
STATE_REGEX = re.compile(r"^[A-Z]{2}$")


# ---------------------------------------------------------------------------
# ID + request-id generation
# ---------------------------------------------------------------------------
def new_uuid() -> str:
    """Generate a server-minted UUID without any prefix."""
    return str(uuid.uuid4())


def new_request_id() -> str:
    """Generate an api_request_id like req_RANDOMALPHANUM (20 chars after req_)."""
    body = "".join(secrets.choice(_ALPHANUM) for _ in range(20))
    return f"req_{body}"


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------
def iso_format(dt: datetime) -> str:
    """Format a UTC datetime as ISO 8601 with three fractional digits and Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    millis = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def parse_iso8601(s: str) -> datetime:
    """Parse an ISO 8601 string (UTC). Returns timezone-aware UTC datetime.

    Raises ValueError on malformed input.
    """
    if not isinstance(s, str):
        raise ValueError("not a string")
    cleaned = s.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    dt = datetime.fromisoformat(cleaned)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso_date(s: str) -> datetime:
    """Parse an ISO 8601 date (YYYY-MM-DD) into a UTC datetime at 00:00."""
    if not isinstance(s, str) or not ISO_DATE_REGEX.match(s):
        raise ValueError("invalid date string")
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def add_days(when: datetime, days: int) -> datetime:
    return when + timedelta(days=days)


def add_minutes(when: datetime, minutes: int) -> datetime:
    return when + timedelta(minutes=minutes)


def add_years_calendar(when: datetime, years: int) -> datetime:
    """Add `years` whole calendar years."""
    try:
        return when.replace(year=when.year + years)
    except ValueError:
        # Feb 29 -> Feb 28 in non-leap years
        return when.replace(year=when.year + years, day=28)


def floor_age_years(birth_dt: datetime, now: datetime) -> int:
    """Floor of (now - birth_dt) / 365.25 days."""
    delta_days = (now - birth_dt).total_seconds() / 86400.0
    return int(delta_days // 365.25)


# ---------------------------------------------------------------------------
# Decimal helpers
# ---------------------------------------------------------------------------
TWO_PLACES = Decimal("0.01")


def round_half_up_2(value: Decimal) -> Decimal:
    """Round a Decimal half-up to exactly 2 fractional digits."""
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def to_decimal(value) -> Decimal:
    """Coerce numeric/string input to a Decimal. Raises ValueError on bad input."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        # Reject booleans masquerading as numbers
        raise ValueError("boolean is not a number")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        # Convert through string to avoid float artefacts
        return Decimal(str(value))
    if isinstance(value, str):
        return Decimal(value)
    raise ValueError("not a number")


def decimal_to_serial(value: Decimal | None) -> float | None:
    """Serialize a Decimal as a JSON number rounded half-up to 2 places.

    PRD §2.6: monetary amounts are decimals with exactly two fractional
    digits. JSON has no Decimal type — we emit them as JSON numbers
    whose numeric value equals the half-up-rounded 2dp Decimal, which is
    what downstream calculations and equality comparisons depend on.
    """
    if value is None:
        return None
    if not isinstance(value, Decimal):
        value = to_decimal(value)
    return float(round_half_up_2(value))


def decimal_to_cents(value: Decimal) -> int:
    """Convert a Decimal already at 2dp into integer cents."""
    return int((round_half_up_2(value) * Decimal("100")).to_integral_value())
