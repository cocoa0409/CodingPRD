"""In-memory data store. Starts empty on every boot — no seeding.

The logical clock (PRD §2.4) starts at exactly 2026-08-01T00:00:00Z and is
only ever moved by POST /_clock/set_current_utc; the server never falls back
to wall-clock time for date-dependent rules. Record created_at/updated_at
timestamps are also stamped from the logical clock (3 fractional digits).
"""

from datetime import datetime, timezone


def new_store():
    return {
        "jurisdiction_rules": {},   # id -> record
        "jurisdiction_index": {},   # jurisdiction code -> rule id
        "clients": {},              # id -> record
        "contacts": {},             # id -> record
        "counsel_firms": {},        # id -> record
        "inventors": {},            # id -> record
        "families": {},             # id -> record
        "applications": {},         # id -> record
        "docket_entries": {},       # id -> record
        "office_actions": {},       # id -> record
        "obligations": {},          # id -> record
        "authorizations": {},       # id -> record
        "instructions": {},         # id -> record
        "reviews": {},              # id -> record
        "assignments": {},          # id -> record
        "audits": {},               # id -> record
        # logical clock: startup default exactly 2026-08-01T00:00:00Z
        "clock": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc),
    }


DB = new_store()


def current_dt():
    return DB["clock"]


def current_date():
    return DB["clock"].date()


def _fmt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    """Wall-clock UTC timestamp for response meta (3 fractional digits)."""
    return _fmt(datetime.now(timezone.utc))


def logical_iso():
    """Logical-clock timestamp for created_at/updated_at on domain records."""
    return _fmt(DB["clock"])
