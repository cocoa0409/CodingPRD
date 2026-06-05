"""In-memory data store. Everything lives in process memory only.

The store starts EMPTY on every boot. No entity is ever seeded, preloaded,
hardcoded, or registered at startup. Tests build all state via the API.
"""
import itertools
import threading
import uuid
from datetime import datetime, timezone

# Process-global monotonic sequence. Stamped on every created entity so that
# creation order is preserved as a stable tiebreaker even when two entities are
# minted at the same simulated-clock instant (list ordering / promotion ties).
_seq_counter = itertools.count(1)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # One dict per entity collection, keyed by id.
        self.test_centers = {}
        self.test_sessions = {}
        self.candidates = {}
        self.registrations = {}
        self.accommodation_requests = {}
        self.standby_entries = {}
        self.score_reports = {}
        self.score_sends = {}
        self.clep_claims = {}
        self.id_verifications = {}

        # Simulated clock ("now") used for all day/hour-difference calculations.
        # Defaults to real wall-clock UTC until a test sets it via the clock endpoint.
        self._clock_now = None

    # ----- clock -----
    def get_clock_now(self):
        if self._clock_now is not None:
            return self._clock_now
        return datetime.now(timezone.utc)

    def set_clock_now(self, dt):
        self._clock_now = dt


def new_id():
    return str(uuid.uuid4())


def now_iso_ms():
    """Current instant on the SIMULATED clock, formatted ISO 8601 with ms.

    Per PRD §2.11 the platform runs against a settable logical clock rather than
    wall-clock time; server-minted created_at/updated_at timestamps live on that
    same timeline so that hour/day-difference computations (standby recency,
    refund tiers) measured against the simulated "now" are coherent. When no
    clock has been set, get_clock_now() falls back to real wall-clock UTC.
    """
    now = store.get_clock_now()
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def stamp_create(obj):
    """Set id / created_at / updated_at / version common fields on a fresh entity."""
    ts = now_iso_ms()
    obj["id"] = new_id()
    obj["created_at"] = ts
    obj["updated_at"] = ts
    obj["version"] = 1
    # Monotonic creation-order tiebreaker (not serialized to clients).
    obj["_seq"] = next(_seq_counter)
    return obj


def touch(obj):
    """Bump updated_at and version on a mutation."""
    obj["updated_at"] = now_iso_ms()
    obj["version"] = obj.get("version", 1) + 1
    return obj


# Single global store instance. Created fresh on every process boot.
store = Store()
