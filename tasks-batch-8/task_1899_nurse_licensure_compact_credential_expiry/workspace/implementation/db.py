"""In-memory data store. Starts empty on every boot — no seeding.

Every entity dict carries internal keys prefixed with "_" (e.g. _seq) that are
stripped during serialization. Stores are plain dicts keyed by id; Python dicts
preserve insertion order, and a global sequence counter gives a deterministic
tie-break for rows sharing a single clock instant.
"""

import itertools
from datetime import datetime, timezone

STORES = {
    "nurses": {},
    "licenses": {},
    "psvs": {},
    "certifications": {},
    "disciplines": {},
    "packets": {},
    "packet_items": {},
    "requirements": {},
    "completions": {},
    "units": {},
    "shifts": {},
    "sessions": {},
    "bookings": {},
    "evaluations": {},
    "audit_runs": {},
    "audit_findings": {},
}

_seq_counter = itertools.count(1)


def next_seq():
    return next(_seq_counter)


# --- Logical clock -----------------------------------------------------------
# Startup default is exactly 2026-08-01T00:00:00Z and NEVER falls back to the
# wall clock. All date comparisons read this clock.
CLOCK = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}


def logical_now():
    return CLOCK["now"]


def set_logical_now(dt):
    CLOCK["now"] = dt


def current_date():
    return CLOCK["now"].date()
