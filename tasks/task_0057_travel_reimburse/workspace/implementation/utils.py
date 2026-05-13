"""Helpers: UUIDs, timestamps, money rounding, server clock."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import random
import string
import uuid


def new_uuid() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    chars = string.ascii_uppercase + string.digits
    suffix = "".join(random.choices(chars, k=20))
    return f"req_{suffix}"


# ---------------- Server clock ----------------
# Real wall clock plus a test-controlled offset (advanced via POST /_clock/advance)
class ServerClock:
    def __init__(self):
        self._offset_seconds: float = 0.0

    def advance(self, seconds: float) -> None:
        self._offset_seconds += float(seconds)

    def now(self) -> datetime:
        return datetime.now(timezone.utc) + timedelta(seconds=self._offset_seconds)

    def now_iso(self) -> str:
        return format_ts(self.now())


CLOCK = ServerClock()


def format_ts(dt: datetime) -> str:
    """Return ISO 8601 UTC with exactly 3 fractional digits and 'Z' suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    # exactly 3 fractional digits
    ms = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def parse_ts(value):
    """Parse ISO 8601 string into a tz-aware UTC datetime. Returns None on failure."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if not isinstance(value, str):
        return False  # signal type error
    s = value.strip()
    # Accept 'Z' suffix
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------- Money ----------------
TWOPL = Decimal("0.01")


def to_money(x) -> Decimal:
    """Convert input to Decimal. Returns None if invalid."""
    if x is None:
        return None
    if isinstance(x, Decimal):
        return x
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return Decimal(str(x))
    if isinstance(x, str):
        try:
            return Decimal(x)
        except Exception:
            return None
    return None


def round_money(x: Decimal) -> Decimal:
    """Round to 2 decimal places using ROUND_HALF_UP."""
    if x is None:
        return None
    return Decimal(x).quantize(TWOPL, rounding=ROUND_HALF_UP)


def money_to_float(x: Decimal) -> float:
    if x is None:
        return None
    return float(x)


# Declared holidays (per PRD)
DECLARED_HOLIDAYS = {"2025-01-01", "2025-05-01", "2025-10-01"}
