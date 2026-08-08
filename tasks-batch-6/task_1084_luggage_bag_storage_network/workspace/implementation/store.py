"""In-memory data store and shared helpers.

Storage is purely in-memory (Python dicts). Every process boot starts empty;
no entity data is ever seeded at startup.
"""
import random
import string
import uuid
from datetime import datetime, timezone, date, timedelta

CLOCK_START = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.hosts = {}
        self.travelers = {}
        self.plans = {}
        self.locations = {}
        self.bookings = {}
        self.bags = {}
        self.extensions = {}
        self.claims = {}
        self.payouts = {}
        self.ratings = {}
        self.clock = CLOCK_START
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now_iso(self):
        return iso(self.clock)

    def current_date(self):
        return self.clock.date()


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def request_id():
    aln = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(aln, k=20))


def parse_date(s):
    """Parse a YYYY-MM-DD string into a date, or raise ValueError."""
    return date.fromisoformat(s)


def parse_clock(s):
    """Parse an ISO 8601 instant (with optional Z) into an aware datetime."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def base_fields(store):
    t = store.now_iso()
    return {
        "id": new_id(),
        "created_at": t,
        "updated_at": t,
        "version": 1,
        "_seq": store.next_seq(),
    }


def touch(store, entity):
    entity["updated_at"] = store.now_iso()
    entity["version"] = entity.get("version", 1) + 1


def serialize(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}
