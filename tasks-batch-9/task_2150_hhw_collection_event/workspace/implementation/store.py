"""In-memory data store (PRD §2.4, §2.9).

Every collection is a plain dict keyed by the server-minted UUID.  The store is
created empty on every process boot and nothing is ever seeded or persisted.
"""

import threading
import uuid
from datetime import datetime, timezone

from flask import g

LOCK = threading.RLock()

# The logical clock (PRD §2.9): before any client moves it, it reads exactly
# 2026-08-01T00:00:00Z and it never falls back to real wall-clock time.
INITIAL_CLOCK_RAW = "2026-08-01T00:00:00Z"
INITIAL_CLOCK_DT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.programs = {}
        self.sites = {}
        self.material_categories = {}
        self.residents = {}
        self.events = {}
        self.staffers = {}
        self.lane_assignments = {}
        self.appointments = {}
        self.dropoff_lines = {}
        self.containers = {}
        self.manifests = {}
        self.clock_raw = INITIAL_CLOCK_RAW
        self.clock_dt = INITIAL_CLOCK_DT
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


def now_wall():
    return datetime.now(timezone.utc)


def iso3(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso3():
    return iso3(now_wall())


def clock_raw():
    """The logical clock rendered exactly as the client last set it."""
    return store.clock_raw


def clock_dt():
    return store.clock_dt


def new_id():
    return str(uuid.uuid4())


def new_row(extra=None):
    ts = now_iso3()
    row = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }
    if extra:
        row.update(extra)
    return row


def _bumped():
    try:
        s = g._bumped_rows
    except Exception:
        return None
    return s


def touch(row):
    """Bump version + updated_at, at most once per request for a given row."""
    seen = _bumped()
    key = row.get("id")
    if seen is not None and key in seen:
        return
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = now_iso3()
    if seen is not None:
        seen.add(key)


def apply_if_changed(row, **fields):
    """Write the fields only if at least one genuinely differs, then bump.

    PRD §2.4: rows a cascade merely reads are untouched; every row a cascade
    genuinely mutates has its version incremented and updated_at refreshed.
    """
    changed = False
    for k, v in fields.items():
        if row.get(k) != v:
            changed = True
            break
    if not changed:
        return False
    row.update(fields)
    touch(row)
    return True


def set_and_touch(row, **fields):
    row.update(fields)
    touch(row)


def order_key(row):
    return (row.get("created_at") or "", row.get("_seq") or 0)


def ordered(rows):
    return sorted(rows, key=order_key)


def all_rows(coll):
    return ordered(list(coll.values()))
