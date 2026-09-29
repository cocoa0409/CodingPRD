"""Foundation utilities: errors, logical clock, response envelope, rounding.

Every structural name here is taken from PRD.md sections 2.1 - 2.4:
  - auth headers            : X-User-ID / X-User-Role
  - envelope                : meta{api_request_id, api_request_timestamp} /
                              response_type / data
  - error body              : data{error_id, message}
  - pagination fields       : limit / offset / total_count / has_more
  - optimistic concurrency  : version (per-row integer starting at 1)
"""

import random
import string
import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class ApiError(Exception):
    """Carries the scaffold error_id plus the HTTP status from the catalog."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


# --------------------------------------------------------------------------
# Logical clock (PRD 2.4) -- the server NEVER reads wall-clock time.
# --------------------------------------------------------------------------

CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"


# --------------------------------------------------------------------------
# Datetime helpers
# --------------------------------------------------------------------------


def parse_dt(value):
    """Parse an ISO-8601 instant into an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fmt_dt(value):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    if value is None:
        return None
    value = value.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year,
        value.month,
        value.day,
        value.hour,
        value.minute,
        value.second,
        value.microsecond // 1000,
    )


def add_days(value, days):
    return value + timedelta(days=days)


def minutes_between(start, end):
    """Whole minutes between two instants (windows are whole minutes)."""
    return int((end - start).total_seconds() // 60)


class LogicalClock(object):
    """The only source of "now" in the server; it moves only when asked."""

    def __init__(self):
        self.now = parse_dt(CLOCK_DEFAULT_ISO)
        self.raw = CLOCK_DEFAULT_ISO

    def set(self, dt, raw):
        self.now = dt
        self.raw = raw


CLOCK = LogicalClock()

# Global request lock: the store is plain Python dicts, so requests are
# serialised to keep every cascade atomic.
LOCK = threading.RLock()


def clock_now():
    return CLOCK.now


def clock_str():
    return fmt_dt(CLOCK.now)


# --------------------------------------------------------------------------
# Rounding (PRD 2.9)
# --------------------------------------------------------------------------


def dec(value):
    """Build a Decimal without binary float artifacts."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def round_half_up(value, places=0):
    """Round half away from zero to `places` decimal places."""
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(round_half_up(value, 0))


def ceil_div_int(numerator, denominator):
    """Exact integer ceiling of numerator/denominator (both ints)."""
    return -((-numerator) // denominator)


def ceil_dec(value):
    return int(dec(value).to_integral_value(rounding=ROUND_CEILING))


# --------------------------------------------------------------------------
# Identity + envelope
# --------------------------------------------------------------------------

_ALNUM = string.ascii_uppercase + string.digits


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def meta_block():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": clock_str(),
    }


def envelope_object(data):
    return {"meta": meta_block(), "response_type": "object", "data": data}


def envelope_array(rows, limit, offset, total_count):
    meta = meta_block()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    return {"meta": meta, "response_type": "array", "data": rows}


def envelope_error(error_id, message):
    return {
        "meta": meta_block(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
