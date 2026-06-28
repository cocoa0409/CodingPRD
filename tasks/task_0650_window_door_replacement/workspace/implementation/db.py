"""In-memory data store. All state is wiped on process restart (fresh module import).

NO seeding, NO preloading. Every entity is created by API calls during tests.
"""
import uuid

from clock import clock, format_iso8601


class DB:
    def __init__(self):
        self.homeowners = {}
        self.projects = {}
        self.consultations = {}
        self.openings = {}
        self.quotes = {}
        self.financing_applications = {}
        self.manufacture_orders = {}
        self.crews = {}
        self.install_jobs = {}
        self.permits = {}
        self.service_tickets = {}
        self.referrals = {}


db = DB()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    return format_iso8601(clock.get())


def stamp_create(record):
    """Set system fields on a freshly created record."""
    ts = now_iso()
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    return record


def touch(record):
    """Bump version and refresh updated_at on a mutation (direct or cascaded)."""
    record["updated_at"] = now_iso()
    record["version"] = record["version"] + 1
    return record
