"""Shared utilities: money rounding, timestamps, UUID minting, validation helpers."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

import db
import errors


# --- Money (PRD §2.6: 2 decimal places, round half up) ---
_CENTS = Decimal("0.01")


def to_decimal(value):
    """Coerce a numeric/string input into a Decimal without float artifacts."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        # bool is an int subclass; reject so it never silently becomes a number.
        raise ValueError("boolean is not a number")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        return Decimal(value)
    raise ValueError("not a number")


def money(value):
    """Round a Decimal/number to 2 decimal places using round-half-up."""
    return to_decimal(value).quantize(_CENTS, rounding=ROUND_HALF_UP)


def money_out(dec):
    """Render a stored Decimal monetary value as a JSON number with 2 decimals."""
    if dec is None:
        return None
    return float(money(dec))


# --- Time ---
def iso_z(dt):
    """Render a timezone-aware UTC datetime as ISO 8601 with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 instant (accepting a trailing Z) into a UTC datetime."""
    if not isinstance(value, str):
        raise errors.invalid_request("to_iso8601 must be an ISO 8601 string.")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise errors.invalid_request("to_iso8601 is not a valid ISO 8601 instant.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# --- Identity ---
def new_id():
    """Server-minted UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())
