"""In-memory data store. All state lives here, in plain dicts keyed by id.

Every boot starts empty — no seeding, no preload. The test harness builds all
preconditions through the declared API surface.
"""
import uuid
from datetime import datetime, timezone


class DB:
    def __init__(self):
        # Each is a dict {id: entity_dict}
        self.facilities = {}
        self.owners = {}
        self.pets = {}
        self.vaccination_records = {}
        self.runs = {}
        self.reservations = {}
        self.run_assignments = {}
        self.addons = {}
        self.packages = {}
        self.package_redemptions = {}


db = DB()


def reset():
    global db
    db = DB()


def new_id():
    """Server-minted UUID with no type prefix."""
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC timestamp with three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
