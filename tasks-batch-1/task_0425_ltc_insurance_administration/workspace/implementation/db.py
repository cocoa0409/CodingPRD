"""In-memory data store. Starts empty on every boot; no seeding."""
import threading
import uuid
from datetime import datetime, timezone

from response import now_iso

# A single process-wide lock makes each request's mutations atomic relative to
# concurrent requests — important for the cascade operations.
LOCK = threading.RLock()


class Store:
    def __init__(self):
        # One dict per entity collection, keyed by id.
        self.policyholders = {}
        self.policies = {}
        self.benefit_pools = {}
        self.premium_invoices = {}
        self.rate_filings = {}
        self.trigger_certifications = {}
        self.providers = {}
        self.care_plans = {}
        self.claims = {}
        self.claim_lines = {}
        self.ledger_entries = {}
        self.partnership_disregards = {}
        # Monotonic counter to preserve creation order for ties / sorting.
        self._seq = 0
        # The deterministic test clock. None until first advance.
        self.clock_iso = None

    def next_seq(self):
        self._seq += 1
        return self._seq


STORE = Store()


def new_id():
    return str(uuid.uuid4())


def common_fields(seq):
    ts = now_iso()
    return {
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": seq,
    }


def touch(record):
    """Bump updated_at and version on a mutable record (PRD §2.4)."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1
