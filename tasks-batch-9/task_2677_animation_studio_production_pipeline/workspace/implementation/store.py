"""In-memory data store and the logical studio clock.

Storage is process-local dictionaries keyed by id. Nothing is ever seeded:
the store starts completely empty on every boot.
"""
import uuid
from datetime import datetime, timezone

from flask import g

# Before any client sets it, the logical clock reads exactly this instant and it
# never falls back to real wall-clock time (PRD 2.4).
CLOCK_ORIGIN = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = CLOCK_ORIGIN
        self.seq = 0
        self.productions = {}
        self.gates = {}
        self.assets = {}
        self.shots = {}
        self.tasks = {}
        self.rooms = {}
        self.sessions = {}
        self.notes = {}
        self.pools = {}
        self.jobs = {}
        self.partners = {}
        self.packages = {}
        self.deliverables = {}


db = Store()


def now():
    return db.clock


def set_clock(dt):
    db.clock = dt


def next_seq():
    db.seq += 1
    return db.seq


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + ('%03d' % (dt.microsecond // 1000)) + 'Z'


def parse_dt(value):
    """Parse an ISO 8601 timestamp. Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith('Z') or raw.endswith('z'):
        raw = raw[:-1] + '+00:00'
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def base_row():
    return {
        'id': new_id(),
        'created_at': db.clock,
        'updated_at': db.clock,
        'version': 1,
        '_seq': next_seq(),
    }


def touch(row):
    """Refresh updated_at and advance version by exactly 1 per request per row.

    A single accepted request counts as one mutation of a row even when several
    cascade steps of that request touch it.
    """
    row['updated_at'] = db.clock
    touched = getattr(g, '_touched', None)
    if touched is None:
        row['version'] += 1
        return
    if row['id'] not in touched:
        touched.add(row['id'])
        row['version'] += 1


def created_key(row):
    return (row['created_at'], row['_seq'])


def by_created(rows):
    return sorted(rows, key=created_key)


def common_out(row):
    return {
        'id': row['id'],
        'created_at': iso(row['created_at']),
        'updated_at': iso(row['updated_at']),
        'version': row['version'],
    }
