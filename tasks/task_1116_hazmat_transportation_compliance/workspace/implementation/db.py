"""In-memory data store, logical clock, and shared time helpers.

The store starts empty on every boot — no seeding of any kind.
All temporal reasoning uses the logical clock (store.clock), never wall time.
Entity created_at/updated_at are stamped from the logical clock so every
determination is reproducible.
"""

import calendar
import itertools
import uuid
from datetime import datetime, timedelta, timezone

CLOCK_START = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.carriers = {}
        self.security_plans = {}
        self.materials = {}
        self.specs = {}
        self.drivers = {}
        self.training_records = {}
        self.vehicles = {}
        self.shipments = {}
        self.papers = {}
        self.loads = {}
        self.load_items = {}
        self.routes = {}
        self.incidents = {}
        self.invoices = {}
        self.seq = itertools.count(1)
        self.clock = CLOCK_START


store = Store()


def new_id():
    return str(uuid.uuid4())


def parse_dt(value):
    """Parse an ISO 8601 datetime to an aware UTC datetime at second
    granularity. Returns None when the value is not a valid datetime."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def fmt_dt(dt):
    """Format an aware UTC datetime as ISO 8601 with three fractional digits."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def add_years(dt, years):
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:  # Feb 29 -> Feb 28
        return dt.replace(year=dt.year + years, day=28)


def add_months(dt, months):
    m = dt.month - 1 + months
    y = dt.year + m // 12
    m = m % 12 + 1
    day = min(dt.day, calendar.monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=day)


def months_late(expires, clock):
    """Started calendar months strictly after expires up to clock.

    0 while clock <= expires; 1 when clock in (expires, expires+1mo]; +1 for
    each further started month.
    """
    if expires is None or clock <= expires:
        return 0
    n = 1
    while clock > add_months(expires, n):
        n += 1
    return n


def stamp_new(entity):
    """Common system fields for versioned resources."""
    entity["id"] = new_id()
    entity["created_at"] = store.clock
    entity["updated_at"] = store.clock
    entity["version"] = 1
    entity["_seq"] = next(store.seq)


def stamp_new_light(entity):
    """TrainingRecord / LoadItem carry only id + created_at (no OCC)."""
    entity["id"] = new_id()
    entity["created_at"] = store.clock
    entity["_seq"] = next(store.seq)


def touch(entity):
    """A mutation bumps updated_at and (for versioned resources) version."""
    if "version" in entity:
        entity["version"] += 1
        entity["updated_at"] = store.clock


def sort_key(entity):
    return (entity["created_at"], entity["_seq"])


def sweep():
    """Clock-advance side effects: carrier/plan expiry transitions.

    Driver qualification postures are computed lazily on read, so the sweep
    needs no stored refresh for them.
    """
    clock = store.clock
    for c in store.carriers.values():
        exp = c.get("registration_expires_at")
        if c["registration_status"] == "APPROVED_ACTIVE" and exp and clock > exp:
            c["registration_status"] = "EXPIRED"
            touch(c)
    for p in store.security_plans.values():
        if p["status"] == "APPROVED" and clock > p["effective_to"]:
            p["status"] = "EXPIRED"
            touch(p)
