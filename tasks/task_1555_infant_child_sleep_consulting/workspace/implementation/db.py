"""In-memory data store and logical clock. The store starts empty on every
boot — no seeding, no external persistence."""
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.consultants = {}
        self.families = {}
        self.cases = {}
        self.questionnaires = {}
        self.plans = {}
        self.packages = {}
        self.logs = {}
        self.sessions = {}
        self.messages = {}
        self.refunds = {}
        self.courses = {}
        self.enrollments = {}
        # Logical clock: startup default is exactly 2026-08-01T00:00:00Z and
        # never falls back to wall-clock time.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.seq = 0  # monotonic insertion counter (stable ordering tiebreak)


store = Store()


def new_id():
    return str(uuid.uuid4())


def now():
    return store.clock


def fmt_dt(dt):
    """Render a datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + '%03dZ' % (dt.microsecond // 1000)


def fmt_date(d):
    return d.isoformat() if d is not None else None


def base_fields():
    t = now()
    return {'id': new_id(), 'created_at': t, 'updated_at': t, 'version': 1}


def register(collection, entity):
    store.seq += 1
    entity['_seq'] = store.seq
    collection[entity['id']] = entity
    return entity


def touch(entity):
    entity['updated_at'] = now()
    entity['version'] += 1
