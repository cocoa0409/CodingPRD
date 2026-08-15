"""In-memory data store and logical clock.

The store starts completely empty on every boot — no seeding, no disk IO.
"""
import uuid
from datetime import datetime, timezone

CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.now = CLOCK_START
        self.seq = 0
        self.employees = {}
        self.boards = {}
        self.slots = {}
        self.jobs = {}
        self.calls = {}
        self.assignments = {}
        self.rest_periods = {}
        self.leave_bids = {}
        self.pay_records = {}
        self.shortages = {}
        # assignment_id -> pay_record_id for the tie-up auto-created DRAFT
        self.auto_pay = {}

    def tick(self):
        self.seq += 1
        return self.seq


store = Store()


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + uuid.uuid4().hex[:24]


def fmt_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO 8601 string to an aware UTC datetime, or return None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def base_record(with_version=True):
    """Common fields: id + created_at; most entities also get updated_at + version."""
    rec = {
        "id": new_id(),
        "created_at": store.now,
        "_seq": store.tick(),
    }
    if with_version:
        rec["updated_at"] = store.now
        rec["version"] = 1
    return rec


def touch(rec):
    rec["updated_at"] = store.now
    rec["version"] = rec.get("version", 1) + 1


def minutes_between(start, end):
    return int((end - start).total_seconds() // 60)


def serialize(rec):
    """Strip internal (_-prefixed) keys and format datetimes as ISO 8601 UTC."""
    out = {}
    for key, value in rec.items():
        if key.startswith("_"):
            continue
        if isinstance(value, datetime):
            out[key] = fmt_dt(value)
        else:
            out[key] = value
    return out
