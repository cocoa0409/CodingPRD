"""In-memory data store, logical UTC clock, id / timestamp / version helpers.

The store starts EMPTY on every boot: no entity is ever seeded, preloaded or
hardcoded here. Tests build every row through the declared endpoints.
"""

import threading
import uuid
from datetime import datetime, timedelta, timezone

# --- the thirteen entity families ----------------------------------------
ordinances = {}
ami_schedules = {}
projects = {}
units = {}
marketing_plans = {}
lottery_events = {}
households = {}
certifications = {}
agreements = {}
monitoring_reviews = {}
resale_transactions = {}
in_lieu_fees = {}
disbursements = {}

LOCK = threading.RLock()

# --- logical UTC clock ----------------------------------------------------
# PRD 2.5: the clock starts at exactly 2026-08-01T00:00:00Z on every boot and is
# NEVER read from the host wall clock.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": CLOCK_DEFAULT}

_seq = {"n": 0}


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def logical_now():
    return _clock["now"]


def set_logical_now(dt):
    _clock["now"] = dt


# --- timestamp formatting -------------------------------------------------
def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional-second digits and a Z suffix."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_dt(value):
    """Tolerant ISO 8601 parser -> aware UTC datetime, or None when unparseable."""
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        for pattern in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(value.strip(), pattern)
                break
            except ValueError:
                dt = None
        if dt is None:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Strict YYYY-MM-DD calendar date -> date, or None."""
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if len(raw) != 10:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_date_loose(value):
    """Accept a calendar date or a full timestamp and return the calendar date."""
    d = parse_date(value)
    if d is not None:
        return d
    dt = parse_dt(value)
    if dt is not None:
        return dt.date()
    return None


def fmt_date(d):
    if d is None:
        return None
    return d.isoformat()


def add_days_date(date_str, days):
    d = parse_date_loose(date_str)
    if d is None:
        return None
    return (d + timedelta(days=days)).isoformat()


def wall_now():
    return datetime.now(timezone.utc)


# --- row lifecycle --------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def insert(store, row):
    stamp = fmt_dt(wall_now())
    row["id"] = new_id()
    row["created_at"] = stamp
    row["updated_at"] = stamp
    row["version"] = 1
    row["_seq"] = next_seq()
    store[row["id"]] = row
    return row


def touch(row):
    """Record one mutation of this row: bump version by exactly one."""
    row["updated_at"] = fmt_dt(wall_now())
    row["version"] = int(row.get("version", 0)) + 1
    return row


def public(row):
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


def sort_key(row):
    """Default collection ordering: created_at ascending, insertion order as the
    stable tie-break for rows written inside the same millisecond."""
    return (row.get("created_at") or "", row.get("_seq") or 0)


def all_rows(store):
    return sorted(store.values(), key=sort_key)


def reset():
    """Only used by tests of this module; never called at import time."""
    for store in (ordinances, ami_schedules, projects, units, marketing_plans,
                  lottery_events, households, certifications, agreements,
                  monitoring_reviews, resale_transactions, in_lieu_fees,
                  disbursements):
        store.clear()
    _clock["now"] = CLOCK_DEFAULT
    _seq["n"] = 0
