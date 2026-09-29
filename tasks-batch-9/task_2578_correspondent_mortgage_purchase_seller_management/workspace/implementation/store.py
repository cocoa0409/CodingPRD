"""In-memory data store, logical clock and record helpers.

The store starts EMPTY on every boot -- nothing is seeded here.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from flask import g

# PRD 2.4: at startup the logical clock reads exactly 2026-08-01T00:00:00Z and
# must never fall back to real wall-clock time.
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "sellers",
    "statements",
    "qc_reviews",
    "products",
    "adjustments",
    "commitments",
    "loans",
    "defects",
    "conditions",
    "advices",
    "demands",
    "transfers",
    "scorecards",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = CLOCK_EPOCH
        self._seq = 0
        for name in COLLECTIONS:
            setattr(self, name, {})

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


# --------------------------------------------------------------------------
# clock helpers
# --------------------------------------------------------------------------

def now():
    return db.clock


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_instant(raw):
    """Parse an ISO-8601 instant. Returns None when unparseable."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(raw):
    """Parse a strict YYYY-MM-DD calendar date. Returns a date or None."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if len(text) != 10 or text[4] != "-" or text[7] != "-":
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def date_start(d):
    """Midnight UTC on the given calendar date (accepts a date or a string)."""
    if isinstance(d, str):
        d = parse_date(d)
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def date_end(d):
    """23:59:59.999 UTC on the given calendar date."""
    if isinstance(d, str):
        d = parse_date(d)
    return datetime(d.year, d.month, d.day, 23, 59, 59, 999000, tzinfo=timezone.utc)


def plus_days(dt, days):
    return dt + timedelta(days=days)


def whole_days_between(start_date, end_date):
    if isinstance(start_date, str):
        start_date = parse_date(start_date)
    if isinstance(end_date, str):
        end_date = parse_date(end_date)
    return (end_date - start_date).days


def month_start(dt):
    return datetime(dt.year, dt.month, 1, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# record helpers
# --------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def base_record():
    stamp = fmt_dt(now())
    return {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": db.next_seq(),
        "_created_dt": now(),
    }


def _touched():
    if not hasattr(g, "_touched_ids"):
        g._touched_ids = set()
    return g._touched_ids


def touch(record):
    """Refresh updated_at and bump version at most once per request/resource.

    PRD 2.4: every mutation of a resource -- including a server-initiated
    cascade or a roll-up recomputation -- refreshes updated_at and increments
    version by exactly 1.
    """
    if record is None:
        return record
    record["updated_at"] = fmt_dt(now())
    seen = _touched()
    key = id(record)
    if key not in seen:
        seen.add(key)
        record["version"] = record.get("version", 1) + 1
    return record


def by_created(records):
    """Ascending created_at order with a stable insertion tiebreak."""
    return sorted(records, key=lambda r: r["_seq"])


def public(record):
    """Serialize a record: drop internal keys, coerce Decimals to numbers."""
    if record is None:
        return None
    out = {}
    for key, value in record.items():
        if key.startswith("_"):
            continue
        if isinstance(value, Decimal):
            out[key] = float(value)
        elif isinstance(value, list):
            out[key] = list(value)
        else:
            out[key] = value
    return out


def public_list(records):
    return [public(r) for r in records]
