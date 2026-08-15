"""In-memory data store plus the logical clock.

The store starts empty on every boot — no seeding. The logical clock starts at
exactly 2026-08-01T00:00:00Z and only moves via POST /_clock/set_current_utc.
"""
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.suppliers = {}
        self.evaluations = {}
        self.entries = {}
        self.lots = {}
        self.verifications = {}
        self.batches = {}
        self.batch_inputs = {}
        self.temp_logs = {}
        self.haccp_records = {}
        self.corrective_actions = {}
        self.labels = {}
        self.finished_lots = {}
        self.recalls = {}
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.seq = 0

    def next_seq(self):
        self.seq += 1
        return self.seq

    def now(self):
        return self.clock


store = Store()


def new_id():
    return str(uuid.uuid4())


def new_entity(**fields):
    """Create a common-fields entity (id/created_at/updated_at/version)."""
    e = {
        "id": new_id(),
        "_seq": store.next_seq(),
        "_created_dt": store.clock,
        "version": 1,
    }
    e.update(fields)
    return e


def new_append_only(**fields):
    """TemperatureLog / HaccpMonitoringRecord: id + created_at only."""
    e = {
        "id": new_id(),
        "_seq": store.next_seq(),
        "_created_dt": store.clock,
    }
    e.update(fields)
    return e


def touch(entity):
    """Bump version + updated_at on any modification (common-fields entities)."""
    entity["version"] = entity.get("version", 1) + 1
    entity["_updated_dt"] = store.clock
