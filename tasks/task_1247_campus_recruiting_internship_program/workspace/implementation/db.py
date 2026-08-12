"""In-memory data store. The store starts EMPTY on every boot — no seeding."""

import threading


class DB:
    def __init__(self):
        self.lock = threading.RLock()
        # Logical clock: starts at 2026-05-01T00:00:00Z, never falls back to wall clock.
        self.clock_utc = None  # None means the initial default instant
        self.seasons = {}
        self.school_targets = {}
        self.campus_events = {}
        self.candidates = {}
        self.applications = {}
        self.employees = {}
        self.interview_days = {}
        self.interview_slots = {}
        self.evaluations = {}
        self.offers = {}
        self.stipend_disbursements = {}
        self.intern_projects = {}
        self.project_assignments = {}
        self.intern_evaluations = {}


db = DB()
