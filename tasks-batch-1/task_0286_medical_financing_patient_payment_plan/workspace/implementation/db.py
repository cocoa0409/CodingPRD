"""In-memory data store + logical clock.

All state lives in module-level dicts keyed by id. NOTHING is seeded at import
time; the store starts empty on every boot and tests build all state via the
declared API surface. start.sh re-invocation wipes every byte of state because
the process restarts from scratch.

Time model (PRD §3 intro, §3.11): the platform runs against a *logical* clock
that test-driving endpoints set/advance. created_at / updated_at and every
system-stamped datetime (promo_start, posted_at, period_*, etc.) use this clock,
so that chronological orderings used by the calculations are driven by the
operator-controlled time, not wall-clock.
"""
import itertools
import uuid
from datetime import datetime, timezone

# --- collections (peer top-level, flat topology) ---
providers = {}
promotional_plans = {}
provider_promotions = {}
credit_applications = {}
patient_accounts = {}
autopay_enrollments = {}
financed_purchases = {}
settlements = {}
payments = {}
billing_statements = {}
refunds = {}

# Monotonic sequence to make created_at strictly ordered even when two entities
# are created at the same logical-clock instant. Used as the final tie-break in
# orderings the PRD pins to created_at.
_seq = itertools.count(1)


class _Clock:
    """Logical clock. Defaults to real UTC now until an operator sets/advances it."""

    def __init__(self):
        self._now = datetime.now(timezone.utc)

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


clock = _Clock()


def new_id():
    # UUID with no type prefix (PRD §2.4).
    return str(uuid.uuid4())


def now_iso():
    """Current logical clock as ISO-8601 UTC with three fractional digits."""
    return iso(clock.now())


def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def next_seq():
    return next(_seq)


def reset():
    """Wipe all state (used only for completeness; process restart is the real wipe)."""
    for coll in (providers, promotional_plans, provider_promotions,
                 credit_applications, patient_accounts, autopay_enrollments,
                 financed_purchases, settlements, payments, billing_statements,
                 refunds):
        coll.clear()
