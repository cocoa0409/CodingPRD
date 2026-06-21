"""In-memory data store. All entities are plain dicts keyed by id.

The store starts EMPTY on every boot. Nothing is seeded or preloaded.
"""
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.facilities = {}
        self.units = {}
        self.residents = {}
        self.assessments = {}
        self.care_plans = {}
        self.medication_orders = {}
        self.administrations = {}
        self.move_in_agreements = {}
        self.billing_statements = {}
        self.incident_reports = {}
        self.survey_deficiencies = {}


db = Store()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    # ISO 8601 UTC timestamp with three fractional digits, Z suffix.
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def stamp_create(obj, common_fields=True):
    ts = now_iso()
    obj["id"] = new_id()
    obj["created_at"] = ts
    if common_fields:
        obj["updated_at"] = ts
        obj["version"] = 1
    return obj


def touch(obj):
    """Mark a resource as mutated: refresh updated_at and bump version."""
    obj["updated_at"] = now_iso()
    obj["version"] = obj.get("version", 1) + 1
