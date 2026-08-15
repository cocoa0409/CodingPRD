"""In-memory data store. Empty at every boot -- never seeded or preloaded."""
import itertools
from datetime import datetime, timezone

STORE = {
    "customers": {},
    "coating_specs": {},
    "paint_lines": {},
    "cure_ovens": {},
    "pretreatment_stages": {},
    "titration_readings": {},
    "lots": {},
    "run_slots": {},
    "oven_cycles": {},
    "quality_tests": {},
    "rework_orders": {},
    "color_changes": {},
    "voc_permits": {},
    "emission_entries": {},
}

# Global monotonic creation sequence; used as created_at tie-breaker and for
# "recorded after" epoch comparisons.
SEQ = itertools.count(1)

# Logical clock: startup default exactly 2026-05-01T00:00:00Z; never falls back
# to wall-clock time.
DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
CLOCK = {"now": DEFAULT_CLOCK}


def clock_now():
    return CLOCK["now"]


def set_clock(dt):
    CLOCK["now"] = dt
