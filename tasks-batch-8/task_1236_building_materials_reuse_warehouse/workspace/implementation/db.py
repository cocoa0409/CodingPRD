"""In-memory data store and logical clock.

Storage is plain Python dicts keyed by id. The store starts completely empty
on every boot — no seeding, no preloading. All state is built by API calls.
"""
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"


class LogicalClock:
    def __init__(self):
        self.now = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.raw = DEFAULT_CLOCK_ISO

    def set(self, dt, raw):
        self.now = dt
        self.raw = raw


CLOCK = LogicalClock()


def now():
    return CLOCK.now


# ---------------------------------------------------------------------------
# Entity stores (insertion-ordered dicts)
# ---------------------------------------------------------------------------

donors = {}
categories = {}
offers = {}
jobs = {}
screenings = {}
batches = {}
items = {}
zones = {}
markdown_runs = {}
accounts = {}
agreements = {}
sales = {}
sale_lines = {}
receipts = {}
crew_members = {}
assignments = {}
vehicles = {}
appointments = {}
reports = {}


def new_id():
    return str(uuid.uuid4())


def touch(entity):
    """Bump version and refresh updated_at on a mutation (incl. cascades)."""
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = now()


def base_fields():
    """Common system-managed fields for a freshly created resource."""
    ts = now()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}


def lean_fields():
    """HazmatScreening / MarkdownRun / SaleLineItem carry only id+created_at."""
    return {"id": new_id(), "created_at": now()}
