"""In-memory data store, logical clock, and id/timestamp helpers.

State is process-local and starts EMPTY on every boot. No seeding.
"""
import uuid
from datetime import datetime, timezone, timedelta

# Logical clock default (PRD 2.8): server startup reads exactly this instant.
CLOCK_DEFAULT = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)


class DB:
    def __init__(self):
        self.reset()

    def reset(self):
        self.plans = {}
        self.providers = {}
        self.members = {}
        self.policies = {}
        self.lasers = {}
        self.claims = {}
        self.funds = {}
        self.checkruns = {}
        self.reimbursements = {}
        self.forms = {}
        self.clock = CLOCK_DEFAULT
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = DB()


def new_id():
    return str(uuid.uuid4())


def fmt_iso(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_dt():
    return db.clock


def now_iso():
    return fmt_iso(db.clock)


def wall_now_iso():
    return fmt_iso(datetime.now(timezone.utc))


def parse_dt(value):
    """Parse an ISO date or datetime string into an aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            dt = datetime.strptime(s[:10], "%Y-%m-%d")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_days(dt, days):
    return dt + timedelta(days=days)


def stamp_new(entity):
    """Attach system-managed common fields on creation."""
    iso = now_iso()
    entity["created_at"] = iso
    entity["updated_at"] = iso
    entity["version"] = 1
    entity["_created_dt"] = db.clock
    entity["_seq"] = db.next_seq()
    return entity


def touch(entity):
    """Record a mutation: refresh updated_at and increment version (PRD 2.4)."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1
    return entity


def sort_key(entity):
    return (entity["_created_dt"], entity["_seq"])
