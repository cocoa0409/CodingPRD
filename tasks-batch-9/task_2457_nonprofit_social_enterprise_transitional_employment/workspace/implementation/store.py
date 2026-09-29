"""In-memory data store, logical clock and record bookkeeping.

Storage is process-local Python dicts only.  Nothing is persisted anywhere, so
re-launching the process wipes every byte of state.  No entity is ever seeded.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from flask import g

# Before any client sets it, the logical clock reads exactly this instant (PRD 2.5).
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

KINDS = [
    "business_lines",
    "referral_partners",
    "referrals",
    "participants",
    "work_shifts",
    "shift_assignments",
    "support_activities",
    "employers",
    "placements",
    "retention_checkpoints",
    "subsidy_periods",
    "cost_entries",
]


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for kind in KINDS:
            setattr(self, kind, {})
        self.now = CLOCK_EPOCH
        self.seq = 0

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()


# --------------------------------------------------------------------------- #
# logical clock helpers
# --------------------------------------------------------------------------- #

def now():
    return store.now


def fmt_dt(value):
    """ISO 8601 UTC with exactly three fractional digits."""
    if value is None:
        return None
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (value.microsecond // 1000)


def parse_iso(value):
    """Parse an ISO 8601 UTC instant.  Raises ValueError when malformed."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("not a datetime string")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def days(count):
    return timedelta(days=count)


def iso_week_start(instant):
    """Monday 00:00:00Z of the ISO week containing `instant`."""
    midnight = instant.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight - timedelta(days=midnight.weekday())


# --------------------------------------------------------------------------- #
# record bookkeeping
# --------------------------------------------------------------------------- #

def _touched_set():
    if not hasattr(g, "touched_rows"):
        g.touched_rows = set()
    return g.touched_rows


def create_record(kind, fields):
    """Mint a new row.  Every row carries id/created_at/updated_at/version."""
    record = {
        "id": str(uuid.uuid4()),
        "created_at": store.now,
        "updated_at": store.now,
        "version": 1,
        "_kind": kind,
        "_seq": store.next_seq(),
    }
    record.update(fields)
    getattr(store, kind)[record["id"]] = record
    # Creation is itself the row's first mutation; later touches inside the same
    # request must not push the version past 1.
    _touched_set().add(record["id"])
    return record


def touch(record):
    """Refresh updated_at and bump version at most once per request per row."""
    touched = _touched_set()
    record["updated_at"] = store.now
    if record["id"] not in touched:
        record["version"] = record["version"] + 1
        touched.add(record["id"])


def set_fields(record, **updates):
    """Assign fields, refreshing updated_at/version only when something changed."""
    changed = False
    for key, value in updates.items():
        current = record.get(key, "__missing__")
        if current == "__missing__" or not _same(current, value):
            record[key] = value
            changed = True
    if changed:
        touch(record)
    return changed


def _same(left, right):
    if isinstance(left, Decimal) or isinstance(right, Decimal):
        if left is None or right is None:
            return left is None and right is None
        try:
            return Decimal(str(left)) == Decimal(str(right))
        except Exception:
            return False
    return left == right


def collection(kind):
    return getattr(store, kind)


def sort_key(record):
    return (record["created_at"], record["_seq"])


def all_records(kind):
    """Every row of a kind, ordered by created_at ascending (creation order)."""
    return sorted(getattr(store, kind).values(), key=sort_key)
