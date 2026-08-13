"""In-memory data store. The store starts empty on every boot — no seeding."""
import itertools
import threading
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.customers = {}
        self.product_models = {}
        self.units = {}
        self.rmas = {}
        self.quotes = {}
        self.repair_lines = {}
        self.parts = {}
        self.failure_codes = {}
        self.depot_bays = {}
        self.loaner_units = {}
        self.loaner_reservations = {}
        self.engineering_escalations = {}
        self.notification_events = {}
        # Logical clock: starts at exactly 2026-08-01T00:00:00Z; never wall-clock.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self._rma_seq = itertools.count(1)

    def next_rma_number(self):
        return "RMA-%06d" % next(self._rma_seq)


store = Store()


def new_id():
    return str(uuid.uuid4())


def now_wall_iso():
    """Real wall-clock timestamp for created_at/updated_at/api_request_timestamp.

    ISO 8601 UTC with three fractional digits.
    """
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def clock_iso():
    """Logical clock timestamp as ISO 8601 UTC with three fractional digits."""
    dt = store.clock
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def clock_now():
    return store.clock


def parse_iso_datetime(s):
    """Parse an ISO 8601 datetime string. Accepts trailing Z."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    text = s.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso_date(s):
    from datetime import date
    if not isinstance(s, str):
        raise ValueError("not a string")
    return date.fromisoformat(s.strip())


def touch(entity):
    """Refresh updated_at and bump version on a mutable entity."""
    entity["updated_at"] = now_wall_iso()
    entity["version"] = entity.get("version", 1) + 1
