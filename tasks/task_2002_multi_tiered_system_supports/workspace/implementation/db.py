"""In-memory data store. Starts empty on every boot; no seeding."""

import threading


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.districts = {}
        self.schools = {}
        self.screening_windows = {}
        self.cut_points = {}
        self.students = {}
        self.screening_scores = {}
        self.catalog_entries = {}
        self.interventionists = {}
        self.plans = {}
        self.probes = {}
        self.sessions = {}
        self.tier_movements = {}
        self.team_meetings = {}
        self.sped_referrals = {}
        # Monotonic sequence for stable created_at tie-breaking.
        self.seq = 0
        # Logical clock; ISO 8601 string in UTC. Startup default per PRD §2.7.
        # MUST NOT fall back to wall-clock time.
        self.clock = "2026-08-01T00:00:00Z"

    def next_seq(self):
        self.seq += 1
        return self.seq


DB = Store()
