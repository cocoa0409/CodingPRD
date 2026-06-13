"""In-memory data store. All state lives in module-level dicts keyed by id.

The store starts EMPTY on every boot. Nothing is seeded, preloaded, or
hardcoded — every entity is constructed by a test via the declared API surface.
A fresh process therefore wipes every byte of state (per the benchmark contract).
"""
import threading
import uuid
from datetime import datetime, timezone

# One lock guarding all mutations (immediate-consistency model, §0.3).
LOCK = threading.RLock()

# Per-entity tables keyed by id.
clinics = {}
providers = {}
exam_rooms = {}
patients = {}
appointments = {}
intake_sessions = {}
insurance_cards = {}
eligibility_checks = {}
consent_documents = {}
questionnaire_responses = {}
copay_payments = {}
queue_entries = {}
room_bookings = {}
reminders = {}
demographics_sync_jobs = {}

# Insertion order counter so list endpoints can sort by created_at ascending
# deterministically even when several records share the same wall-clock ms.
_seq = {"n": 0}

# Per-clinic monotonic enqueue sequence for KioskQueueEntry.enqueued_seq.
_enqueue_seq = {}


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Wall-clock creation/update timestamp, ISO 8601 UTC, 3 fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def next_enqueue_seq(clinic_id):
    cur = _enqueue_seq.get(clinic_id, 0) + 1
    _enqueue_seq[clinic_id] = cur
    return cur
