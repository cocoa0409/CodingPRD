import uuid
from datetime import datetime, timezone

from clock import format_iso8601_ms


class Store:
    def __init__(self):
        self.cemeteries = {}
        self.sections = {}
        self.gravesites = {}
        self.niches = {}
        self.burial_cases = {}
        self.eligibility_determinations = {}
        self.pre_need_determinations = {}
        self.interment_schedules = {}
        self.marker_orders = {}
        self.military_honors = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    return format_iso8601_ms(datetime.now(timezone.utc))


def base_fields(with_version=True):
    """Common server-managed fields for a freshly created entity."""
    ts = now_iso()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "_seq": db.next_seq(),
    }
    if with_version:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    """Mutation of a versioned resource: bump updated_at and version."""
    if "version" in rec:
        rec["version"] += 1
        rec["updated_at"] = now_iso()
