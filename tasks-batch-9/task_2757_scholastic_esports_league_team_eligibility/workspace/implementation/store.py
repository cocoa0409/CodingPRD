"""In-memory store, the logical league clock, and record helpers.

Storage is process-local Python dicts only.  The store starts EMPTY on every
boot: nothing is seeded, preloaded or hardcoded.  Every entity the API exposes
is created by a caller through a declared endpoint.
"""

import datetime as _dt
import re
import uuid
from decimal import Decimal, ROUND_HALF_UP

from flask import g

from errors import ApiError, NOT_FOUND_FOR

UTC = _dt.timezone.utc

# PRD 2.4 -- the logical clock's value at server startup.
CLOCK_EPOCH = _dt.datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=UTC)

KINDS = (
    "district",
    "school",
    "coach",
    "student",
    "title",
    "title_approval",
    "season",
    "team",
    "roster_slot",
    "match",
    "fair_play_case",
)


class Store(object):
    def __init__(self):
        self.tables = {}
        self.clock = CLOCK_EPOCH
        self.reset()

    def reset(self):
        for kind in KINDS:
            self.tables[kind] = {}
        self.clock = CLOCK_EPOCH

    # ---- clock -----------------------------------------------------------
    @property
    def now(self):
        return self.clock

    def set_clock(self, value):
        self.clock = value

    # ---- table access ----------------------------------------------------
    def table(self, kind):
        return self.tables[kind]

    def get(self, kind, rec_id):
        if not isinstance(rec_id, str):
            return None
        return self.tables[kind].get(rec_id)

    def all(self, kind):
        return list(self.tables[kind].values())

    def put(self, kind, rec):
        self.tables[kind][rec["id"]] = rec
        return rec


db = Store()


# ---------------------------------------------------------------------------
# datetime / date helpers
# ---------------------------------------------------------------------------
_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.(\d+))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_datetime(value):
    """Parse an ISO 8601 instant into an aware UTC datetime truncated to ms.

    Returns None when the value is not a parseable ISO 8601 datetime string.
    """
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute, second = (int(m.group(i)) for i in range(1, 7))
    frac = m.group(8) or ""
    micro = 0
    if frac:
        frac = (frac + "000000")[:6]
        micro = int(frac)
    tz = m.group(9)
    try:
        naive = _dt.datetime(year, month, day, hour, minute, second, micro)
    except ValueError:
        return None
    if tz in (None, "Z", "z"):
        aware = naive.replace(tzinfo=UTC)
    else:
        sign = 1 if tz[0] == "+" else -1
        body = tz[1:].replace(":", "")
        offset = _dt.timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        aware = naive.replace(tzinfo=_dt.timezone(sign * offset))
        aware = aware.astimezone(UTC)
    # normalise to exactly three fractional digits (millisecond resolution)
    aware = aware.replace(microsecond=(aware.microsecond // 1000) * 1000)
    return aware


def parse_date(value):
    """Parse a YYYY-MM-DD pure date; returns None when unparseable."""
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def iso(value):
    """Serialize an aware datetime as YYYY-MM-DDTHH:MM:SS.mmmZ."""
    if value is None:
        return None
    v = value.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        v.year, v.month, v.day, v.hour, v.minute, v.second, v.microsecond // 1000,
    )


def iso_date(value):
    if value is None:
        return None
    return "%04d-%02d-%02d" % (value.year, value.month, value.day)


def clock_date():
    return db.now.date()


def completed_years(start_date, end_date):
    """Whole years completed between two pure dates."""
    years = end_date.year - start_date.year
    if (end_date.month, end_date.day) < (start_date.month, start_date.day):
        years -= 1
    return years


# ---------------------------------------------------------------------------
# numeric helpers
# ---------------------------------------------------------------------------
def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    return Decimal(str(value))


def rhu(value, places):
    """round half up to `places` decimal places, returning a Decimal."""
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def out_num(value, places):
    """Serialize a numeric field at a fixed decimal width."""
    if value is None:
        return None
    return float(rhu(value, places))


# ---------------------------------------------------------------------------
# record lifecycle
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def _touched():
    if not hasattr(g, "_touched_records"):
        g._touched_records = set()
    return g._touched_records


def new_record(kind, **fields):
    now = db.now
    rec = {"_kind": kind, "id": new_id(), "created_at": now, "updated_at": now, "version": 1}
    rec.update(fields)
    db.put(kind, rec)
    # A freshly created record already carries version 1; it must not also be
    # bumped by a roll-up recomputation performed later in the same request.
    _touched().add(rec["id"])
    return rec


def touch(rec):
    """Mark a record mutated: refresh updated_at, bump version once per request."""
    if rec is None:
        return rec
    rec["updated_at"] = db.now
    seen = _touched()
    if rec["id"] not in seen:
        rec["version"] = rec["version"] + 1
        seen.add(rec["id"])
    return rec


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------
def find(kind, rec_id):
    return db.get(kind, rec_id)


def must_find(kind, rec_id):
    rec = db.get(kind, rec_id)
    if rec is None:
        raise ApiError(NOT_FOUND_FOR[kind])
    return rec


def sorted_records(records):
    """PRD 2.3 -- list results are sorted by created_at ascending (stable)."""
    return sorted(records, key=lambda r: r["created_at"])
