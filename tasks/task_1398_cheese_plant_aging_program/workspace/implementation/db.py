"""In-memory data store and the logical plant clock (PRD section 2.4/2.5).

The store starts completely empty on every boot; all entity state is built
through the API. The logical clock defaults to exactly 2026-08-01T00:00:00Z
and never falls back to wall-clock time.
"""

import itertools
import uuid
from datetime import datetime, timezone

STORES = {
    "plants": {},
    "milk_intakes": {},
    "vats": {},
    "make_sheets": {},
    "additive_lots": {},
    "cheese_batches": {},
    "whey_streams": {},
    "aging_rooms": {},
    "aging_units": {},
    "grading_events": {},
    "allocation_orders": {},
    "cut_wrap_runs": {},
    "export_certificates": {},
}

_seq_counter = itertools.count(1)

# Logical clock — default reading before any clock call (PRD 2.4).
_clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def now():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


def next_seq():
    return next(_seq_counter)


def new_id():
    return str(uuid.uuid4())


def new_record():
    """Fresh common fields (PRD 2.5): id, created_at, updated_at, version."""
    ts = now()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(rec):
    """Every mutation bumps version by one and refreshes updated_at."""
    rec["version"] += 1
    rec["updated_at"] = now()
