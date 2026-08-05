"""Shared low-level helpers: instant rendering/parsing, calendar arithmetic,
decimal money handling and JSON serialisation.

TIMESTAMP RENDERING -- ONE RULE, NO EXCEPTIONS (PRD 2.5)
=======================================================
Every instant this API emits -- server-written stamp, caller-supplied instant
echoed back, or derived/computed instant -- is rendered by `iso()` as an
ISO 8601 UTC timestamp with EXACTLY three fractional-second digits and a
trailing `Z`:  YYYY-MM-DDTHH:MM:SS.sssZ

Caller-supplied instants are parsed into aware UTC `datetime` objects on the
way in and stored as `datetime`, so they leave through exactly the same
renderer as computed instants.  There is no second convention anywhere.

`date_of_birth` is deliberately NOT an instant: it is a plain YYYY-MM-DD string
stored and echoed verbatim.
"""
import calendar
import itertools
import json
import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

UTC = timezone.utc

_NUM_OPEN = "\u0001NUM:"
_NUM_CLOSE = "\u0001"
_NUM_RE = re.compile(r'"\\u0001NUM:(-?[0-9]+(?:\.[0-9]+)?)\\u0001"')

TWOPLACES = Decimal("0.01")


# ---------------------------------------------------------------------------
# identifiers
# ---------------------------------------------------------------------------
_id_counter = itertools.count(1)


def new_id():
    """Server-minted bare UUID string; no type prefix.

    Rows minted inside one cascade share a `created_at`, and PRD 2.3 breaks
    that tie on `id` ascending.  The first 48 bits are therefore a monotonic
    counter, so the declared tie-break yields creation order.  The value is
    still a syntactically valid v4 UUID string -- the version and variant
    nibbles are left exactly as uuid4 produced them.
    """
    base = uuid.uuid4().hex
    prefix = "%012x" % (next(_id_counter) & 0xFFFFFFFFFFFF)
    digits = prefix + base[12:]
    return "%s-%s-%s-%s-%s" % (
        digits[0:8],
        digits[8:12],
        digits[12:16],
        digits[16:20],
        digits[20:32],
    )


_ALNUM = string.ascii_uppercase + string.digits


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


# ---------------------------------------------------------------------------
# instants
# ---------------------------------------------------------------------------
def iso(dt):
    """THE single instant renderer.  None -> None."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    else:
        dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_instant(value):
    """Parse a caller-supplied instant. Returns aware UTC datetime or None when
    the value is not a well-formed instant."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hh, mm = (int(m.group(i)) for i in range(1, 6))
    ss = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    off = m.group(8)
    try:
        dt = datetime(year, month, day, hh, mm, ss, micro, tzinfo=UTC)
    except ValueError:
        return None
    if off and off not in ("Z", "z"):
        sign = 1 if off[0] == "+" else -1
        off = off[1:].replace(":", "")
        delta = timedelta(hours=int(off[:2]), minutes=int(off[2:4]))
        dt = dt - sign * delta
    return dt


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def is_calendar_date(value):
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return False
    y, m, d = (int(p) for p in value.split("-"))
    try:
        datetime(y, m, d)
    except ValueError:
        return False
    return True


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_hours(dt, hours):
    return dt + timedelta(hours=hours)


def add_months(dt, months):
    """Calendar-month arithmetic: keep the day-of-month, clamp to the last day
    of the target month when the target month is shorter."""
    total = dt.month - 1 + months
    year = dt.year + total // 12
    month = total % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


# ---------------------------------------------------------------------------
# money / decimals
# ---------------------------------------------------------------------------
def q2(value):
    """Round half up to two decimal places."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def to_decimal(value):
    """Convert a JSON-decoded number to Decimal without float artefacts.
    Returns None when the value is not numeric."""
    if isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    return None


ZERO = Decimal("0.00")


# ---------------------------------------------------------------------------
# JSON serialisation
# ---------------------------------------------------------------------------
def _default(obj):
    if isinstance(obj, Decimal):
        return _NUM_OPEN + format(obj, "f") + _NUM_CLOSE
    if isinstance(obj, datetime):
        return iso(obj)
    raise TypeError("not serialisable: %r" % (obj,))


def dumps(payload):
    """Serialise, rendering Decimal values as bare JSON numbers that keep their
    declared scale (e.g. 1800.00 rather than 1800.0)."""
    text = json.dumps(payload, default=_default, ensure_ascii=True)
    return _NUM_RE.sub(lambda m: m.group(1), text)
