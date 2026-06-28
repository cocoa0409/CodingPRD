"""In-memory data store (PRD §2.4 / §2.6).

All storage is in-memory Python dicts keyed by id. The store starts EMPTY on
every boot — no entity is ever seeded, preloaded, or hardcoded. Tests build all
state via the API surface.
"""
import itertools
import uuid

from clock import clock, format_ts


class Store:
    def __init__(self):
        # One dict per entity type, keyed by id.
        self.payers = {}
        self.patients = {}
        self.consents = {}
        self.care_plans = {}
        self.devices = {}
        self.vitals = {}
        self.alerts = {}
        self.review_tasks = {}
        self.care_activities = {}
        self.billing_periods = {}
        self.line_items = {}
        self.claims = {}
        # Monotonic sequence to provide a deterministic creation order
        # independent of timestamp collisions (PRD ordering tie-breaks).
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    return str(uuid.uuid4())


def stamp_create(record, *, common_fields=True):
    """Set system-managed fields at creation (PRD §2.4).

    Full first-class records carry id, created_at, updated_at, version.
    Lighter records (ConsentRecord, VitalsReading) carry only id, created_at.
    """
    now = format_ts(clock.now())
    record["id"] = new_id()
    record["created_at"] = now
    record["_seq"] = db.next_seq()
    if common_fields:
        record["updated_at"] = now
        record["version"] = 1
    return record


def touch(record):
    """Refresh updated_at and increment version on mutation (PRD §2.4)."""
    record["updated_at"] = format_ts(clock.now())
    record["version"] = record.get("version", 1) + 1
    return record
