"""In-memory data store, logical clock, ID generation."""
import uuid
import random
import string
from datetime import datetime, timezone


CLOCK_DEFAULT = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.shops = {}
        self.shipping_profiles = {}
        self.materials = {}
        self.listings = {}
        self.vacation_periods = {}
        self.orders = {}
        self.reviews = {}
        self.cases = {}
        self.payouts = {}
        self.clock = CLOCK_DEFAULT
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


def new_id():
    """Server-minted UUID with no type prefix (PRD 2.4)."""
    return uuid.uuid4().hex


def new_request_id():
    """api_request_id: 'req_' + 20 random alphanum."""
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(alphabet, k=20))


def now():
    """Read the logical clock (does not advance)."""
    return store.clock


def set_clock(dt):
    store.clock = dt


def fmt_ts(dt):
    """ISO 8601 UTC with three fractional digits, trailing Z."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    """Parse ISO 8601 timestamp. Accepts trailing Z or +00:00."""
    if not isinstance(s, str):
        raise ValueError("expected string timestamp")
    v = s
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def stamp_common(record):
    """Fill id, created_at, updated_at, version for a fresh record."""
    t = now()
    record["id"] = new_id()
    record["created_at"] = t
    record["updated_at"] = t
    record["version"] = 1
    record["_seq"] = store.next_seq()
    return record


def touch(record):
    """Bump updated_at and version on mutation."""
    record["updated_at"] = now()
    record["version"] = record.get("version", 0) + 1
