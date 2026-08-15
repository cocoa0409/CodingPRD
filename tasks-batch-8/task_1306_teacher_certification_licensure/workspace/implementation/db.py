"""In-memory data store and logical clock.

The store starts completely empty on every boot. No seeding of any kind.
"""
import threading
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # entity collections, keyed by id
        self.applicants = {}
        self.programs = {}
        self.applications = {}
        self.transcripts = {}
        self.test_scores = {}
        self.background_checks = {}
        self.reciprocity_evaluations = {}
        self.deficiency_plans = {}
        self.licenses = {}
        self.endorsements = {}
        self.emergency_permits = {}
        self.ce_credits = {}
        self.ce_audits = {}
        self.misconduct_cases = {}
        self.disciplinary_actions = {}
        # sequential license number counter
        self.license_number_seq = 0
        # monotonic creation sequence for stable created_at tie-breaking
        self.create_seq = 0
        # logical clock
        self._clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self._clock

    def set_clock(self, dt):
        self._clock = dt

    def next_license_number(self):
        self.license_number_seq += 1
        return "LIC-%06d" % self.license_number_seq


db = Store()
