"""Shared helpers — id generation, timestamps, ISO parsing, rounding."""

import secrets
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

_ALPHANUM = string.ascii_letters + string.digits


def new_uuid() -> str:
    """Generate a server-minted UUID without any prefix."""
    return str(uuid.uuid4())


def new_request_id() -> str:
    """Generate an api_request_id of the form req_RANDOMALPHANUM (20 chars after req_)."""
    body = "".join(secrets.choice(_ALPHANUM) for _ in range(20))
    return f"req_{body}"


def iso_now(now: datetime) -> str:
    """Format a UTC datetime as ISO 8601 with three fractional digits and Z suffix."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    # Render with millisecond precision and Z suffix.
    millis = int(now.microsecond / 1000)
    return now.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def parse_iso8601(s: str) -> datetime:
    """Parse an ISO 8601 string (UTC) tolerantly. Returns timezone-aware UTC datetime.

    Accepts either a trailing 'Z' or an explicit +00:00 offset, and may carry
    fractional-second precision of any length.
    """
    if not isinstance(s, str):
        raise ValueError("not a string")
    # Replace Z with +00:00 so fromisoformat can handle it.
    cleaned = s.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    dt = datetime.fromisoformat(cleaned)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def round_half_up_int(numerator: int, denominator: int) -> int:
    """Return numerator/denominator rounded half-up to the nearest integer.

    Uses Decimal to obtain exact half-up semantics (Python's built-in round()
    uses banker's rounding which is incorrect here per PRD §2.9).
    """
    q = (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)
