"""In-memory data store, logical clock, and id/timestamp helpers.

The store starts empty on every boot — nothing is seeded. All entities needed
by any request flow are created through the declared API surface.
"""
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.clearing_banks = {}
        self.accounts = {}
        self.freezes = {}
        self.check_items = {}
        self.hold_decisions = {}
        self.return_events = {}
        self.cases = {}
        self.claims = {}
        self.warranties = {}
        self.notifications = {}
        self.fees = {}
        self.recredits = {}
        self.ledger = {}
        self.seq = 0


store = Store()


class LogicalClock:
    """Single logical clock. Boots at exactly 2026-05-01T00:00:00Z (a Friday).

    The server never consults wall-clock time; the clock advances only via
    POST /_clock/set_current_utc.
    """

    def __init__(self):
        self._now = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


clock = LogicalClock()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    store.seq += 1
    return store.seq


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + f'{dt.microsecond // 1000:03d}Z'


def ts_or_none(dt):
    return fmt_ts(dt) if dt is not None else None


def base_fields():
    """Common system fields for primary resources (id/created_at/updated_at/version)."""
    now = clock.now()
    return {'id': new_id(), 'created_at': now, 'updated_at': now,
            'version': 1, '_seq': next_seq()}


def touch(entity):
    """Refresh updated_at and bump version on a primary resource."""
    entity['updated_at'] = clock.now()
    entity['version'] += 1
