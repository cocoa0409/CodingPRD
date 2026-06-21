"""In-memory data store. Wiped on every process boot — no seeding."""
import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


def now_ts():
    # ISO 8601 UTC with three fractional digits.
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


class Store:
    def __init__(self):
        self.container_types = {}
        self.contractor_accounts = {}
        self.containers = {}
        self.routes = {}
        self.rental_orders = {}
        self.service_stops = {}
        self.weigh_tickets = {}
        self.street_permits = {}
        self.invoices = {}
        # Single ClockState object (id + created_at + current_date).
        self.clock = None

    def insert_with_common(self, table, record):
        """Stamp id + common fields (created_at/updated_at/version) and store."""
        rid = new_id()
        ts = now_ts()
        record["id"] = rid
        record["created_at"] = ts
        record["updated_at"] = ts
        record["version"] = 1
        table[rid] = record
        return record

    def insert_append_only(self, table, record):
        """Stamp id + created_at only (WeighTicket: no updated_at/version)."""
        rid = new_id()
        record["id"] = rid
        record["created_at"] = now_ts()
        table[rid] = record
        return record

    @staticmethod
    def touch(record):
        """Refresh updated_at and bump version by 1 (a mutation occurred)."""
        record["updated_at"] = now_ts()
        record["version"] = record.get("version", 0) + 1


db = Store()
