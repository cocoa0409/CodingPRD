"""In-memory data store and the server logical clock.

The store starts empty on every boot; no entity is ever seeded, preloaded, or
hardcoded at startup. All state is built through the declared API surface.
"""
import uuid
from datetime import datetime, timezone

DB = {
    "bases": {},
    "aircraft": {},
    "pilots": {},
    "routes": {},
    "clients": {},
    "campaigns": {},
    "airspace_approvals": {},
    "tfr_restrictions": {},
    "banners": {},
    "banner_revisions": {},
    "seasonal_capacities": {},
    "flight_slots": {},
    "weather_assessments": {},
    "flight_logs": {},
    "make_good_credits": {},
    "proof_of_flights": {},
    "invoices": {},
}

# Logical clock (PRD 2.5): at server startup the logical clock reads exactly
# 2026-08-01T00:00:00Z and never falls back to the host wall clock. Every
# time-dependent rule (booking lead times, scheduling cutoffs, TFR overlap,
# approval-window containment, credit expiry) and every server-stamped
# timestamp reads this clock.
_START_ISO = "2026-08-01T00:00:00Z"
_CLOCK = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}

# Monotone insertion sequence used as a stable tie-break after created_at.
_SEQ = {"n": 0}


def new_id():
    """Server-minted UUID with no type prefix."""
    return str(uuid.uuid4())


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def clock_now():
    return _CLOCK["now"]


def set_clock(dt):
    _CLOCK["now"] = dt


def fmt_ts(dt):
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return fmt_ts(clock_now())
