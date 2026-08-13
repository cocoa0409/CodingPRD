"""In-memory data store and test-driving logical clock.

All state lives in module-level dicts keyed by id. Nothing is persisted to
disk; every boot starts with an empty store (per benchmark contract).
"""
import threading
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Logical clock (PRD section 2.4)
# ---------------------------------------------------------------------------
_CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock_now = _CLOCK_DEFAULT


def clock_now():
    """Current logical instant. Never falls back to wall-clock time."""
    return _clock_now


def set_clock(dt):
    global _clock_now
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _clock_now = dt.astimezone(timezone.utc)


def iso(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-08-01T00:00:00.000Z"""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return iso(_clock_now)


# ---------------------------------------------------------------------------
# Entity stores (empty at startup; populated only via declared API calls)
# ---------------------------------------------------------------------------
credit_unions = {}
cusos = {}
investments = {}
agreements = {}
offerings = {}
certificates = {}
exceptions = {}
remittances = {}
reports = {}
exams = {}
findings = {}
loss_events = {}
repurchase_cases = {}

STORES = {
    "credit_union": credit_unions,
    "cuso": cusos,
    "investment": investments,
    "agreement": agreements,
    "offering": offerings,
    "certificate": certificates,
    "exception": exceptions,
    "remittance": remittances,
    "report": reports,
    "exam": exams,
    "finding": findings,
    "loss_event": loss_events,
    "repurchase_case": repurchase_cases,
}

_seq_lock = threading.Lock()
_seq = 0


def next_seq():
    global _seq
    with _seq_lock:
        _seq += 1
        return _seq


def new_id():
    return str(uuid.uuid4())


def insert(kind, entity):
    entity["id"] = new_id()
    entity["created_at"] = clock_now()
    entity["updated_at"] = clock_now()
    entity["version"] = 1
    entity["_seq"] = next_seq()
    STORES[kind][entity["id"]] = entity
    return entity
