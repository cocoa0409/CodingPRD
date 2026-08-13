"""In-memory data store and server-held logical clock.

Storage is in-memory only (Python dicts keyed by id). The store starts empty
on every boot; no entity is ever seeded, preloaded, or hardcoded at startup.
"""
import itertools
import threading
from datetime import datetime, timezone

# PRD 2.11: at server startup the logical clock reads exactly
# 2026-08-01T00:00:00Z and never falls back to wall-clock time.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.clock = CLOCK_DEFAULT
        self.seq = itertools.count(1)  # insertion sequence for created_at ordering
        self.projects = {}
        self.spec_sections = {}
        self.subcontractors = {}
        self.reviewers = {}
        self.submittals = {}
        self.revisions = {}
        self.long_lead_items = {}
        self.rfis = {}
        self.impact_assessments = {}
        self.distribution_records = {}
        self.installation_activities = {}
        self.owner_reports = {}
        self.escalation_events = {}


store = Store()

COLLECTIONS = [
    "projects", "spec_sections", "subcontractors", "reviewers", "submittals",
    "revisions", "long_lead_items", "rfis", "impact_assessments",
    "distribution_records", "installation_activities", "owner_reports",
    "escalation_events",
]
