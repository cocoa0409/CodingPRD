"""Low level helpers: ids, logical/wall clock formatting, decimal arithmetic."""

import random
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

_ALNUM = string.ascii_uppercase + string.digits


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def now_utc():
    return datetime.now(timezone.utc)


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_iso(value):
    """Parse an ISO 8601 instant. Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text[-1] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def D(value):
    """Exact Decimal from an int/float/str/Decimal."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places):
    """Round half up to `places` decimals."""
    quant = Decimal(1).scaleb(-places)
    return D(value).quantize(quant, rounding=ROUND_HALF_UP)


def whole_minutes(start, end):
    """Elapsed whole minutes between two instants, truncated toward zero."""
    secs = int((end - start).total_seconds())
    if secs >= 0:
        return secs // 60
    return -((-secs) // 60)


ZERO3 = Decimal("0.000")
ZERO2 = Decimal("0.00")
ZERO4 = Decimal("0.0000")
