"""In-memory data store. No persistence, no seeding — every collection starts
empty on every fresh boot (per-test-server isolation). Tests build all state via
the API surface.
"""
import uuid

from response import now_iso


class DB:
    def __init__(self):
        # Each is a dict keyed by id.
        self.calibration_standards = {}
        self.calibration_vendors = {}
        self.instruments = {}
        self.calibration_events = {}
        self.measurement_points = {}
        self.certificates = {}
        self.impacts = {}
        self.affected_products = {}
        self.gage_rr_studies = {}
        self.gage_rr_trials = {}
        # Singleton logical clock — PRD §2.4: boots at current_epoch == 0.
        self.clock = {
            "id": str(uuid.uuid4()),
            "created_at": now_iso(),
            "current_epoch": 0,
        }


db = DB()


def new_id():
    return str(uuid.uuid4())


def common_fields():
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


def touch(entity):
    """Refresh updated_at and bump version (PRD §2.5)."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity["version"] + 1
