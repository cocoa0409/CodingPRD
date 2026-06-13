"""In-memory data store and shared helpers.

Storage is entirely in-process Python dicts keyed by UUID. There is NO
persistence of any kind: a fresh process boots an empty store, which is
exactly what the per-test-server harness relies on.

The store is NEVER seeded — all entities are created by tests via the API.
"""

import threading
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.families = {}
        self.caregivers = {}
        self.background_checks = {}
        self.job_postings = {}
        self.interviews = {}
        self.bookings = {}
        self.sessions = {}
        self.backup_requests = {}
        self.payouts = {}
        self.reviews = {}
        self.tax_statements = {}
        # Deterministic test clock; defaults to real "now" until set.
        self._clock = datetime.now(timezone.utc)
        self.lock = threading.RLock()

    # ---- clock --------------------------------------------------------
    def now(self):
        return self._clock

    def set_clock(self, dt):
        self._clock = dt


store = Store()


# --- ids / timestamps ------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC with exactly three fractional digits (milliseconds)."""
    return iso(store.now())


def iso(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO 8601 string into a tz-aware UTC datetime.

    Returns None on any failure so callers can raise the right error.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# --- tier ordering ---------------------------------------------------------
TIER_ORDER = {"NONE": 0, "BASIC": 1, "STANDARD": 2, "PREMIUM": 3}


def tier_rank(t):
    return TIER_ORDER.get(t, -1)


def tier_max(a, b):
    return a if tier_rank(a) >= tier_rank(b) else b
