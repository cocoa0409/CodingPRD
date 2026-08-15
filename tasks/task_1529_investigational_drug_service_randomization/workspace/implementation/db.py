"""In-memory data store. All state wiped on process restart."""

import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.studies = {}
        self.sites = {}
        self.staff = {}
        self.lots = {}
        self.kits = {}
        self.temperature_logs = {}
        self.excursions = {}
        self.subjects = {}
        self.slots = {}
        self.dispensing_records = {}
        self.returns = {}
        self.destruction_records = {}
        self.unblinding_requests = {}
        self.monitor_visits = {}
        self.fee_schedules = {}
        # resupply sequence per lot_id: next 1-based N for RS-<lot_number>-<N>
        self.resupply_seq = {}
        # logical clock; default exactly 2026-08-01T00:00:00Z
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


store = Store()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Real wall-clock timestamp for meta.api_request_timestamp (3 fractional digits)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def clock_iso():
    """Logical clock as ISO 8601 with Z suffix."""
    dt = store.clock
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp_created(obj):
    ts = clock_iso()
    obj["created_at"] = ts
    obj["updated_at"] = ts
    obj["version"] = 1
    return obj


def touch(obj):
    obj["updated_at"] = clock_iso()
    obj["version"] = obj.get("version", 1) + 1
    return obj
