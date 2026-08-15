"""In-memory data store. Fresh on every boot — no seeding."""
import threading
import uuid
from datetime import datetime, timezone, timedelta


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.programs = {}
        self.students = {}
        self.instruments = {}
        self.instrument_assignments = {}
        self.uniforms = {}
        self.uniform_assignments = {}
        self.cleaning_batches = {}
        self.arrangements = {}
        self.events = {}
        self.trips = {}
        self.trip_enrollments = {}
        self.payments = {}
        self.fundraisers = {}
        self.auditions = {}
        self.audition_entries = {}
        self.chair_placements = {}
        self.truck_charters = {}
        self.truck_loads = {}
        # logical clock
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def reset(self):
        self.__init__()


store = Store()


def new_id():
    return str(uuid.uuid4())


def now():
    return store.clock


def now_iso():
    return iso(store.clock)


def iso(dt):
    """ISO 8601 UTC with 3 fractional digits, Z suffix."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(s):
    """Parse an ISO8601 datetime string to aware datetime."""
    if s is None:
        return None
    if isinstance(s, datetime):
        return s.astimezone(timezone.utc)
    if not isinstance(s, str):
        raise ValueError("not a datetime string")
    v = s.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def ceil_div(a, b):
    return -(-a // b)


def days_ceil(later, earlier):
    """Ceil of whole days between two datetimes."""
    delta = (later - earlier).total_seconds()
    if delta <= 0:
        return 0
    return ceil_div(int(delta * 1_000_000), 86400 * 1_000_000)


def days_floor(later, earlier):
    delta = (later - earlier).total_seconds()
    return int(delta // 86400)
