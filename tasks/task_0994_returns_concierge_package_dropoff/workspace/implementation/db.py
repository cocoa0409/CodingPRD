"""In-memory data store and logical clock. The store starts EMPTY on every
boot: no seeding, no preload, no file persistence."""

import uuid
from datetime import datetime, timezone

COLLECTIONS = (
    "plans", "merchants", "cycles", "shoppers", "orders", "items",
    "locations", "slots", "reservations", "labels", "zones",
    "appointments", "routes", "totes", "ledger", "exceptions",
)

store = {name: {} for name in COLLECTIONS}

_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


# Logical clock: starts at exactly 2026-05-01T00:00:00Z; never wall-clock.
_logical_now = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


def now():
    return _logical_now


def set_now(dt):
    global _logical_now
    _logical_now = dt


def new_id():
    return str(uuid.uuid4())


def fmt_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_s(dt):
    """ISO 8601 UTC, second precision."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp(rec):
    """Initialize system-managed common fields on creation."""
    rec["id"] = new_id()
    t = now()
    rec["created_at"] = t
    rec["updated_at"] = t
    rec["version"] = 1
    rec["_seq"] = next_seq()
    return rec


def stamp_immutable(rec):
    """RefundLedgerEntry: id + created_at only (append-only event log)."""
    rec["id"] = new_id()
    rec["created_at"] = now()
    rec["_seq"] = next_seq()
    return rec


def touch(rec):
    """Refresh updated_at and bump optimistic-concurrency version."""
    rec["updated_at"] = now()
    rec["version"] += 1
