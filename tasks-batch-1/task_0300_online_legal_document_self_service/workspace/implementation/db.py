"""In-memory data store for the Legal Document Self-Service API.

All storage is in-memory only — Python dicts keyed by id. The store starts
EMPTY on every process boot; no entity is seeded, preloaded, or hardcoded.
Tests construct every entity they need via the declared API surface.
"""

import threading
import uuid
from datetime import datetime, timezone


class Store:
    """Holds all entity collections plus the logical clock."""

    def __init__(self):
        self.lock = threading.RLock()
        # One dict per entity collection, keyed by id.
        self.customers = {}
        self.subscription_plans = {}
        self.subscriptions = {}
        self.clause_templates = {}
        self.document_projects = {}
        self.questionnaire_responses = {}
        self.assembled_clauses = {}
        self.document_revisions = {}
        self.attorneys = {}
        self.attorney_reviews = {}
        self.signature_requests = {}
        self.notary_referrals = {}
        self.orders = {}
        self.update_reminders = {}

        # Monotonic creation sequence for deterministic created_at ordering.
        self._seq = 0
        # Logical clock for reminder due_at comparisons (test-driving). None
        # means "unset" — when unset, due-time comparisons fall back to wall clock.
        self.clock_now = None

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


def new_id():
    """Server-minted UUID with no type prefix."""
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC instant with exactly three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
