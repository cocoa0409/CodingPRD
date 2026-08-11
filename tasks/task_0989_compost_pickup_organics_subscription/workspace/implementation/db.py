"""In-memory data store, logical clock, id/timestamp helpers.

Storage is process-local dicts keyed by id. Nothing is seeded at startup;
the store starts empty on every boot. The logical clock starts at exactly
2026-05-01T00:00:00Z and is only moved by POST /_clock/set_current_utc.
"""

import threading
import uuid
from datetime import datetime, timedelta, timezone

store = {
    "service_plans": {},
    "subscribers": {},
    "subscriptions": {},
    "routes": {},
    "bins": {},
    "pickups": {},
    "tags": {},
    "weigh_tickets": {},
    "credit_entries": {},
    "redemptions": {},
    "invoices": {},
}

lock = threading.RLock()

_seq = [0]
_last_ts = [None]
# Logical clock: never falls back to wall-clock time (PRD 2.4).
_clock = [datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)]


def new_id():
    return str(uuid.uuid4())


def next_seq():
    _seq[0] += 1
    return _seq[0]


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def wall_ts():
    """Monotonically increasing wall-clock timestamp string (created_at /
    updated_at), so created_at ordering always matches insertion order."""
    now = datetime.now(timezone.utc)
    if _last_ts[0] is not None and now <= _last_ts[0]:
        now = _last_ts[0] + timedelta(milliseconds=1)
    _last_ts[0] = now
    return fmt_ts(now)


def logical_now():
    return _clock[0]


def set_logical(dt):
    _clock[0] = dt


def touch(entity):
    """Any modification refreshes updated_at and bumps version (PRD 2.5)."""
    entity["updated_at"] = wall_ts()
    entity["version"] = entity.get("version", 0) + 1


def new_entity(common=True):
    e = {"id": new_id(), "_seq": next_seq(), "created_at": wall_ts()}
    if common:
        e["updated_at"] = e["created_at"]
        e["version"] = 1
    return e
