"""In-memory data store, logical clock, and primitive helpers.

Everything lives in process memory only. A fresh process (start.sh re-invocation)
wipes every byte of state. NOTHING is seeded here — the store starts empty and all
entities are built by tests through the declared API surface.
"""

import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# Global constants (scaffold §1.3)
# ---------------------------------------------------------------------------
PREMIER_THRESHOLD_CENTS = 1000000   # $10,000 lifetime net sales
ELITE_THRESHOLD_CENTS = 5000000     # $50,000 lifetime net sales
PREMIER_DISCOUNT_PCT = Decimal("0.03")
ELITE_DISCOUNT_PCT = Decimal("0.05")
MIN_COMMISSION_PCT = Decimal("0.05")
SALES_TAX_PCT = Decimal("0.08")
RESTOCKING_PCT = Decimal("0.10")
PAYOUT_HOLD_DAYS = 1
OFFER_TTL_HOURS = 72
TRAVEL_BUFFER_MINUTES = 60

DEFAULT_CLOCK = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    """Holds every collection plus the logical clock and the ordering sequence."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.sellers = {}
        self.buyers = {}
        self.category_policies = {}
        self.items = {}
        self.listings = {}
        self.offers = {}
        self.sales = {}
        self.payouts = {}
        self.disputes = {}
        self.concierges = {}
        self.vehicles = {}
        self.pickups = {}
        self.clock = DEFAULT_CLOCK
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        """The single source of 'now' for the whole system: the logical clock."""
        return self.clock


db = Store()


# ---------------------------------------------------------------------------
# Identity / timestamp primitives
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def format_iso(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (dt.microsecond // 1000)


def parse_iso(s):
    """Parse an ISO 8601 instant (with 'Z' or offset) into an aware UTC datetime."""
    if not isinstance(s, str) or not s.strip():
        raise ValueError("bad datetime")
    t = s.strip()
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Money helpers (Decimal, round-half-up to whole cents)
# ---------------------------------------------------------------------------
def rhu_cents(dec_value):
    """Round a Decimal to a whole number of cents using round-half-up."""
    return int(Decimal(dec_value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def to_decimal_rate(rate):
    """Convert an input rate (float/int) into a Decimal preserving its literal value."""
    return Decimal(str(rate))


def mul_round(cents, rate):
    """round_half_up(cents * rate) -> whole cents."""
    return rhu_cents(Decimal(int(cents)) * to_decimal_rate(rate))


# ---------------------------------------------------------------------------
# Domain calculations
# ---------------------------------------------------------------------------
GRADE_RANK = {"A": 4, "B": 3, "C": 2, "D": 1}  # A best, D worst


def tier_for(lifetime_net_sales_cents):
    L = lifetime_net_sales_cents
    if L >= ELITE_THRESHOLD_CENTS:
        return "ELITE"
    if L >= PREMIER_THRESHOLD_CENTS:
        return "PREMIER"
    return "STANDARD"


def tier_discount(tier):
    if tier == "PREMIER":
        return PREMIER_DISCOUNT_PCT
    if tier == "ELITE":
        return ELITE_DISCOUNT_PCT
    return Decimal("0")


def locked_commission_rate(base_commission_pct, tier):
    """max(base - tier_discount, MIN_COMMISSION_PCT) as a Decimal."""
    rate = to_decimal_rate(base_commission_pct) - tier_discount(tier)
    if rate < MIN_COMMISSION_PCT:
        rate = MIN_COMMISSION_PCT
    return rate


def is_listable(verdict, condition_grade, listable_min_condition_grade):
    if verdict != "AUTHENTIC":
        return False
    if condition_grade is None or listable_min_condition_grade is None:
        return False
    return GRADE_RANK.get(condition_grade, 0) >= GRADE_RANK.get(listable_min_condition_grade, 0)
