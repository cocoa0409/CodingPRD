"""In-memory data store, logical clock, id/timestamp management.

Storage is process-local Python dicts only.  The store starts completely empty
on every boot: nothing is seeded, preloaded or hardcoded.
"""

import itertools
import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.4: before any caller sets it, the logical clock reads exactly this
# instant and never falls back to wall-clock time.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"


def parse_iso(value):
    """Parse an ISO 8601 instant into an aware UTC datetime.  Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if not text:
        raise ValueError("empty")
    if text[-1] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_iso(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


class Store(object):
    def __init__(self):
        self.jurisdictions = {}
        self.venues = {}
        self.rides = {}
        self.workers = {}
        self.routes = {}
        self.route_stops = {}
        self.contracts = {}
        self.ride_allocations = {}
        self.permit_applications = {}
        self.inspection_orders = {}
        self.crew_assignments = {}
        self.ticket_sales = {}
        self.settlements = {}
        self.weather_closures = {}
        self.make_goods = {}
        self._seq = itertools.count(1)
        self.clock = parse_iso(DEFAULT_CLOCK_ISO)


store = Store()


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------
def now():
    return store.clock


def now_iso():
    return fmt_iso(store.clock)


def set_clock(dt):
    store.clock = dt


# --------------------------------------------------------------------------
# row lifecycle
# --------------------------------------------------------------------------
def _touched_set():
    from flask import g
    s = getattr(g, "_touched_rows", None)
    if s is None:
        s = set()
        g._touched_rows = s
    return s


def new_id():
    return str(uuid.uuid4())


def create(table, data, common=True):
    """Insert a new row.  ``common`` adds created_at/updated_at/version."""
    row = dict(data)
    row["id"] = new_id()
    row["_seq"] = next(store._seq)
    ts = now_iso()
    row["created_at"] = ts
    if common:
        row["updated_at"] = ts
        row["version"] = 1
    table[row["id"]] = row
    _touched_set().add(row["id"])
    return row


def touch(row):
    """Mutation bookkeeping: refresh updated_at, bump version once per request."""
    if row is None:
        return row
    row["updated_at"] = now_iso()
    seen = _touched_set()
    if row["id"] not in seen:
        row["version"] = int(row.get("version", 1)) + 1
        seen.add(row["id"])
    return row


# --------------------------------------------------------------------------
# ordering / query helpers
# --------------------------------------------------------------------------
def order_key(row):
    """PRD 2.3: list responses are ordered by created_at ascending."""
    return (row.get("created_at", ""), row.get("_seq", 0))


def sorted_rows(rows):
    return sorted(rows, key=order_key)


def all_of(table):
    return sorted_rows(table.values())


def where(table, **filters):
    out = []
    for row in table.values():
        ok = True
        for key, value in filters.items():
            if row.get(key) != value:
                ok = False
                break
        if ok:
            out.append(row)
    return sorted_rows(out)


def day_bucket(dt):
    """Half-open UTC day bucket [D 00:00Z, D+1 00:00Z) -> the date D."""
    return dt.astimezone(timezone.utc).date()


def add_days(dt, days):
    return dt + timedelta(days=days)
