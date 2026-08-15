"""In-memory data store. The store starts empty on every boot; no seeding."""
import uuid
from datetime import datetime, timezone

DB = {
    "rating_cycles": {},
    "measures": {},
    "cutpoint_sets": {},
    "measure_performances": {},
    "members": {},
    "care_gaps": {},
    "provider_groups": {},
    "incentive_payouts": {},
    "survey_vendors": {},
    "survey_waves": {},
    "complaint_cases": {},
    "rating_forecasts": {},
}

# Logical clock: startup default 2026-08-01T00:00:00Z, never wall-clock.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"
LOGICAL_CLOCK = {"current": DEFAULT_CLOCK}

# Monotonic insertion sequence for deterministic created_at tie-breaking.
_SEQ = {"n": 0}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Wall-clock UTC timestamp used for created_at/updated_at (not the logical clock)."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"
