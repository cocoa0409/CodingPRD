"""In-memory data store and the logical clock.

The store starts empty on every boot. No seeding of any kind.
"""

import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Stores (flat topology; all linkage via FK fields)
# ---------------------------------------------------------------------------

STORES = {
    "practices": {},
    "products": {},
    "usage_profiles": {},
    "orders": {},
    "equipment_sales": {},
    "technicians": {},
    "service_tickets": {},
    "dispatch_jobs": {},
    "coverage_agreements": {},
    "promotions": {},
    "rebate_claims": {},
    "trade_ins": {},
}

# Monotonic insertion counter, used as a stable tertiary sort key.
_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Logical clock — starts at exactly 2026-08-01T00:00:00Z and never falls back
# to wall-clock time on its own.
# ---------------------------------------------------------------------------

_CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = _CLOCK_DEFAULT


def now():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt
