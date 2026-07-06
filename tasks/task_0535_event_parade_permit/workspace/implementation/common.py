"""Shared helpers: response envelope, errors, clock, ids, timestamps, money."""
import uuid
import random
import string
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP


# ---------------------------------------------------------------------------
# Logical clock (EventClock singleton)
# ---------------------------------------------------------------------------
CLOCK_DEFAULT = "2026-05-01T00:00:00Z"


class Clock:
    def __init__(self):
        self.current_utc = _parse_iso(CLOCK_DEFAULT)

    def now(self):
        return self.current_utc

    def now_iso(self):
        return to_iso(self.current_utc)


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------
def _parse_iso(value):
    """Parse an ISO 8601 UTC string into a timezone-aware datetime."""
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso(value):
    return _parse_iso(value)


def to_iso(dt):
    """Serialize a datetime to ISO 8601 UTC with three fractional digits and Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


CLOCK = Clock()


# ---------------------------------------------------------------------------
# IDs
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------
def money(value):
    """Round a numeric to 2 decimals, ROUND_HALF_UP, return a float."""
    d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(d)


def D(value):
    return Decimal(str(value))


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _meta(extra=None):
    m = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": to_iso(datetime.now(timezone.utc)),
    }
    if extra:
        m.update(extra)
    return m


def success(data, response_type="object", pagination=None):
    return {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
