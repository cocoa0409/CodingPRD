"""In-memory data store. Starts empty on every boot (no seeding)."""
import uuid
from datetime import datetime, timezone

from response import utc_now_iso


class Store:
    def __init__(self):
        # one dict per entity collection, keyed by id
        self.clinics = {}
        self.shifts = {}
        self.machines = {}
        self.stations = {}
        self.patients = {}
        self.orders = {}
        self.standing_slots = {}
        self.sessions = {}
        self.transport_trips = {}
        self.lab_orders = {}
        self.statements = {}
        # logical clinic clock (used for no-show trailing window). None until set.
        # We keep it as a date-capable ISO string; default to wall-clock now.
        self.clock_now = None

    def new_id(self):
        return str(uuid.uuid4())

    def stamp_create(self, record):
        ts = utc_now_iso()
        record["id"] = self.new_id()
        record["created_at"] = ts
        record["updated_at"] = ts
        record["version"] = 1
        return record

    def touch(self, record):
        """Bump version and updated_at on any mutation that changes the resource."""
        record["version"] = record.get("version", 1) + 1
        record["updated_at"] = utc_now_iso()
        return record


db = Store()
