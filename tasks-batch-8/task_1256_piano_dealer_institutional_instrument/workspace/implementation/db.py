"""In-memory store and the dealer's logical clock.

Storage is process-local dicts keyed by id. The store starts EMPTY on every
boot; nothing is seeded or preloaded. The logical clock defaults to exactly
2026-05-01T00:00:00Z and moves only via the PlatformAdmin clock endpoint.
"""
import uuid

from util import parse_dt, fmt_dt

stores = {
    'consignors': {},
    'customers': {},
    'instruments': {},
    'appraisals': {},
    'bids': {},
    'orders': {},
    'crews': {},
    'jobs': {},
    'technicians': {},
    'plans': {},
    'visits': {},
    'agreements': {},
    'warranties': {},
    'referrals': {},
    'events': {},
}

DEFAULT_CLOCK_ISO = '2026-05-01T00:00:00Z'
_clock = parse_dt(DEFAULT_CLOCK_ISO, 'clock')


def now():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


def base_fields():
    ts = fmt_dt(_clock)
    return {'id': str(uuid.uuid4()), 'created_at': ts, 'updated_at': ts, 'version': 1}


def touch(res):
    """Every mutation refreshes updated_at and increments version by exactly one."""
    res['updated_at'] = fmt_dt(_clock)
    res['version'] += 1
