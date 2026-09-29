"""In-memory data store, logical clock and record helpers.

Storage is process-local Python dicts keyed by id. Nothing is persisted and
nothing is seeded: the store starts completely empty on every boot and every
row is created by an API call.
"""

import copy
import uuid
from datetime import datetime, timedelta, timezone

from flask import g

# PRD 2.5 -- the logical clock starts here on every fresh boot.
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

ENTITY_COLLECTIONS = (
    "applicants",
    "facilities",
    "allocations",
    "banks",
    "beneficiaries",
    "credits",
    "requirements",
    "amendments",
    "presentations",
    "documents",
    "discrepancies",
    "waivers",
    "claims",
    "screenings",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in ENTITY_COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_START
        self._counter = 0

    def next_seq(self):
        self._counter += 1
        return self._counter

    def snapshot(self):
        return copy.deepcopy({k: getattr(self, k) for k in ENTITY_COLLECTIONS + ("clock", "_counter")})

    def restore(self, snap):
        for key, value in snap.items():
            setattr(self, key, value)


db = Store()


# --------------------------------------------------------------------------
# instants and dates
# --------------------------------------------------------------------------

def fmt_instant(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def wall_now_iso():
    return fmt_instant(datetime.now(timezone.utc))


def clock_dt():
    return db.clock


def clock_instant():
    return fmt_instant(db.clock)


def clock_date():
    return db.clock.date()


def clock_date_str():
    return db.clock.date().isoformat()


def end_of_day(d):
    """A deadline derived from a date lands at 23:59:59.999Z on that date."""
    return datetime(d.year, d.month, d.day, 23, 59, 59, 999000, tzinfo=timezone.utc)


def end_of_day_iso(d):
    return fmt_instant(end_of_day(d))


def parse_instant(text):
    """Parse an ISO 8601 instant; returns None when unparseable."""
    if not isinstance(text, str) or not text.strip():
        return None
    raw = text.strip()
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# --------------------------------------------------------------------------
# rows
# --------------------------------------------------------------------------

def new_row(**fields):
    now = clock_instant()
    row = {"id": str(uuid.uuid4())}
    row.update(fields)
    row["created_at"] = now
    row["updated_at"] = now
    row["version"] = 1
    row["_seq"] = db.next_seq()
    return row


def new_bare_row(**fields):
    """PresentedDocument carries only id and created_at (PRD 2.4)."""
    row = {"id": str(uuid.uuid4())}
    row.update(fields)
    row["created_at"] = clock_instant()
    row["_seq"] = db.next_seq()
    return row


def _touched_set():
    marker = getattr(g, "_touched_rows", None)
    if marker is None:
        marker = set()
        g._touched_rows = marker
    return marker


def touch(row):
    """Bump version/updated_at once per row per request (PRD 2.4)."""
    if row is None:
        return row
    if "version" not in row:
        return row
    marker = _touched_set()
    if row["id"] in marker:
        return row
    marker.add(row["id"])
    row["version"] = int(row["version"]) + 1
    row["updated_at"] = clock_instant()
    return row


def public(row):
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


def by_created(rows):
    """Default list ordering: created_at ascending (insertion order)."""
    return sorted(rows, key=lambda r: r["_seq"])


def add_days(d, n):
    return d + timedelta(days=n)
