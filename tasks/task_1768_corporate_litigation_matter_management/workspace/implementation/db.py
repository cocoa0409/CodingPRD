"""In-memory data store, logical clock, identity and timestamp helpers."""
import random
import string
import uuid
from datetime import datetime, timedelta, timezone


class Store:
    def __init__(self):
        self.staff_users = {}
        self.firms = {}
        self.matters = {}
        self.engagements = {}
        self.budgets = {}
        self.accruals = {}
        self.holds = {}
        self.custodians = {}
        self.vendors = {}
        self.work_orders = {}
        self.deadlines = {}
        self.policies = {}
        self.settlements = {}
        self.payments = {}
        self.matter_seq = 0
        self.seq = 0
        # Logical clock: startup default is exactly 2026-08-01T00:00:00Z and
        # never falls back to wall-clock time.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


store = Store()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    store.seq += 1
    return store.seq


def next_matter_number():
    store.matter_seq += 1
    return "MTR-%04d-%06d" % (store.clock.year, store.matter_seq)


def new_request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def wall_now():
    return datetime.now(timezone.utc)


def fmt_ts(dt):
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def fmt_iso(dt):
    """Canonical ISO 8601 UTC used for logical-clock-stamped domain fields."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = dt.microsecond // 1000
    if ms:
        return base + ".%03dZ" % ms
    return base + "Z"


def parse_dt(value):
    """Parse an ISO 8601 date/datetime string into an aware UTC datetime.

    Returns None when the value is not a parseable ISO 8601 string.
    """
    if not isinstance(value, str) or not value:
        return None
    s = value.strip()
    try:
        if s.endswith(("Z", "z")):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def touch(rec):
    """Bump optimistic-concurrency version and refresh updated_at."""
    rec["version"] = rec.get("version", 0) + 1
    rec["updated_at"] = fmt_ts(wall_now())


def new_common(rec):
    """Stamp common system fields onto a freshly created record."""
    rec["id"] = new_id()
    rec["created_at"] = fmt_ts(wall_now())
    rec["updated_at"] = rec["created_at"]
    rec["version"] = 1
    rec["_seq"] = next_seq()
    return rec
