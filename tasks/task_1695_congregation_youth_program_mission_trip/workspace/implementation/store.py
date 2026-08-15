"""In-memory data store, logical clock, and common-field machinery.

The store starts EMPTY on every boot. No seeding of any kind.
"""
import itertools
import uuid
from datetime import datetime, timezone

from util import fmt_clock


class Store:
    def __init__(self):
        self.programs = {}
        self.trips = {}
        self.participants = {}
        self.registrations = {}
        self.consent_forms = {}
        self.fundraising_accounts = {}
        self.donations = {}
        self.payments = {}
        self.scholarship_applications = {}
        self.chaperones = {}
        self.background_checks = {}
        self.chaperone_assignments = {}
        self.itinerary_items = {}
        self.lodging_reservations = {}

        self._seq = itertools.count(1)

        # Logical clock: never reads wall clock for domain timestamps.
        self.clock_dt = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

        # Per-request set of entities already version-bumped (coalescing).
        self._bumped = set()

    # -- common fields ------------------------------------------------------

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        return next(self._seq)

    def stamp_created(self, entity):
        ts = self._clock_stamp()
        entity["id"] = self.new_id()
        entity["created_at"] = ts
        entity["updated_at"] = ts
        entity["version"] = 1
        entity["_seq"] = self.next_seq()
        return entity

    def begin_request(self):
        self._bumped = set()

    def touch(self, collection_name, entity_id):
        """Bump version + updated_at at most once per entity per request."""
        key = (collection_name, entity_id)
        if key in self._bumped:
            return
        self._bumped.add(key)
        coll = getattr(self, collection_name)
        ent = coll.get(entity_id)
        if ent is None:
            return
        ent["version"] += 1
        ent["updated_at"] = self._clock_stamp()

    def _clock_stamp(self):
        """created_at/updated_at are stamped from the logical clock (PRD §2.4:
        "The system never reads the wall clock") rendered with the three
        fractional digits PRD §2.5 requires of the common fields."""
        dt = self.clock_dt
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"

    def clock_string(self):
        return fmt_clock(self.clock_dt)


DB = Store()
