"""In-memory data store. Fresh and EMPTY on every process boot — no seeding.

All entity state is created by tests via the declared API surface.
"""
import itertools
import uuid

from clock import LogicalClock

# Served-counties configuration (PRD §2.8 / §3.2). The office serves a fixed
# configured list; a county not in the list is DECLINED at triage. "Kings" is
# served; anything else (e.g. "Elsewhere") is out of jurisdiction.
SERVED_COUNTIES = {"Kings"}


class DB:
    def __init__(self):
        self.clock = LogicalClock()
        # one dict per entity type, keyed by id
        self.cases = {}
        self.investigators = {}
        self.pathologists = {}
        self.cooler_units = {}
        self.bodies = {}
        self.autopsy_exams = {}
        self.specimens = {}
        self.tox_screens = {}
        self.death_certificates = {}
        self.next_of_kin = {}
        self.property_items = {}
        self.property_releases = {}
        self.indigent_dispositions = {}
        # monotonic sequence to order creations deterministically for list sorting
        self._seq = itertools.count(1)

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        return next(self._seq)


db = DB()
