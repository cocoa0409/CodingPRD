"""In-memory data store and logical clock.

Storage is process-local Python dictionaries only.  Nothing is persisted and
NOTHING is ever seeded: every entity is created through a declared endpoint.
"""
import copy
import threading
import uuid
from datetime import datetime, timedelta, timezone

# The logical clock's startup value, pinned by PRD 2.4.
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

COLLECTIONS = (
    "requesters",
    "staff",
    "requests",
    "video_assets",
    "responsive_records",
    "exemption_claims",
    "redaction_tasks",
    "depicted_individuals",
    "fee_estimates",
    "fee_ledger_entries",
    "litigation_holds",
    "denial_letters",
    "release_packages",
)

LOCK = threading.RLock()


def parse_dt(value):
    """Parse an ISO-8601 instant.  Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fmt_dt(value):
    """ISO-8601 UTC with exactly three fractional digits."""
    if value is None:
        return None
    if isinstance(value, str):
        value = parse_dt(value)
        if value is None:
            return None
    value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (value.microsecond // 1000)


def add_days(value, days):
    """Whole days added to an instant; time-of-day preserved exactly."""
    return value + timedelta(days=int(days))


def new_id():
    return str(uuid.uuid4())


class Store(object):
    def __init__(self):
        self.data = {name: {} for name in COLLECTIONS}
        self.clock = parse_dt(CLOCK_DEFAULT)
        self._seq = 0

    # -- clock ------------------------------------------------------------
    def now(self):
        return self.clock

    def now_str(self):
        return fmt_dt(self.clock)

    def set_clock(self, value):
        self.clock = value

    # -- rows -------------------------------------------------------------
    def next_seq(self):
        self._seq += 1
        return self._seq

    def col(self, name):
        return self.data[name]

    def get(self, name, row_id):
        if not isinstance(row_id, str):
            return None
        return self.data[name].get(row_id)

    def all(self, name):
        """Every row of a collection in created_at ASC (insertion) order."""
        return sorted(self.data[name].values(), key=lambda row: row["_seq"])

    def insert(self, name, row, common=True):
        row["id"] = row.get("id") or new_id()
        row["_seq"] = self.next_seq()
        row["created_at"] = self.now_str()
        if common:
            row["updated_at"] = row["created_at"]
            row["version"] = 1
        self.data[name][row["id"]] = row
        return row

    # -- snapshot / rollback ---------------------------------------------
    def snapshot(self):
        return (copy.deepcopy(self.data), self.clock, self._seq)

    def restore(self, snap):
        self.data, self.clock, self._seq = snap[0], snap[1], snap[2]


store = Store()
