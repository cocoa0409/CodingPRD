"""In-memory data store and logical clock.

All state lives in module-level dicts keyed by id. Nothing is persisted to
disk, so every process boot (every `bash start.sh`) starts with an empty
store. No seeding of any entity happens here.
"""
import uuid
from datetime import datetime, timedelta, timezone


class _Store:
    def __init__(self):
        self.bases = {}
        self.routes = {}
        self.seasons = {}
        self.aircraft = {}
        self.pilots = {}
        self.duty_days = {}
        self.flights = {}
        self.bookings = {}
        self.passengers = {}
        self.credits = {}
        self.weather_observations = {}
        self.complaints = {}
        # Internal (non-entity) ledger of credit applications:
        # each entry {booking_id, credit_id, amount_cents}
        self.credit_applications = []
        # Logical clock: starts exactly at 2026-08-01T00:00:00Z and only
        # advances via POST /_clock/set_current_utc. Never wall-clock.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        # Monotonic insertion counter for deterministic tie-breaking where
        # created_at timestamps tie under the frozen logical clock.
        self.seq = 0


db = _Store()


def now():
    return db.clock


def set_clock(dt):
    db.clock = dt


def next_seq():
    db.seq += 1
    return db.seq


def new_id():
    return str(uuid.uuid4())


def new_entity():
    """Common fields: id, created_at, updated_at, version (starts at 1)."""
    t = now()
    return {
        'id': new_id(),
        'created_at': t,
        'updated_at': t,
        'version': 1,
        '_seq': next_seq(),
    }


def touch(ent):
    """Every mutation increments version and refreshes updated_at."""
    ent['version'] = ent.get('version', 1) + 1
    ent['updated_at'] = now()


def fmt_ts(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + f'{dt.microsecond // 1000:03d}Z'


def parse_datetime(value):
    """Parse an ISO 8601 datetime string; naive values treated as UTC."""
    if not isinstance(value, str):
        raise ValueError('not a string')
    text = value.strip()
    if text.endswith(('Z', 'z')):
        text = text[:-1] + '+00:00'
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse a YYYY-MM-DD date string."""
    if not isinstance(value, str):
        raise ValueError('not a string')
    return datetime.strptime(value.strip(), '%Y-%m-%d').date()


def add_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)
