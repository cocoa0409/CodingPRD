"""In-memory storage, the logical clock and row bookkeeping.

Every byte of state lives in module-level dicts, so a fresh process starts with a
completely empty program: no partner, no cycle, no volunteer is ever seeded.
"""
import itertools
import uuid
from datetime import datetime, timedelta, timezone

from config import CLOCK_START_ISO

TABLES = (
    "partner_orgs",
    "program_cycles",
    "project_requests",
    "scope_definitions",
    "deliverables",
    "volunteers",
    "skill_profiles",
    "availability_windows",
    "match_offers",
    "engagements",
    "agreements",
    "milestones",
    "time_logs",
    "scope_change_requests",
    "quality_reviews",
    "satisfaction_surveys",
    "valuation_records",
)

db = {name: {} for name in TABLES}

_seq_counter = itertools.count(1)


# --------------------------------------------------------------------------- #
# logical clock
# --------------------------------------------------------------------------- #
def parse_iso(text):
    """Parse an ISO 8601 UTC instant. Returns None when unparsable."""
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if not raw:
        return None
    if raw.endswith("z") or raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


_clock = {"now": parse_iso(CLOCK_START_ISO)}


def now():
    """The logical clock. Wall-clock time is never consulted."""
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


def hours(n):
    return timedelta(hours=n)


def days(n):
    return timedelta(days=n)


# --------------------------------------------------------------------------- #
# rows
# --------------------------------------------------------------------------- #
def new_id():
    return str(uuid.uuid4())


def insert(table, row, versioned=True):
    """Persist a new row, stamping identity and audit fields."""
    row["id"] = new_id()
    row["created_at"] = now()
    row["_seq"] = next(_seq_counter)
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    db[table][row["id"]] = row
    return row


def touch(row):
    """Advance a row's audit stamps: every mutation bumps version by exactly 1."""
    if row is None:
        return None
    if "version" in row:
        row["version"] = int(row["version"]) + 1
        row["updated_at"] = now()
    return row


def get(table, row_id):
    if not isinstance(row_id, str):
        return None
    return db[table].get(row_id)


def order_key(row):
    """Default ordering: created_at ascending, insertion order as tie-break.

    Row identifiers never participate in any ordering.
    """
    return (row["created_at"], row["_seq"])


def all_rows(table):
    return sorted(db[table].values(), key=order_key)


def where(table, **filters):
    out = []
    for row in db[table].values():
        if all(row.get(k) == v for k, v in filters.items()):
            out.append(row)
    return sorted(out, key=order_key)


def first(table, **filters):
    rows = where(table, **filters)
    return rows[0] if rows else None
