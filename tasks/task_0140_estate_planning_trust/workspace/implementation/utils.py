"""Shared utilities: ids, timestamps, parsing, rounding."""
from __future__ import annotations

import secrets
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_EVEN, ROUND_HALF_UP


def new_uuid() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"req_{suffix}"


def iso_now(dt: datetime) -> str:
    """ISO 8601 UTC timestamp with exactly three fractional digits and Z suffix.

    Matches PRD §2.4 timestamp format.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    ms = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def parse_iso_datetime(value):
    """Parse an ISO 8601 timestamp into a UTC-aware datetime.

    Returns None on invalid input — callers turn that into ERR_BAD_REQUEST.
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


# ── Rounding ───────────────────────────────────────────────────────────────


def round_half_even(value, places: int = 0) -> Decimal:
    """Banker's rounding (round-half-to-even) to N decimal places."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    q = Decimal("1").scaleb(-places) if places > 0 else Decimal("1")
    return value.quantize(q, rounding=ROUND_HALF_EVEN)


def round_half_up(value, places: int = 0) -> Decimal:
    """Half-up rounding to N decimal places."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    q = Decimal("1").scaleb(-places) if places > 0 else Decimal("1")
    return value.quantize(q, rounding=ROUND_HALF_UP)


# ── Type checks ────────────────────────────────────────────────────────────


def is_non_negative_int(value) -> bool:
    """Reject booleans (since bool is a subtype of int in Python)."""
    if isinstance(value, bool):
        return False
    return isinstance(value, int) and value >= 0
