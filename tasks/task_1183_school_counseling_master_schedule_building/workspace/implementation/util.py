"""Shared utilities: ids, timestamps (monotonic), logical clock, decimals."""

import itertools
import random
import string
import threading
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

_lock = threading.Lock()
_last_ts = None
_seq = itertools.count(1)

CLOCK_DEFAULT = "2026-05-01T00:00:00Z"


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def next_seq():
    return next(_seq)


def _format_dt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    """Wall-clock UTC ISO8601 with 3 fractional digits, monotonically increasing."""
    global _last_ts
    with _lock:
        dt = datetime.now(timezone.utc)
        if _last_ts is not None and dt <= _last_ts:
            dt = _last_ts + timedelta(milliseconds=1)
        _last_ts = dt
        return _format_dt(dt)


def parse_iso(value):
    """Parse an ISO8601 string ('Z' or offset) into an aware UTC datetime.

    Raises ValueError on malformed input.
    """
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_d(value):
    """Coerce an int/float/str/Decimal to Decimal (string path for floats)."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ValueError("bool is not numeric")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        return Decimal(value)
    raise ValueError("not numeric")


def q2(value):
    """Round half-up to 2 decimal places."""
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def q4(value):
    """Round half-up to 4 decimal places."""
    return Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def num(value):
    """Serialize a Decimal as a JSON number (float)."""
    if isinstance(value, Decimal):
        return float(value)
    return value
