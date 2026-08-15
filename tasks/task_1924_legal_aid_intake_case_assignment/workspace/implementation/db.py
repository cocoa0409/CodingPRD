"""In-memory data store and logical clock.

The store starts completely empty on every boot. No seeding of any kind.
"""
import threading
import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class DB:
    def __init__(self):
        self.lock = threading.RLock()
        self.clock = DEFAULT_CLOCK
        self.seq = 0
        self.clients = {}
        self.applications = {}
        self.conflict_checks = {}
        self.cases = {}
        self.staff = {}
        self.panel_members = {}
        self.referrals = {}
        self.grant_programs = {}
        self.grant_reports = {}
        self.venue_rules = {}
        self.time_entries = {}
        self.surveys = {}
        self.unmet_records = {}
        self.waitlist_entries = {}


db = DB()


def now():
    return db.clock


def next_seq():
    db.seq += 1
    return db.seq


def new_id():
    return str(uuid.uuid4())


def fmt_dt(dt):
    """Serialize a datetime as ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "{}.{:03d}Z".format(dt.strftime("%Y-%m-%dT%H:%M:%S"), dt.microsecond // 1000)
