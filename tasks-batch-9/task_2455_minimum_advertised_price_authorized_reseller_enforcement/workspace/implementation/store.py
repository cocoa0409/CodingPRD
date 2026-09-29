"""In-memory store, the deterministic logical clock and row helpers.

Storage is process-memory only (plain dicts keyed by id).  Nothing is persisted
and nothing is seeded: every row is created by a client through the declared
API surface.
"""

import itertools
import uuid
from datetime import datetime, timedelta, timezone

# PRD §2.6 — before any client pins it, the logical clock reads this instant.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)
        self.policies = {}
        self.products = {}
        self.resellers = {}
        self.distributors = {}
        self.agreements = {}
        self.observations = {}
        self.violations = {}
        self.notices = {}
        self.exceptions = {}
        self.serial_units = {}
        self.test_purchases = {}
        self.chargebacks = {}

    def next_seq(self):
        return next(self._seq)


store = Store()


# --------------------------------------------------------------------------
# Clock / timestamp helpers (PRD §2.4, §2.6)
# --------------------------------------------------------------------------
def now_dt():
    return store.clock


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def now_iso():
    return fmt(store.clock)


def parse_iso(value):
    """Parse an ISO 8601 instant; returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def dt_of(row, field):
    """Parsed datetime of a stored (string) datetime field."""
    return parse_iso(row.get(field))


def days(n):
    return timedelta(days=n)


# --------------------------------------------------------------------------
# Row helpers (PRD §2.4)
# --------------------------------------------------------------------------
def new_row(fields):
    stamp = now_iso()
    row = {
        "id": str(uuid.uuid4()),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
    }
    row.update(fields)
    row["_seq"] = store.next_seq()
    return row


def _touched_set():
    try:
        from flask import g, has_request_context
        if has_request_context():
            if not hasattr(g, "_touched_rows"):
                g._touched_rows = set()
            return g._touched_rows
    except Exception:
        pass
    return None


def touch(row):
    """Advance a row's version counter and refresh updated_at.

    A row mutated several times while serving one request advances its counter
    exactly once — PRD §3.7 enumerates a single termination notice as advancing
    "the reseller" once even though it moves both the ledger and both axes.
    """
    seen = _touched_set()
    key = id(row)
    row["updated_at"] = now_iso()
    if seen is not None:
        if key in seen:
            return row
        seen.add(key)
    row["version"] = row.get("version", 1) + 1
    return row


def sort_rows(rows):
    """PRD §2.3 — created_at ascending, stable across repeated reads."""
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq", 0)))


def serialize(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def serialize_all(rows):
    return [serialize(r) for r in rows]


def values(collection):
    return list(collection.values())
