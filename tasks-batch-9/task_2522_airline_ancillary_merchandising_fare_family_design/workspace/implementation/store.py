"""In-memory data store, logical clock and common resource properties.

The store starts EMPTY on every boot.  Nothing is seeded, preloaded or
hardcoded: every entity is created by an API caller.
"""
import itertools
import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.4: before the clock is ever set it reads exactly this instant and it
# NEVER falls back to real wall-clock time.
DEFAULT_CLOCK_UTC = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.products = {}
        self.families = {}
        self.attributes = {}
        self.flights = {}
        self.segments = {}
        self.channels = {}
        self.publications = {}
        self.bookings = {}
        self.assignments = {}
        self.offers = {}
        self.waivers = {}
        self.revenue = {}
        self.clock = DEFAULT_CLOCK_UTC
        self._counter = itertools.count(1)


db = Store()


def new_id():
    return str(uuid.uuid4())


def seq():
    return next(db._counter)


def now():
    """The logical clock -- the sole source of 'now' for this system."""
    return db.clock


def set_clock(dt):
    db.clock = dt


def iso(dt):
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + '%03dZ' % (dt.microsecond // 1000)


def accounting_period():
    c = db.clock
    return '%04d-%02d' % (c.year, c.month)


def minutes(n):
    return timedelta(minutes=n)


def common_fields():
    """id / created_at / updated_at / version for a freshly created resource."""
    return {
        'id': new_id(),
        'created_at': now(),
        'updated_at': now(),
        'version': 1,
        '_seq': seq(),
    }


def touch(rec):
    """A mutation: refresh updated_at and increment version by exactly 1."""
    rec['updated_at'] = now()
    rec['version'] = rec['version'] + 1


def by_created(rows):
    """Default list ordering: created_at ascending, insertion order for ties."""
    return sorted(rows, key=lambda r: (r['created_at'], r.get('_seq', 0)))
