"""In-memory store.

Storage is plain Python dicts keyed by id, held in this module's globals for the
lifetime of the process.  There is no database, no file, no cache and no other
form of persistence of any kind: a fresh `bash start.sh` starts with every
collection empty.  NOTHING is ever seeded here -- every entity a test needs is
built by the test through the declared endpoints.
"""

import itertools
import uuid
from datetime import datetime, timezone

from timeutil import Ts, canonical, mint, parse_dt

# --- collections -----------------------------------------------------------
inmates = {}
intake_screenings = {}
chronic_enrollments = {}
chronic_visits = {}
sick_calls = {}
medication_orders = {}
medication_administrations = {}
specialty_referrals = {}
utilization_reviews = {}
transport_orders = {}
copay_charges = {}
ledger_entries = {}
grievances = {}
release_plans = {}
mortality_reviews = {}

COLLECTIONS = (
    inmates, intake_screenings, chronic_enrollments, chronic_visits, sick_calls,
    medication_orders, medication_administrations, specialty_referrals,
    utilization_reviews, transport_orders, copay_charges, ledger_entries,
    grievances, release_plans, mortality_reviews,
)

_seq = itertools.count(1)

# --- logical clock ---------------------------------------------------------
# Before any call to POST /_clock/set_current_utc the logical clock reads
# exactly 2026-05-01T00:00:00Z.  It never falls back to host wall-clock time.
DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = DEFAULT_CLOCK


def clock_dt():
    return _clock


def now():
    """Current logical-clock instant as a server-generated Ts."""
    return mint(_clock)


def set_clock(dt):
    global _clock
    _clock = dt


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def base_row(with_version=True):
    """Common system fields.  `_seq` gives a stable tie-break for equal created_at."""
    stamp = now()
    row = {
        "id": new_id(),
        "created_at": stamp,
        "_seq": next_seq(),
    }
    if with_version:
        row["updated_at"] = stamp
        row["version"] = 1
    return row


def touch(row):
    """Persisted mutation: refresh updated_at and advance version by exactly 1."""
    row["updated_at"] = now()
    row["version"] = row.get("version", 1) + 1
    return row


def sort_rows(rows, key="created_at"):
    def sort_key(r):
        value = r.get(key)
        dt = value.dt if isinstance(value, Ts) else None
        return (dt is None, dt or datetime.min.replace(tzinfo=timezone.utc), r.get("_seq", 0))

    return sorted(rows, key=sort_key)


def reset():  # pragma: no cover - only used by local smoke checks
    for collection in COLLECTIONS:
        collection.clear()
    set_clock(DEFAULT_CLOCK)
