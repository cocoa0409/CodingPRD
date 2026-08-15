"""In-memory data store and the server logical clock.

The store starts empty on every boot; no seeding anywhere. All system-stamped
timestamps read the logical clock, which starts at 2026-05-01T00:00:00Z and is
repositioned only through POST /_clock/set_current_utc.
"""

from datetime import datetime, timezone

STORE = {
    "permits": {},
    "molds": {},
    "ply_books": {},
    "work_orders": {},
    "resin_batches": {},
    "layup_sessions": {},
    "equipment": {},
    "cure_cycles": {},
    "inspections": {},
    "repairs": {},
}

_seq = [0]


def next_seq():
    _seq[0] += 1
    return _seq[0]


_DEFAULT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = [_DEFAULT]


def now():
    return _clock[0]


def set_clock(dt):
    _clock[0] = dt


def fmt_dt(dt):
    """ISO 8601 UTC with three fractional digits (entity timestamps)."""
    return "%s.%03dZ" % (dt.strftime("%Y-%m-%dT%H:%M:%S"), dt.microsecond // 1000)


def touch(rec):
    rec["updated_at"] = fmt_dt(now())
    rec["version"] += 1


def new_base():
    import uuid

    ts = fmt_dt(now())
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
