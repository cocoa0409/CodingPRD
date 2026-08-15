"""In-memory data store and logical clock.

Storage is in-memory only: plain dicts keyed by resource id. No files, no
SQLite, no external persistence. The store starts empty on every boot; the
only startup state is the mandated logical-clock default of
2026-08-01T00:00:00Z (a clock default, not entity data).
"""

import uuid
from datetime import datetime, timezone

# Logical clock: starts exactly at 2026-08-01T00:00:00Z and never falls back
# to wall-clock time.
_clock = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}

# Monotonic insertion counter used only as a deterministic tie-break after
# created_at (never serialized).
_seq = {"n": 0}


def fresh_db():
    return {
        "subscription_plans": {},
        "service_zones": {},
        "customers": {},
        "subscriptions": {},
        "service_pauses": {},
        "starter_kits": {},
        "inventory_pools": {},
        "inventory_swaps": {},
        "routes": {},
        "route_stops": {},
        "soiled_intakes": {},
        "wash_formulas": {},
        "wash_batches": {},
        "lost_item_cases": {},
        "invoices": {},
    }


db = fresh_db()


def clock_now():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


def clock_today():
    return _clock["now"].astimezone(timezone.utc).date()


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_ts_seconds(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def clock_now_iso():
    return fmt_ts(_clock["now"])


def new_id():
    return str(uuid.uuid4())


def new_resource(fields):
    """Create a resource dict with system-managed common fields."""
    _seq["n"] += 1
    now = clock_now_iso()
    r = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": _seq["n"],
    }
    r.update(fields)
    return r


def touch(r):
    """Register a mutation: bump optimistic-concurrency version + timestamp."""
    r["updated_at"] = clock_now_iso()
    r["version"] += 1


def public(r):
    """Strip internal keys (prefixed with '_') for serialization."""
    return {k: v for k, v in r.items() if not k.startswith("_")}
