"""Shared helpers: time formatting/parsing, id generation, rounding."""
import re
import uuid
import random
import string
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    alphanum = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(alphanum, k=20))


def iso(dt: datetime) -> str:
    """ISO 8601 UTC with exactly three fractional digits and Z suffix."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


_ISO_RE = re.compile(r"Z$")


def parse_iso(s):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Returns None on failure. Accepts trailing 'Z' or explicit offsets.
    """
    if not isinstance(s, str) or not s:
        return None
    txt = s.strip()
    # normalize trailing Z to +00:00 for fromisoformat
    if txt.endswith("Z") or txt.endswith("z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def round_half_up(value) -> int:
    """Round a numeric value to the nearest integer using round-half-up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
