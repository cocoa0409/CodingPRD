"""In-memory data store. Fresh on every process boot; no persistence."""

import uuid
import threading


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.nurses = {}
        self.ladder_criteria = {}
        self.participation_events = {}
        self.certifications = {}
        self.reimbursement_claims = {}
        self.certification_bonuses = {}
        self.applications = {}
        self.review_assignments = {}
        self.advancement_decisions = {}
        self.anniversary_reviews = {}
        self.budget_lines = {}
        self.retention_snapshots = {}
        # Event log used by calc_retention_risk trailing-window counting.
        # Entries: dict(event_kind, nurse_id, occurred_at, created_at, seq)
        self.risk_events = []
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_id(self):
        return str(uuid.uuid4())


db = Store()
