"""Shared low-level helpers: ids, ISO-8601 time handling, round-half-up money."""

import math
import random
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

UTC = timezone.utc

# The logical clock's boot value, per PRD 2.4.
LOGICAL_CLOCK_EPOCH_ZERO = "2026-08-01T00:00:00Z"


def new_id():
    """Server-minted UUID with no type prefix (PRD 2.5)."""
    return str(uuid.uuid4())


def new_seed():
    """Barcode seed. Deliberately hyphen-free: the presented barcode is split at
    its LAST hyphen, so a hyphen inside the seed would still round-trip, but a
    hyphen-free seed keeps the split unambiguous."""
    return uuid.uuid4().hex


def api_request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def now_utc():
    return datetime.now(UTC)


def iso3(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.5)."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000
    )


def now_iso3():
    return iso3(now_utc())


def iso_clock(dt):
    """Render a logical-clock instant.

    PRD 2.4 pins the clock's own reading: before any client has moved it, it
    "reads exactly `2026-08-01T00:00:00Z`", i.e. the clock carries whatever
    precision it was set to rather than the three-fractional-digit shape that
    PRD 2.5 mandates for `created_at`/`updated_at`. Server-side instants that
    "take the logical clock's value at the moment of the write" therefore render
    at second precision, only growing a fractional part when the client moved
    the clock to a sub-second instant.
    """
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    stem = "%04d-%02d-%02dT%02d:%02d:%02d" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second
    )
    if dt.microsecond:
        return stem + ".%03dZ" % (dt.microsecond // 1000)
    return stem + "Z"


def parse_dt(value):
    """Parse an ISO-8601 instant; returns None when unparseable."""
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
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def whole_seconds(dt):
    """Instants are compared at whole-second resolution (PRD 2.11)."""
    return int(math.floor(dt.timestamp()))


def dec(value):
    return Decimal(str(value))


def round_half_up(value, places=0):
    quantum = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)


def rhu_cents(value):
    """Round half up to a whole cent, returned as int."""
    return int(round_half_up(value, 0))
