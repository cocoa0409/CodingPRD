import uuid
import threading

from response import now_iso


class Store:
    """In-memory store. Starts empty on every boot — no seeding."""

    def __init__(self):
        self.lock = threading.RLock()
        self.clients = {}
        self.engagements = {}
        self.scope_estimates = {}
        self.accounts = {}
        self.entries = {}
        self.statements = {}
        self.recon_items = {}
        self.phases = {}
        self.invoices = {}
        self.tax_packages = {}
        self.service_plans = {}
        self.exceptions = {}
        self.completion_reports = {}


db = Store()


def new_id():
    return str(uuid.uuid4())


def stamp_new(record):
    ts = now_iso()
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    return record


def touch(record):
    """A mutation: refresh updated_at and bump version."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1
    return record
