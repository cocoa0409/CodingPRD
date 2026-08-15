"""Shared helpers: logical clock, timestamps, envelope, ids, rounding."""

import random
import string
import uuid
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal, ROUND_HALF_UP

from db import STORE

CLOCK_START_ISO = "2026-08-01T00:00:00Z"


def iso_to_ms(iso_str: str) -> int:
    """Parse an ISO-8601 timestamp (with Z or offset, optional fractional seconds) to epoch ms."""
    if not isinstance(iso_str, str):
        raise ValueError("not a string")
    s = iso_str.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(round(dt.timestamp() * 1000))


def ms_to_iso(ms: int) -> str:
    """Format epoch ms as ISO-8601 UTC with three fractional digits, Z suffix."""
    dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    # build with exactly 3 fractional digits
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    frac = f"{int(dt.microsecond / 1000):03d}"
    return f"{base}.{frac}Z"


def current_clock_ms() -> int:
    return STORE.current_utc_ms


def current_clock_iso() -> str:
    return ms_to_iso(STORE.current_utc_ms)


def new_resource_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return f"req_{suffix}"


def now_iso() -> str:
    """Server wall-clock timestamp for meta.api_request_timestamp (ISO 8601 UTC, 3 fractional digits)."""
    dt = datetime.now(tz=timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    frac = f"{int(dt.microsecond / 1000):03d}"
    return f"{base}.{frac}Z"


def date_iso(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def parse_date(s: str) -> date:
    if not isinstance(s, str):
        raise ValueError("not a date string")
    # strict YYYY-MM-DD
    if len(s) != 10 or s[4] != "-" or s[7] != "-":
        raise ValueError("bad date format")
    return date(int(s[0:4]), int(s[5:7]), int(s[8:10]))


def date_of_ms(ms: int) -> date:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).date()


def round_half_up_cents(value) -> int:
    """Round a Decimal/float numeric to whole cents with ROUND_HALF_UP; returns int."""
    d = Decimal(str(value)) if not isinstance(value, Decimal) else value
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def touch(resource: dict):
    """Refresh updated_at and bump version on a mutated resource."""
    resource["updated_at"] = current_clock_iso()
    resource["version"] = resource.get("version", 1) + 1


def init_system_fields(resource: dict):
    resource["id"] = new_resource_id()
    resource["created_at"] = current_clock_iso()
    resource["updated_at"] = resource["created_at"]
    resource["version"] = 1
