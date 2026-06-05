"""Shared utilities: time parsing/formatting, decimal rounding (PRD §2.4/§2.5)."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import invalid_request


def new_id():
    return str(uuid.uuid4())


def iso_millis(dt):
    """Format a tz-aware datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value, field="timestamp"):
    """Parse an ISO 8601 timestamp string into a tz-aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset. Naive values are treated as UTC.
    """
    if not isinstance(value, str) or not value.strip():
        raise invalid_request(f"Field '{field}' must be an ISO 8601 timestamp string.")
    raw = value.strip()
    try:
        normalized = raw
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        raise invalid_request(f"Field '{field}' is not a valid ISO 8601 timestamp.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_months(dt, months):
    """Add a whole number of months to a datetime (calendar arithmetic)."""
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    # Clamp the day to the last valid day of the target month.
    day = dt.day
    while True:
        try:
            return dt.replace(year=year, month=month, day=day)
        except ValueError:
            day -= 1
            if day < 1:
                raise


def round_half_up_1(value):
    """Round a numeric value to one decimal place, round-half-up. Returns float."""
    d = Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return float(d)


def as_decimal(value):
    return Decimal(str(value))
