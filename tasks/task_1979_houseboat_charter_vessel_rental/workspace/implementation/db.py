"""In-memory data store and logical clock.

The store starts completely empty on every boot — no seeding of any kind.
All temporal behavior is driven by a single logical clock (never wall-clock),
defaulting to exactly 2026-08-01T00:00:00Z at startup.
"""

import uuid
from datetime import datetime, timezone, date

# ---------------------------------------------------------------------------
# Entity stores: id -> record dict. Records carry common system fields:
# id (uuid string, no prefix), created_at, updated_at (ISO8601 ms precision),
# version (int, starts at 1, +1 per mutation), plus a private _seq used only
# for deterministic created_at tie-breaking in list sorting (never serialized).
# ---------------------------------------------------------------------------

store = {
    "vessels": {},
    "season_rates": {},
    "geo_zones": {},
    "renters": {},
    "certificates": {},
    "bookings": {},
    "itineraries": {},
    "charges": {},
    "incidents": {},
    "maintenance_windows": {},
    "cleaning_turns": {},
    "weather_advisories": {},
}

_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = DEFAULT_CLOCK


def get_clock():
    return _clock


def set_clock(dt):
    global _clock
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _clock = dt.astimezone(timezone.utc)


def current_date():
    return _clock.date()


# ---------------------------------------------------------------------------
# Formatting / record helpers
# ---------------------------------------------------------------------------

def fmt_dt(dt):
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_date(d):
    return d.isoformat()


def now_iso():
    return fmt_dt(_clock)


def new_id():
    return str(uuid.uuid4())


def base_record():
    """Common system-managed fields for every resource."""
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(rec):
    """Record a mutation: refresh updated_at and increment version by 1."""
    rec["updated_at"] = now_iso()
    rec["version"] += 1


def insert(kind, rec):
    store[kind][rec["id"]] = rec
    return rec


def get(kind, rid):
    return store[kind].get(rid)


def all_of(kind):
    return list(store[kind].values())


def sorted_created(records):
    """created_at ascending; _seq breaks ties deterministically."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
