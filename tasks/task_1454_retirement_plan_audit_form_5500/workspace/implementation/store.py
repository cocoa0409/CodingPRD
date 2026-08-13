"""In-memory data store. Starts completely empty on every boot — no seeding."""
import itertools
import threading
import uuid
from datetime import datetime, timedelta, timezone


def format_ts(t):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-08-01T00:00:00.000Z"""
    return t.strftime('%Y-%m-%dT%H:%M:%S.') + '{:03d}Z'.format(t.microsecond // 1000)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self._seq = itertools.count(1)
        self._last_ts = None
        # Logical clock: fixed startup value, never falls back to wall-clock time.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.engagements = {}
        self.participants = {}
        self.contributions = {}
        self.trust_statements = {}
        self.test_results = {}
        self.assessments = {}
        self.findings = {}
        self.corrective_actions = {}
        self.filings = {}
        self.schedule_entries = {}
        self.fees = {}
        self.extensions = {}
        self.correction_filings = {}

    def next_seq(self):
        return next(self._seq)

    def new_id(self):
        return str(uuid.uuid4())

    def timestamp(self):
        """Wall-clock timestamp for created_at/updated_at; strictly increasing."""
        with self.lock:
            t = datetime.now(timezone.utc)
            if self._last_ts is not None and t <= self._last_ts:
                t = self._last_ts + timedelta(milliseconds=1)
            self._last_ts = t
            return format_ts(t)

    def clock_date(self):
        return self.clock.date()


store = Store()


def base_fields():
    ts = store.timestamp()
    return {
        'id': store.new_id(),
        'created_at': ts,
        'updated_at': ts,
        'version': 1,
        '_seq': store.next_seq(),
    }


def touch(entity):
    """Bump version and updated_at on a mutation (PRD section 2.4)."""
    entity['version'] += 1
    entity['updated_at'] = store.timestamp()


def public(entity):
    """Strip internal keys (prefixed with _) for output."""
    return {k: v for k, v in entity.items() if not k.startswith('_')}
