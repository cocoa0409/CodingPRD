"""Shared low-level helpers: identifiers, instant rendering/parsing, decimal
charge handling and JSON serialisation.

TIMESTAMP RENDERING -- ONE RULE, NO EXCEPTIONS (PRD 2.2 / 2.4)
==============================================================
Every instant this API emits -- server-written stamp, caller-supplied instant
echoed back, or derived/computed instant -- is rendered by `iso()` as an
ISO 8601 UTC timestamp with EXACTLY three fractional-second digits and a
trailing `Z`:  YYYY-MM-DDTHH:MM:SS.sssZ

Caller-supplied instants are parsed into aware UTC `datetime` objects on the
way in and stored as `datetime`, so they leave through exactly the same
renderer as computed instants.  There is no second convention anywhere.
"""
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

TENTH = Decimal("0.1")


# ---------------------------------------------------------------------------
# identifiers
# ---------------------------------------------------------------------------
_id_counter = itertools.count(1)


def new_id():
    """Server-minted bare UUID string; no type prefix.

    Rows minted inside one cascade share a `created_at`, and list ordering
    breaks that tie on `id` ascending.  The first 48 bits are therefore a
    monotonic counter, so the declared tie-break yields creation order.  The
    value is still a syntactically valid UUID string.
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


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)


# ---------------------------------------------------------------------------
# decimals (charge weights to 0.1 lb, pressures to 0.1 psig -- PRD 2.4)
# ---------------------------------------------------------------------------
def round_tenth(value):
    """Round half up to one decimal place (0.1 lb / 0.1 psig)."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(TENTH, rounding=ROUND_HALF_UP)


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


ZERO = Decimal("0")


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
    declared scale (e.g. 8400.0 rather than 8400)."""
    text = json.dumps(payload, default=_default, ensure_ascii=True)
    return _NUM_RE.sub(lambda m: m.group(1), text)
