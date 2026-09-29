"""Pure helpers: identifiers, ISO-8601 rendering/parsing and the integer
rounding disciplines pinned by PRD section 2.6.

Money is *never* a float anywhere in this service.  Every monetary quantity is
an integer count of cents and every rate is an integer count of basis points,
so both rounding disciplines are implemented with exact integer arithmetic.
"""

import random
import string
import uuid
from datetime import datetime, timezone

# The logical clock starts here on every process start (PRD section 1).
CLOCK_EPOCH_ISO = "2026-08-01T00:00:00.000Z"

_ALNUM = string.ascii_uppercase + string.digits


def new_uuid():
    """A UUID string with no type prefix (PRD section 2.4)."""
    return str(uuid.uuid4())


def new_request_id():
    """Server-generated request id; starts with ``req_`` (PRD section 2.2)."""
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def parse_iso(value):
    """Parse an ISO-8601 instant into a tz-aware UTC datetime.

    Returns ``None`` when the value is not a parseable ISO-8601 instant.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_iso(moment):
    """Render a datetime as an ISO-8601 UTC instant with exactly three
    fractional-second digits (PRD section 2.4)."""
    if moment is None:
        return None
    moment = moment.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        moment.year,
        moment.month,
        moment.day,
        moment.hour,
        moment.minute,
        moment.second,
        moment.microsecond // 1000,
    )


def wall_now_iso():
    """Wall-clock ISO-8601 UTC stamp for the response envelope metadata."""
    return format_iso(datetime.now(timezone.utc))


def round_half_up(numerator, denominator):
    """Exact-rational round half up: floor(n/d + 1/2).

    A value exactly halfway between two cents goes to the larger cent, as
    PRD section 2.6 requires.  ``denominator`` must be positive.
    """
    return (2 * numerator + denominator) // (2 * denominator)


def floor_div(numerator, denominator):
    """Truncation of a non-negative exact rational toward zero (PRD 2.6)."""
    return numerator // denominator
