"""In-memory data store. Fresh and empty on every process boot — no seeding."""
import itertools
from datetime import datetime, timezone

UTC = timezone.utc

# Entity tables keyed by id; the ledger is an append-only list.
STORE = {
    'departments': {},
    'faculty': {},
    'cycles': {},
    'applications': {},
    'reviews': {},
    'plans': {},
    'grants': {},
    'fellowships': {},
    'obligations': {},
    'repayments': {},
    'payments': {},
    'reports': {},
    'ledger': [],
}

# The logical clock: starts at exactly 2026-08-01T00:00:00Z, never wall-clock.
CLOCK = {'now': datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)}

# Monotonic insertion sequence for stable created_at tie-breaking.
SEQ = itertools.count(1)


def clock_now():
    return CLOCK['now']


def touch(res):
    """Stamp a mutation: updated_at + version increment (common-field semantics)."""
    res['updated_at'] = clock_now()
    res['version'] += 1
