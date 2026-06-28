"""In-memory data store (PRD: state is wiped on every process start).

Storage is plain Python dicts keyed by id. There is NO persistence, NO seeding,
and NO preloaded data — every entity is created by the test via the API surface.
A fresh process therefore starts with empty stores and the default logical clock.
"""
import threading
import uuid

from clock import Clock


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.clock = Clock()
        # One dict per entity collection, keyed by id.
        self.facilities = {}
        self.programs = {}
        self.cohorts = {}
        self.patients = {}
        self.assessments = {}
        self.admissions = {}
        self.authorizations = {}
        self.reviews = {}
        self.treatment_plans = {}
        self.meal_plans = {}
        self.meal_events = {}
        self.family_programs = {}
        self.discharge_plans = {}
        # Monotonic insertion counter to give deterministic created_at ordering
        # even when many records share the same logical-clock instant.
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_id(self):
        # PRD §2.4: "a server-minted UUID string with no type prefix".
        return str(uuid.uuid4())

    def now_iso(self):
        return self.clock.iso()


# Single module-level store instance. Created empty; never seeded.
store = Store()
