"""In-memory data store (PRD §2.4). State is wiped on every process boot."""

import uuid

from clock import Clock


class DB:
    def __init__(self):
        self.clock = Clock()
        # One dict per entity type, keyed by id.
        self.children = {}
        self.therapists = {}
        self.evaluations = {}
        self.plans_of_care = {}
        self.goals = {}
        self.authorizations = {}
        self.appointments = {}
        self.session_notes = {}
        self.goal_progress_entries = {}
        self.coordination_plans = {}
        self.home_programs = {}
        self.waitlist_entries = {}

    def new_id(self):
        # PRD §2.4: a unique, server-minted identifier formatted as a UUID,
        # with no type prefix.
        return str(uuid.uuid4())

    def now_iso(self):
        return self.clock.now_iso()


# Single global store. Constructed fresh at import time => empty on every boot.
db = DB()
