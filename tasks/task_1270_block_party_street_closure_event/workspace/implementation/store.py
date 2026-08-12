"""In-memory data store, logical clock, id and timestamp generation.

Storage is process-local dicts keyed by id. No disk persistence of any kind.
The store starts empty on every boot; nothing is seeded.
"""
import uuid
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=UTC)


class Store:
    def __init__(self):
        self.clock = DEFAULT_CLOCK
        self.organizers = {}
        self.segments = {}
        self.petitions = {}
        self.signatures = {}
        self.applications = {}
        self.tcps = {}
        self.sound_plans = {}
        self.insurance = {}
        self.stocks = {}
        self.reservations = {}
        self.pools = {}
        self.contributions = {}
        self.deposits = {}
        self.charges = {}
        self.reports = {}
        self._last_ts = None
        self._seq = 0


db = Store()


def new_id():
    return str(uuid.uuid4())


def now():
    """The logical clock. Never falls back to wall-clock time."""
    return db.clock


def tick():
    """Monotonic event timestamp derived from the logical clock.

    Guarantees strictly increasing created_at/updated_at values within the
    process so created_at ordering (e.g. the stock selector tie-break) is
    always well defined even when the logical clock is not advanced.
    """
    t = db.clock
    if db._last_ts is not None and t <= db._last_ts:
        t = db._last_ts + timedelta(milliseconds=1)
    db._last_ts = t
    return t


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(UTC)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + '%03dZ' % (dt.microsecond // 1000)


def entity(**kw):
    """Create a resource dict with common system fields (id/created_at/updated_at/version)."""
    e = {'id': new_id()}
    e.update(kw)
    t = tick()
    e['created_at'] = t
    e['updated_at'] = t
    e['version'] = 1
    db._seq += 1
    e['_seq'] = db._seq
    return e


def touch(e):
    """Record a mutation: refresh updated_at and bump version (where carried)."""
    e['updated_at'] = tick()
    if 'version' in e:
        e['version'] += 1


def sort_key(e):
    return (e['created_at'], e['_seq'])
