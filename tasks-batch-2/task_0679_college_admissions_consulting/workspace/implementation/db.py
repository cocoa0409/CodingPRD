"""In-memory data store. Starts empty on every boot — no seeding."""
import uuid
import threading
from datetime import datetime, timezone


# Server logical clock. Startup default per PRD §2.4.
DEFAULT_CLOCK_ISO = "2026-04-01T00:00:00Z"


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # entity collections keyed by id
        self.counselors = {}
        self.students = {}
        self.contracts = {}
        self.billing_entries = {}
        self.school_list_items = {}
        self.applications = {}
        self.application_tasks = {}
        self.essays = {}
        self.essay_versions = {}
        self.recommendations = {}
        self.activities = {}
        self.scholarships = {}
        self.appointments = {}
        # logical clock, stored as aware UTC datetime
        self.clock = _parse_default_clock()

    def reset(self):
        self.__init__()


def _parse_default_clock():
    return datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)


# single module-level store instance
store = Store()


def new_id():
    return str(uuid.uuid4())


def now_iso_ms():
    """Wall-clock-derived server timestamp for created_at/updated_at and meta.
    ISO 8601 UTC with three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
