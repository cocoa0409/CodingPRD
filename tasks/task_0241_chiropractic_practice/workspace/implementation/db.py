"""In-memory data store. Everything lives in module-level dicts keyed by id.

The store starts EMPTY on every boot — no seeding, no preloaded entities.
start.sh re-invocation (per-test-server isolation) wipes all state.
"""
import uuid
from datetime import datetime, timezone

# One dict per entity type, keyed by id.
providers = {}
treatment_rooms = {}
fee_schedules = {}
wellness_plans = {}
patients = {}
insurance_policies = {}
exam_records = {}
treatment_plans = {}
plan_phases = {}
appointment_series = {}
appointments = {}
soap_notes = {}
ledger_entries = {}

# Singleton practice clock. current_utc defaults to None until set; when None we
# fall back to real wall-clock UTC so late-cancel/no-show math still works.
practice_clock = {
    "id": str(uuid.uuid4()),
    "created_at": None,
    "current_utc": None,
}

# Monotonic creation sequence so list ordering by creation is stable even when
# multiple records share an identical created_at timestamp.
_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC timestamp with three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
