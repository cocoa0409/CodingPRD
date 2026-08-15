"""In-memory data store and the server-side logical clock.

The store starts EMPTY on every boot. No seeding of any kind: every entity a
test needs is built through the declared API surface.
"""
import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


class Store:
    def __init__(self):
        self.programs = {}
        self.funders = {}
        self.logic_models = {}
        self.indicators = {}
        self.cycles = {}
        self.participants = {}
        self.consents = {}
        self.instruments = {}
        self.certifications = {}
        self.observations = {}
        self.milestones = {}
        self.audits = {}
        self.findings = {}
        self.reports = {}
        self.engagements = {}
        self.actions = {}
        self.seq = 0
        self.clock_iso = DEFAULT_CLOCK  # raw string, as supplied
        self.clock_dt = parse_dt(DEFAULT_CLOCK)


def parse_dt(s):
    """Parse an ISO-8601 datetime string into an aware UTC datetime."""
    t = s.strip()
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """Format an aware datetime as ISO-8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


db = Store()


def now_dt():
    return db.clock_dt


def now_iso():
    return fmt_dt(db.clock_dt)


def new_id():
    return str(uuid.uuid4())


def next_seq():
    db.seq += 1
    return db.seq


def new_entity(coll, fields):
    """Create an entity with the four common system-managed properties."""
    ts = now_iso()
    ent = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    ent.update(fields)
    coll[ent["id"]] = ent
    return ent
