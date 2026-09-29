"""In-memory store, logical clock and record helpers.

The store starts completely empty on every boot: nothing is seeded, preloaded
or hardcoded.  Every entity is created through the declared API surface.
"""

import itertools
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

# ---------------------------------------------------------------- tables -----

ROOMS = {}
LOTS = {}
BILLETS = {}
SPECS = {}
COMPONENTS = {}
STATIONS = {}
RESERVATIONS = {}
CATALOG = {}
ORDERS = {}
SELECTIONS = {}
RUNS = {}
INSPECTIONS = {}
SHOPS = {}
WARRANTIES = {}
SHIPMENTS = {}

_seq = itertools.count(1)

# ----------------------------------------------------------- logical clock ---

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": DEFAULT_CLOCK}


def now_utc():
    """The current logical clock instant (governs every domain time rule)."""
    return _clock["now"]


def set_now(dt):
    _clock["now"] = dt


# ----------------------------------------------------------- time helpers ----

_TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T](\d{2}):(\d{2}):(\d{2})(\.\d+)?Z$"
)


def parse_ts(value):
    """RFC 3339 with a trailing Z.  Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    m = _TS_RE.match(value)
    if not m:
        return None
    try:
        return datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4)), int(m.group(5)), int(m.group(6)),
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None


def fmt_ts(dt):
    """Domain instants are rendered to whole seconds with a trailing Z."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def audit_stamp():
    """Audit columns: ISO 8601 UTC with exactly three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def add_months(dt, months):
    """Calendar-month arithmetic clamped to the last valid day of the month."""
    total = dt.month - 1 + months
    year = dt.year + total // 12
    month = total % 12 + 1
    day = dt.day
    while True:
        try:
            return datetime(year, month, day, 0, 0, 0, tzinfo=timezone.utc)
        except ValueError:
            day -= 1


def add_days(dt, days):
    return dt + timedelta(days=days)


def whole_days_between(a, b):
    """Whole days from the date part of a to the date part of b."""
    return (b.date() - a.date()).days


# --------------------------------------------------------- record helpers ----

def new_record(table, fields, versioned=True):
    rid = str(uuid.uuid4())
    stamp = audit_stamp()
    rec = {"id": rid, "created_at": stamp}
    if versioned:
        rec["updated_at"] = stamp
        rec["version"] = 1
    rec.update(fields)
    rec["_seq"] = next(_seq)
    table[rid] = rec
    return rec


def touch(rec):
    """Any mutated row -- named by the caller or reached by a cascade -- moves
    its updated_at and version."""
    if rec is None:
        return rec
    if "version" in rec:
        rec["version"] = rec["version"] + 1
        rec["updated_at"] = audit_stamp()
    return rec


def sort_key_created(rec):
    return (rec["created_at"], rec["_seq"])


def by_created(rows):
    return sorted(rows, key=sort_key_created)


# ------------------------------------------------------------ serialisation --

def _conv(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return fmt_ts(value)
    if isinstance(value, list):
        return [_conv(v) for v in value]
    return value


def public(rec, extra=None):
    out = {}
    for key, value in rec.items():
        if key.startswith("_"):
            continue
        out[key] = _conv(value)
    if extra:
        for key, value in extra.items():
            out[key] = _conv(value)
    return out
