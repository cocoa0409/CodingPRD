"""In-memory data store, logical clock, id/seq generation, datetime helpers.

The store starts EMPTY on every boot. Nothing is seeded. Every entity a test
needs is created via the declared API surface.
"""
import uuid
from datetime import datetime, timezone, timedelta

# Logical clock default (§2.4): startup reads exactly 2026-03-01T00:00:00Z.
DEFAULT_CLOCK = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.clock = DEFAULT_CLOCK
        self._seq = 0
        # One dict per collection, keyed by id.
        self.funding_pools = {}
        self.households = {}
        self.applications = {}
        self.income_documents = {}
        self.vendors = {}
        self.utility_accounts = {}
        self.pledges = {}
        self.crisis_benefits = {}
        self.payments = {}
        self.bill_credits = {}
        self.weatherization_referrals = {}

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        return self.clock


db = Store()


# --------------------------------------------------------------------------
# Datetime helpers
# --------------------------------------------------------------------------
def parse_dt(value):
    """Parse an ISO-8601 string into an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a datetime string")
    t = value.strip()
    if not t:
        raise ValueError("empty datetime string")
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_dt(dt):
    """Format an aware datetime as ISO-8601 UTC with exactly 3 fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def now_iso():
    return format_dt(db.now())


def wall_iso():
    return format_dt(datetime.now(timezone.utc))


def add_hours(dt, hours):
    return dt + timedelta(hours=hours)


# --------------------------------------------------------------------------
# Common-field helpers
# --------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def stamp_new(entity):
    """Attach id + common system fields to a freshly created entity dict."""
    now_dt = db.now()
    entity["id"] = new_id()
    entity["created_at"] = format_dt(now_dt)
    entity["updated_at"] = format_dt(now_dt)
    entity["version"] = 1
    entity["_seq"] = db.next_seq()
    entity["_created_dt"] = now_dt
    return entity


def touch(entity):
    """Bump version by 1 and refresh updated_at to the current logical-clock instant."""
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = now_iso()
    return entity


def sort_key(entity):
    """Sort by created_at ascending, with a stable insertion-sequence tie-break."""
    return (entity["_created_dt"], entity["_seq"])


def public(entity):
    """Serialize an entity, stripping internal (underscore-prefixed) fields."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}
