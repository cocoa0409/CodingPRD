"""In-memory data store + logical clock. No persistence of any kind.

The store starts EMPTY on every boot. No seeding, no preloading, no disk.
"""
import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


def parse_dt(s):
    """Parse an ISO8601 string ('Z' or offset) into an aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class Store:
    def __init__(self):
        self.seasons = {}
        self.clubs = {}
        self.coaches = {}
        self.players = {}
        self.memberships = {}
        self.ledger_entries = {}
        self.meets = {}
        self.pairings = {}
        self.disputes = {}
        self.tournaments = {}
        self.sections = {}
        self.entries = {}
        self.proctor_assignments = {}
        self.bids = {}
        self.rating_events = {}
        self.snapshots = {}
        self.stipends = {}
        self.seq = 0
        self.clock = parse_dt(DEFAULT_CLOCK)


store = Store()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    store.seq += 1
    return store.seq


def clock_now():
    return store.clock


def iso(dt):
    """Format a datetime as ISO8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_date(s):
    """Validate a strict YYYY-MM-DD date string; return datetime.date."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    from datetime import date as _date
    parts = s.split("-")
    if len(parts) != 3 or len(parts[0]) != 4 or len(parts[1]) != 2 or len(parts[2]) != 2:
        raise ValueError("bad date")
    y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
    return _date(y, m, d)


def now_iso():
    return iso(store.clock)
