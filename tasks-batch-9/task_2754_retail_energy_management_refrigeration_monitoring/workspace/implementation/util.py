"""Numeric, temporal and JSON helpers.

All arithmetic is exact decimal arithmetic and every rounding step rounds
half up (PRD section 2.8).  Every timestamp reads the logical clock, never
wall time (PRD section 2.5).
"""

import json
import random
import re
import string
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, getcontext

getcontext().prec = 60

D0 = Decimal(0)


def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def rhu(value, places):
    """Round half up to `places` decimal places."""
    quant = Decimal(1).scaleb(-places)
    return D(value).quantize(quant, rounding=ROUND_HALF_UP)


def q(value, places):
    """Materialise an already-correct value at the given scale."""
    if value is None:
        return None
    return rhu(value, places)


ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T](\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?Z$"
)


def parse_iso(text):
    """Parse an ISO-8601 UTC instant with a literal Z offset.

    Returns None when the value is not a well-formed instant.
    """
    if not isinstance(text, str):
        return None
    m = ISO_RE.match(text)
    if not m:
        return None
    frac = m.group(7) or ""
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    try:
        return datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4)), int(m.group(5)), int(m.group(6)),
            micro, tzinfo=timezone.utc,
        )
    except ValueError:
        return None


def fmt_iso(dt):
    """Render an instant as ISO-8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def elapsed_seconds(start, end):
    return Decimal((end - start).total_seconds()).quantize(Decimal("0.000001"))


def whole_minutes(start, end):
    """Whole minutes between two instants, remainder discarded."""
    secs = int((end - start).total_seconds())
    if secs < 0:
        return 0
    return secs // 60


def exact_hours(start, end):
    """Exact elapsed hours between two instants as a Decimal."""
    secs = D((end - start).total_seconds())
    return secs / Decimal(3600)


def month_bounds(dt):
    """[start, end) of the UTC calendar month containing dt."""
    start = datetime(dt.year, dt.month, 1, tzinfo=timezone.utc)
    if dt.month == 12:
        end = datetime(dt.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(dt.year, dt.month + 1, 1, tzinfo=timezone.utc)
    return start, end


_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


# --------------------------------------------------------------------------
# JSON emission.  Decimals are emitted as exact literals so that a value
# materialised at two decimal places is rendered with two decimal places.
# --------------------------------------------------------------------------

def _emit(value, out):
    if value is None:
        out.append("null")
    elif value is True:
        out.append("true")
    elif value is False:
        out.append("false")
    elif isinstance(value, Decimal):
        out.append(str(value))
    elif isinstance(value, int):
        out.append(str(value))
    elif isinstance(value, float):
        out.append(repr(value))
    elif isinstance(value, str):
        out.append(json.dumps(value))
    elif isinstance(value, dict):
        out.append("{")
        first = True
        for key, sub in value.items():
            if not first:
                out.append(",")
            first = False
            out.append(json.dumps(str(key)))
            out.append(":")
            _emit(sub, out)
        out.append("}")
    elif isinstance(value, (list, tuple)):
        out.append("[")
        first = True
        for sub in value:
            if not first:
                out.append(",")
            first = False
            _emit(sub, out)
        out.append("]")
    elif isinstance(value, datetime):
        out.append(json.dumps(fmt_iso(value)))
    else:
        out.append(json.dumps(str(value)))


def json_text(value):
    out = []
    _emit(value, out)
    return "".join(out)
