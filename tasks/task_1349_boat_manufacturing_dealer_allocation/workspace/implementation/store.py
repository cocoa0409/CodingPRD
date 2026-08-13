"""In-memory data store and logical clock.

PRD §2.5: the logical clock starts at exactly 2026-08-01T00:00:00Z and never
falls back to wall-clock time. All timestamps derive from this clock.
The store starts empty on every boot — no seed data.
"""
import uuid
from datetime import datetime, date, timezone
from decimal import Decimal, ROUND_HALF_UP
from calendar import monthrange


# ---------------------------------------------------------------- clock
class LogicalClock:
    def __init__(self):
        # Startup default: exactly 2026-08-01T00:00:00Z (PRD §2.5)
        self._now = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


CLOCK = LogicalClock()

# ---------------------------------------------------------------- store
DB = {
    'models': {},
    'options': {},
    'dealers': {},
    'shows': {},
    'runs': {},
    'slots': {},
    'orders': {},
    'lines': {},
    'hulls': {},
    'advances': {},
    'registrations': {},
    'claims': {},
    'campaigns': {},
    'notices': {},
}

_SEQ = [0]


def next_seq():
    _SEQ[0] += 1
    return _SEQ[0]


# ---------------------------------------------------------------- time fmt
def fmt_dt(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-08-01T00:00:00.000Z"""
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + '%03dZ' % (dt.microsecond // 1000)


def parse_dt(s):
    """Lenient ISO-8601 datetime parse -> aware UTC datetime, or None."""
    if not isinstance(s, str):
        return None
    t = s.strip()
    if t.endswith('Z') or t.endswith('z'):
        t = t[:-1] + '+00:00'
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    if not isinstance(s, str):
        return None
    try:
        return date.fromisoformat(s.strip())
    except ValueError:
        return None


def add_months(d, months):
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    day = min(d.day, monthrange(y, m)[1])
    return date(y, m, day)


# ---------------------------------------------------------------- money
def rhu(x):
    """Round half up to integer cents (PRD §2.6)."""
    return int(Decimal(x).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------- records
def new_rec(fields):
    """Create a primary resource record with common fields (PRD §2.4)."""
    now = CLOCK.now()
    rec = dict(fields)
    rec['id'] = str(uuid.uuid4())
    rec['created_at'] = fmt_dt(now)
    rec['updated_at'] = fmt_dt(now)
    rec['version'] = 1
    rec['_cts'] = now
    rec['_seq'] = next_seq()
    return rec


def touch(rec):
    """Every mutation refreshes updated_at and increments version (PRD §2.4/§2.8)."""
    rec['updated_at'] = fmt_dt(CLOCK.now())
    rec['version'] += 1


def serialize(rec):
    return {k: v for k, v in rec.items() if not k.startswith('_')}


# ---------------------------------------------------------------- derived
PIPELINE_STATES = {'ALLOCATED', 'COMMITTED', 'IN_PRODUCTION', 'DELIVERED'}
RESERVED_STATES = {'ALLOCATED', 'COMMITTED', 'IN_PRODUCTION'}


def recount_allocation(dealer_id):
    """allocation_used: orders in ALLOCATED/COMMITTED/IN_PRODUCTION/DELIVERED."""
    return sum(1 for o in DB['orders'].values()
               if o['dealer_id'] == dealer_id and o['status'] in PIPELINE_STATES)


def recompute_reserved(slot_id):
    """reserved_hours: production_hours of orders in pipeline-on-slot states."""
    return sum(o['production_hours'] for o in DB['orders'].values()
               if o['slot_id'] == slot_id and o['status'] in RESERVED_STATES)


def recompute_utilized(dealer_id):
    """floor_plan_utilized_cents: sum of outstanding principal over OPEN advances."""
    return sum(a['outstanding_principal_cents'] for a in DB['advances'].values()
               if a['dealer_id'] == dealer_id and a['status'] == 'OPEN')


TIER_RATES = {
    'TIER_STANDARD': Decimal('0.06'),
    'TIER_ELEVATED': Decimal('0.075'),
    'TIER_HIGH': Decimal('0.095'),
}


def tier_for_ratio(ratio):
    # Boundaries: exactly 0.50 -> TIER_ELEVATED; exactly 0.80 -> TIER_HIGH.
    if ratio < Decimal('0.50'):
        return 'TIER_STANDARD'
    if ratio < Decimal('0.80'):
        return 'TIER_ELEVATED'
    return 'TIER_HIGH'


def tier_for(utilized_cents, limit_cents):
    return tier_for_ratio(Decimal(utilized_cents) / Decimal(limit_cents))
