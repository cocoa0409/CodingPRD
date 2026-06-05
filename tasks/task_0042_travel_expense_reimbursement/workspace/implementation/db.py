"""In-memory data store. Starts empty on every boot. No seeding."""
import uuid
from datetime import datetime, timezone


def _now_iso():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


class Store:
    def __init__(self):
        # one dict per entity type, keyed by id
        self.travelers = {}
        self.approvers = {}
        self.travel_policies = {}
        self.per_diem_rates = {}
        self.trip_requests = {}
        self.virtual_cards = {}
        self.expense_reports = {}
        self.expense_lines = {}
        self.receipts = {}
        self.approval_steps = {}

    # ---- id / timestamp helpers ----
    @staticmethod
    def new_id():
        return str(uuid.uuid4())

    @staticmethod
    def now():
        return _now_iso()


# Singleton store. Recreated fresh on every process start; never seeded.
store = Store()


def base_fields(common=True):
    """Return the common identity fields for a new entity.

    common=True  -> full identity quartet (id, created_at, updated_at, version)
    common=False -> immutable reference data (id, created_at only)
    """
    ts = store.now()
    if common:
        return {
            "id": store.new_id(),
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
    return {
        "id": store.new_id(),
        "created_at": ts,
    }


def touch(entity):
    """Bump version and refresh updated_at on a mutable entity."""
    if "version" in entity:
        entity["version"] += 1
        entity["updated_at"] = store.now()
