"""In-memory data store, logical clock and shared primitives.

The store starts completely empty on every boot: no entity is seeded, preloaded
or hardcoded.  Every record is created through the declared API surface.
"""

import itertools
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

UTC = timezone.utc

# PRD §2.4 - the logical clock reads exactly this before any call and never
# falls back to wall-clock time.
LOGICAL_CLOCK_INITIAL = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

_lock = threading.RLock()


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        # one dict per entity collection (flat topology, §1.0)
        self.briefs = {}
        self.materials = {}
        self.records = {}
        self.formulas = {}
        self.components = {}
        self.lots = {}
        self.cabinets = {}
        self.retentions = {}
        self.rigs = {}
        self.tests = {}
        self.shipments = {}
        self.documents = {}
        self.batches = {}
        self.forecasts = {}
        self.grants = {}
        self.clock = LOGICAL_CLOCK_INITIAL
        self._ord = itertools.count(1)
        self._last_stamp = None


db = Store()


def now_logical():
    return db.clock


def set_logical(dt):
    db.clock = dt


def new_id():
    return str(uuid.uuid4())


def stamp():
    """Strictly monotonic wall-clock stamp truncated to millisecond precision.

    created_at / updated_at are rendered with exactly three fractional digits
    (§2.4).  Making the sequence strictly increasing keeps `created_at ASC`
    ordering identical to insertion order, which every sequence_no /
    iteration_no derivation relies on.
    """
    with _lock:
        t = datetime.now(UTC)
        t = t.replace(microsecond=(t.microsecond // 1000) * 1000)
        if db._last_stamp is not None and t <= db._last_stamp:
            t = db._last_stamp + timedelta(milliseconds=1)
        db._last_stamp = t
        return t


def iso(dt):
    if dt is None:
        return None
    d = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        d.year, d.month, d.day, d.hour, d.minute, d.second, d.microsecond // 1000)


_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,9}))?"
    r"\s*(Z|z|[+-]\d{2}:?\d{2})?$")


def parse_dt(value):
    """Lenient ISO-8601 parser.  Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    m = _DT_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute, second, frac, tz = m.groups()
    try:
        micro = 0
        if frac:
            micro = int((frac + "000000")[:6])
        base = datetime(int(year), int(month), int(day), int(hour), int(minute),
                        int(second or 0), micro, tzinfo=UTC)
    except ValueError:
        return None
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        body = tz[1:].replace(":", "")
        offs = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        base = base - sign * offs
    return base


def base_entity():
    ts = stamp()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_ord": next(db._ord),
    }


def touch(entity):
    """A real mutation: refresh updated_at and increment version (§2.4, §2.10)."""
    entity["updated_at"] = stamp()
    entity["version"] = entity["version"] + 1


def by_creation(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_ord"]))


def rhu(value, places=0):
    """Round half up (never banker's rounding), applied exactly once."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def num(value):
    """Render a Decimal for JSON as a plain number."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    return float(value)
