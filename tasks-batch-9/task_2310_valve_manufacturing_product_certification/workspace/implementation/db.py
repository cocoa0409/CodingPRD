"""In-memory store. Starts completely empty on every boot — nothing is seeded."""

import uuid
from datetime import datetime, timezone


def iso_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return iso_ms(datetime.now(timezone.utc))


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.valve_models = {}
        self.foundries = {}
        self.qualifications = {}
        self.heat_lots = {}
        self.components = {}
        self.valve_units = {}
        self.test_records = {}
        self.actuator_packages = {}
        self.licenses = {}
        self.orders = {}
        self._seq = 0
        # The logical works clock: fixed start on a fresh system (PRD 2.5).
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def new_row(extra=None):
    """Create a row carrying the common server-managed properties (PRD 2.4)."""
    row = {
        "id": new_id(),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    if extra:
        row.update(extra)
    return row


def touch(row):
    """Register a mutation of a row: refresh updated_at, increment version."""
    row["updated_at"] = now_iso()
    row["version"] = row.get("version", 1) + 1
    return row


def sort_rows(rows):
    return sorted(rows, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))


def public(row, fields):
    return {f: row.get(f) for f in fields}


def clock_now():
    return db.clock


def clock_iso():
    return iso_ms(db.clock)
