"""Utility helpers: ids, timestamps, integer arithmetic, datetime parsing."""

import random
import string
import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def now_iso():
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def ceil_div(a, b):
    """Ceiling division for non-negative a and positive b."""
    return (a + b - 1) // b


def round_half_up_div(num, den):
    """round_half_up(num/den) = floor(x + 1/2) = (2*num + den) // (2*den)."""
    return (2 * num + den) // (2 * den)


def parse_dt(value):
    """Parse an ISO 8601 datetime string into an aware datetime (UTC assumed if naive)."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def touch(rec):
    """Every mutation refreshes updated_at and increments version (PRD §2.5, §2.10)."""
    rec["updated_at"] = now_iso()
    rec["version"] += 1
