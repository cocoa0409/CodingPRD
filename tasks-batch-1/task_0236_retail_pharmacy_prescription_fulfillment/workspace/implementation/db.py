"""In-memory data store. Wiped on every process start (per-test-server boot).

NO seeding, preloading, or hardcoded entities — every entity is created by
tests through the declared API surface. The clock singleton is created lazily
on first access with its default deterministic epoch.
"""
import threading
import uuid

from clock import now_iso

# Logical clock default epoch (PRD §2.4).
CLOCK_DEFAULT_UTC = "2026-01-01T00:00:00.000Z"
CLOCK_ID = "clock"

# A coarse lock to keep multi-resource mutations atomic within a request.
LOCK = threading.RLock()

# One dict per entity collection, keyed by id.
drug_products = {}
insurance_plans = {}
formulary_entries = {}
interaction_rules = {}
patients = {}
prescribers = {}
prescriptions = {}
fills = {}
dur_alerts = {}
prior_auth_requests = {}
pdmp_reports = {}
payment_records = {}

# The logical clock singleton (created lazily).
_clock = None


def new_id():
    return str(uuid.uuid4())


def get_clock():
    """Return the singleton logical clock, creating it on first use.

    This is NOT entity seeding — it is the system epoch the PRD mandates
    (§2.4): the clock begins at a fixed deterministic instant and carries
    only id + created_at + current_utc (no version, no updated_at).
    """
    global _clock
    if _clock is None:
        ts = now_iso()
        _clock = {
            "id": CLOCK_ID,
            "created_at": ts,
            "current_utc": CLOCK_DEFAULT_UTC,
        }
    return _clock


def current_utc():
    """The deterministic logical wall clock used for ALL date math."""
    return get_clock()["current_utc"]
