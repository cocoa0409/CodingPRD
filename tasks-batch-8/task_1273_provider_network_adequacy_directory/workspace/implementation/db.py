"""In-memory data store.

All state lives in module-level dicts keyed by id. The store starts empty on
every boot — nothing is seeded. The logical clock starts at exactly
2026-05-01T00:00:00Z and is advanced only via POST /_clock/set_current_utc.
"""

from datetime import datetime, timezone


def _initial_clock() -> datetime:
    return datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


# Logical clock (never falls back to wall clock)
clock_now: datetime = _initial_clock()

# Entity stores, keyed by id
regions = {}
standards = {}
providers = {}
locations = {}
listings = {}
members = {}
cycles = {}
records = {}
probes = {}
evaluations = {}
results = {}
deficiencies = {}
access_plan_requests = {}
complaints = {}
corrections = {}
