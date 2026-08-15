"""In-memory data store. Starts empty on every boot; no seeding."""
import itertools
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.sign_up_periods = {}
        self.runs = {}
        self.operators = {}
        self.bid_entries = {}
        self.extra_board_slots = {}
        self.daily_assignments = {}
        self.absence_cases = {}
        self.pay_records = {}
        self.vacation_slots = {}
        self.grievance_cases = {}
        self.seq = itertools.count(1)


db = Store()


def now_iso():
    """ISO 8601 UTC timestamp with three fractional digits, e.g. 2025-05-24T10:30:00.123Z."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


def mint():
    """Base system fields for a new entity: id, created_at, updated_at, version=1."""
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next(db.seq),
    }


def touch(entity):
    """Every mutation refreshes updated_at and increments version by exactly one."""
    entity["updated_at"] = now_iso()
    entity["version"] += 1


def ser(entity):
    """Serialize: strip internal bookkeeping keys."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}
