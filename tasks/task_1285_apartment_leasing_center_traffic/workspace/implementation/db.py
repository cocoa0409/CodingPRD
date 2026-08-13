"""In-memory data store. The store starts empty on every boot; no seeding.

All entity timestamps (created_at, updated_at, first_responded_at, deadlines,
expirations) are derived from the single server-side logical clock, never from
wall-clock time (PRD §2.4). The logical clock defaults to 2026-08-01T00:00:00Z.
"""
import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK_STR = "2026-08-01T00:00:00Z"

DB = {
    "properties": {},
    "agents": {},
    "floorplans": {},
    "offers": {},
    "inquiries": {},
    "tours": {},
    "waitlist_entries": {},
    "applications": {},
    "leases": {},
    "moveins": {},
    # Logical clock (aware datetime, UTC) and a monotonic creation sequence used
    # as a stable tie-break when many rows share one logical-clock timestamp.
    "_clock": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc),
    "_seq": 0,
}


def new_id():
    return str(uuid.uuid4())


def next_seq():
    DB["_seq"] += 1
    return DB["_seq"]


def clock_now():
    return DB["_clock"]


def set_clock(dt):
    DB["_clock"] = dt


def fmt_dt(dt):
    """Serialize an aware UTC datetime.

    Compact `...T HH:MM:SSZ` form when the value lands on a whole second (this
    matches every literal timestamp in the spec/recipes); three fractional
    digits otherwise. Both forms satisfy the ISO-8601 envelope contract.
    """
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def meta_ts():
    """Envelope meta timestamp: wall-clock UTC with three fractional digits."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"
