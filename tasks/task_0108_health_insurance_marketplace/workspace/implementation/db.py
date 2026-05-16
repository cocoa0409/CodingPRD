"""In-memory data store for all entities."""

import threading
import uuid

from clock import clock


class DataStore:
    def __init__(self):
        self.lock = threading.RLock()
        self.applications = {}        # id -> dict
        self.household_members = {}   # id -> dict
        self.income_records = {}      # id -> dict
        self.insurers = {}            # id -> dict
        self.plans = {}               # id -> dict
        self.plan_variants = {}       # id -> dict
        self.sep_events = {}          # id -> dict
        self.enrollments = {}         # id -> dict
        self.premium_invoices = {}    # id -> dict

    def reset(self):
        with self.lock:
            self.applications.clear()
            self.household_members.clear()
            self.income_records.clear()
            self.insurers.clear()
            self.plans.clear()
            self.plan_variants.clear()
            self.sep_events.clear()
            self.enrollments.clear()
            self.premium_invoices.clear()


db = DataStore()


def new_id() -> str:
    """Server-minted UUID with no type prefix."""
    return str(uuid.uuid4())


def now_iso() -> str:
    return clock.now_iso()


def stamp_created(record: dict, versioned: bool = True) -> dict:
    """Stamp id, created_at, and (if versioned) updated_at, version on a new record."""
    if not record.get("id"):
        record["id"] = new_id()
    ts = now_iso()
    record["created_at"] = ts
    if versioned:
        record["updated_at"] = ts
        record["version"] = 1
    return record


def bump_version(record: dict) -> dict:
    """Bump version and refresh updated_at."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 0) + 1
    return record
