"""In-memory data store.

Starts EMPTY on every boot. No seeding, no preloaded entities — tests build
all preconditions through the declared API surface.
"""
import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


def now_iso():
    # ISO 8601 UTC with three fractional digits (PRD §2.4).
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


class Store:
    def __init__(self):
        self.parks = {}
        self.pricing_policies = {}
        self.entry_windows = {}
        self.cabanas = {}
        self.lockers = {}
        self.guests = {}
        self.orders = {}
        self.admissions = {}
        self.cabana_rentals = {}
        self.locker_rentals = {}
        self.rain_checks = {}
        # Singleton ClockState. current_utc is None until POST /_clock/set_current_utc.
        self.clock = {
            "id": new_id(),
            "created_at": now_iso(),
            "current_utc": None,
        }


db = Store()


def add_common_fields(record):
    """Attach the full system-managed quartet (PRD §2.4)."""
    ts = now_iso()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    return record


def touch(record):
    """Refresh updated_at and bump version on every mutation (PRD §2.4 / §2.7)."""
    record["updated_at"] = now_iso()
    record["version"] = record["version"] + 1
