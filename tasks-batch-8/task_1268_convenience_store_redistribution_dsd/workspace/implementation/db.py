"""In-memory data store, logical clock, and record helpers.

Storage is process-local only: plain dicts keyed by id. Nothing is seeded at
startup; every entity is created through the declared API surface.
"""
import itertools
import uuid
from datetime import datetime, timezone

STORE = {
    'retailers': {},
    'products': {},
    'order_guides': {},
    'promo_events': {},
    'retail_price_records': {},
    'delivery_windows': {},
    'fuel_surcharge_rates': {},
    'tax_stamp_supplies': {},
    'delivery_manifests': {},
    'purchase_orders': {},
    'order_lines': {},
    'invoices': {},
    'payments': {},
    'credit_memos': {},
    'delivery_exceptions': {},
    'new_item_requests': {},
}

_seq_counter = itertools.count(1)

# Logical clock: starts at exactly 2026-05-01T00:00:00Z, advances only via
# POST /_clock/set_current_utc. Never falls back to wall-clock time.
_logical_now = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


def next_seq():
    return next(_seq_counter)


def new_id():
    return str(uuid.uuid4())


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + '%03dZ' % (dt.microsecond // 1000)


def wall_now():
    return datetime.now(timezone.utc)


def wall_now_iso():
    return fmt_ts(wall_now())


def logical_now():
    return _logical_now


def logical_now_iso():
    return fmt_ts(_logical_now)


def set_logical_now(dt):
    global _logical_now
    _logical_now = dt.astimezone(timezone.utc)


def new_record(common=True):
    """Fresh system-managed fields. Order lines pass common=False (id + created_at only)."""
    rec = {
        'id': new_id(),
        'created_at': wall_now_iso(),
        '_seq': next_seq(),
    }
    if common:
        rec['updated_at'] = rec['created_at']
        rec['version'] = 1
    return rec


def touch(rec):
    """Refresh updated_at and bump version (when the resource carries one)."""
    if 'updated_at' in rec:
        rec['updated_at'] = wall_now_iso()
    if 'version' in rec:
        rec['version'] = rec['version'] + 1


def public(rec):
    """Strip internal keys (prefixed with _) before serialization."""
    return {k: v for k, v in rec.items() if not k.startswith('_')}
