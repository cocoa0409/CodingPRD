"""In-memory data store. Starts EMPTY on every boot — nothing is ever seeded."""
import uuid

from constants import CLOCK_STARTUP_ISO
from timeutil import parse_iso


class Store:
    def __init__(self):
        self.online_services = {}
        self.determination_evidence = {}
        self.age_screens = {}
        self.parental_notices = {}
        self.activities = {}
        self.consent_requests = {}
        self.child_data_records = {}
        self.parental_rights_requests = {}
        self.third_party_integrations = {}
        self.retention_schedules = {}
        self.safe_harbor_programs = {}
        self.safe_harbor_assessments = {}
        self._seq = 0
        self.current_utc = parse_iso(CLOCK_STARTUP_ISO)

    def next_seq(self):
        self._seq += 1
        return self._seq

    @staticmethod
    def new_id():
        return str(uuid.uuid4())


db = Store()


def now():
    """The logical clock instant (PRD §2.4) — never real wall-clock time."""
    return db.current_utc


def touch(row):
    """Record an accepted mutation of a resource: bump version, refresh updated_at."""
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = now()
    return row


def by_service(collection, service_id):
    return [r for r in collection.values() if r.get("service_id") == service_id]


def ordered(rows):
    """Default list ordering: created_at ascending (stable on insertion sequence)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
