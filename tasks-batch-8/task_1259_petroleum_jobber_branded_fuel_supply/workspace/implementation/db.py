"""In-memory data store. Empty at every boot; nothing is ever seeded."""
import uuid
from datetime import datetime, timezone

COLLECTIONS = [
    'products', 'stations', 'agreements', 'postings', 'tanks', 'trucks',
    'drops', 'meters', 'losses', 'recons', 'invoices', 'drafts', 'taxes',
    'audits',
]

STORE = {name: {} for name in COLLECTIONS}

_seq_counter = [0]


def next_seq():
    _seq_counter[0] += 1
    return _seq_counter[0]


def new_id():
    return uuid.uuid4().hex


# ---------------------------------------------------------------------------
# Logical clock: starts at exactly 2026-05-01T00:00:00Z, advances only via
# POST /api/_clock/set_current_utc. Never wall-clock.
# ---------------------------------------------------------------------------
_CLOCK = {'now': datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)}


def clock_now():
    return _CLOCK['now']


def set_clock(dt):
    _CLOCK['now'] = dt


def clock_date_str():
    return _CLOCK['now'].date().isoformat()


def wall_now():
    return datetime.now(timezone.utc)


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits (metadata stamps)."""
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + '{:03d}Z'.format(
        dt.microsecond // 1000)


def fmt_clock(dt):
    """Canonical logical-clock ISO 8601 UTC (trailing fractional zeros cut)."""
    base = dt.strftime('%Y-%m-%dT%H:%M:%S')
    if dt.microsecond:
        frac = '{:06d}'.format(dt.microsecond).rstrip('0')
        return base + '.' + frac + 'Z'
    return base + 'Z'


def stamp_new(rec):
    """Apply common system fields to a freshly created record."""
    ts = fmt_ts(wall_now())
    rec['created_at'] = ts
    rec['updated_at'] = ts
    rec['version'] = 1
    rec['_seq'] = next_seq()
    return rec


def touch(rec):
    """Refresh updated_at and bump version on a mutated record."""
    rec['updated_at'] = fmt_ts(wall_now())
    rec['version'] += 1


def get_or_404(collection, rid, err):
    from errors import ApiError
    rec = STORE[collection].get(rid)
    if rec is None:
        raise ApiError(err, 404, 'Resource not found: {}'.format(rid))
    return rec
