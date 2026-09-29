"""Shared helpers: ids, timestamps, half-up rounding, response envelope."""
import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

UTC = timezone.utc

# --------------------------------------------------------------------------
# identity
# --------------------------------------------------------------------------


def new_id():
    """Server-minted id: a UUID string with no type prefix (PRD 2.4)."""
    return str(uuid.uuid4())


_RID_ALPHABET = string.ascii_uppercase + string.digits


def new_request_id():
    """api_request_id starts with req_ (PRD 2.2)."""
    return "req_" + "".join(random.choice(_RID_ALPHABET) for _ in range(20))


# --------------------------------------------------------------------------
# timestamps -- ISO 8601 UTC with exactly three fractional digits (PRD 2.4)
# --------------------------------------------------------------------------

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def wall_now():
    return datetime.now(UTC)


def wall_now_iso():
    return fmt_dt(wall_now())


def parse_dt(value):
    """Parse an ISO 8601 instant. Returns an aware UTC datetime or raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    m = _ISO_RE.match(value.strip())
    if not m:
        raise ValueError("not an ISO 8601 instant: %r" % (value,))
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    tz = m.group(8)
    if tz in (None, "Z", "z"):
        offset = timedelta(0)
    else:
        sign = 1 if tz[0] == "+" else -1
        body = tz[1:].replace(":", "")
        offset = sign * timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
    naive = datetime(year, month, day, hour, minute, second, micro)
    return (naive - offset).replace(tzinfo=UTC)


def is_dt(value):
    try:
        parse_dt(value)
        return True
    except ValueError:
        return False


# --------------------------------------------------------------------------
# arithmetic -- every rounding in this system is half-up (PRD 2.5)
# --------------------------------------------------------------------------


def rhu(value, places):
    """Round half-up to `places` decimals, returned as a float."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        dec = value
    else:
        dec = Decimal(repr(float(value)))
    quantum = Decimal(1).scaleb(-places)
    return float(dec.quantize(quantum, rounding=ROUND_HALF_UP))


def num(value):
    """Normalise a numeric to int when it is integral, else float."""
    if value is None:
        return None
    f = float(value)
    if f.is_integer() and abs(f) < 1e15:
        return f
    return f


def whole_minutes(start, end):
    return int((end - start).total_seconds() // 60)


# --------------------------------------------------------------------------
# public projection of a stored row (internal keys are underscore-prefixed)
# --------------------------------------------------------------------------


def pub(row):
    if row is None:
        return None
    out = {}
    for key, value in row.items():
        if key.startswith("_"):
            continue
        if isinstance(value, list):
            out[key] = [dict(v) if isinstance(v, dict) else v for v in value]
        else:
            out[key] = value
    return out
