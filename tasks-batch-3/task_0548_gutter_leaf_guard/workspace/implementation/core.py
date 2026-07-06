"""In-memory store, envelope helpers, and calculation rules for the
Gutter Leaf-Guard API. The store starts empty on every boot."""

import math
import random
import string
import uuid
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# Constants (from SCAFFOLD §1.3 calculations + PRD §3)
# ---------------------------------------------------------------------------
TIER1_MAX_FEET = 200
TIER2_MAX_FEET = 400
TIER1_MULT = Decimal("1.00")
TIER2_MULT = Decimal("0.95")
TIER3_MULT = Decimal("0.90")
DOWNSPOUT_UNIT_CENTS = 12000

CAP_TIER1_MAX_CENTS = 500000
CAP_TIER2_MAX_CENTS = 1000000
CAP_TIER1 = Decimal("0.10")
CAP_TIER2 = Decimal("0.15")
CAP_TIER3 = Decimal("0.20")

FEET_PER_CREW_DAY = 150
DEPOSIT_PCT = Decimal("0.10")

REFERRAL_PCT = Decimal("0.03")
REFERRAL_MAX_CENTS = 50000

REMEDIATION_BASE = {"CLOG": 15000, "OVERFLOW": 30000, "DETACHMENT": 60000}
REMEDIATION_CENTS_PER_FOOT = Decimal("200")

NO_SHOW_LIMIT = 2
QUOTE_VALIDITY_DAYS = 30
MIN_FINANCE_AMOUNT_CENTS = 100000
FINANCE_MAX_CENTS = 5000000
TRAVEL_BUFFER = timedelta(minutes=30)  # TRAVEL_BUFFER_MIN (unspecified numerically in spec)

DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"

# ---------------------------------------------------------------------------
# In-memory store (empty at boot — no seeding)
# ---------------------------------------------------------------------------
products = {}
sales_reps = {}
crews = {}
leads = {}
appointments = {}
quotes = {}
financing_plans = {}
jobs = {}
warranty_claims = {}
referrals = {}

clock = {"now": None}   # set in reset()
weather = {}            # "YYYY-MM-DD" -> "CLEAR" | "RAIN" | "SEVERE"


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def parse_iso(s):
    if not isinstance(s, str):
        raise ApiError("ERR_VALIDATION", 400, "invalid timestamp")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        raise ApiError("ERR_VALIDATION", 400, "invalid timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_ms(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_wall():
    return datetime.now(timezone.utc)


def now_iso():
    return iso_ms(now_wall())


def parse_date(s):
    if not isinstance(s, str):
        raise ApiError("ERR_VALIDATION", 400, "invalid date")
    try:
        return date.fromisoformat(s.strip())
    except ValueError:
        raise ApiError("ERR_VALIDATION", 400, "invalid date")


def clock_now():
    return clock["now"]


# ---------------------------------------------------------------------------
# Money / numeric helpers
# ---------------------------------------------------------------------------
def D(x):
    return Decimal(str(x))


def rhu(x):
    """round half up to a whole integer (cents)."""
    return int(D(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Envelope / id helpers
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def gen_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def make_meta(pagination=None):
    m = {"api_request_id": gen_request_id(), "api_request_timestamp": now_iso()}
    if pagination:
        m.update(pagination)
    return m


def stamp_common(entity):
    ts = now_iso()
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    return entity


def touch(entity):
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


def reset():
    products.clear(); sales_reps.clear(); crews.clear(); leads.clear()
    appointments.clear(); quotes.clear(); financing_plans.clear(); jobs.clear()
    warranty_claims.clear(); referrals.clear(); weather.clear()
    clock["now"] = parse_iso(DEFAULT_CLOCK_ISO)


reset()


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def tier_mult(feet):
    f = D(feet)
    if f < TIER1_MAX_FEET:
        return TIER1_MULT
    if f < TIER2_MAX_FEET:
        return TIER2_MULT
    return TIER3_MULT


def discount_cap(subtotal_cents):
    if subtotal_cents < CAP_TIER1_MAX_CENTS:
        return CAP_TIER1
    if subtotal_cents < CAP_TIER2_MAX_CENTS:
        return CAP_TIER2
    return CAP_TIER3


def price_quote(product, feet, color, downspout_count, discount_pct):
    """Return (subtotal_cents, discount_cents, total_cents) per §3.4.
    Round-per-line then sum. Discount cap keyed on subtotal (pre-discount)."""
    f = D(feet)
    tr = D(product["base_rate_cents_per_foot"]) * tier_mult(feet)  # exact, unrounded
    gutter_line = rhu(f * tr)
    if color in (product.get("premium_colors") or []):
        color_line = rhu(f * D(product.get("color_surcharge_cents_per_foot", 0) or 0))
    else:
        color_line = 0
    downspout_line = int(downspout_count) * DOWNSPOUT_UNIT_CENTS
    subtotal = gutter_line + color_line + downspout_line

    cap = discount_cap(subtotal)
    effective = min(D(discount_pct), cap)
    discount = rhu(D(subtotal) * effective)
    total = subtotal - discount
    return subtotal, discount, total


def compute_financing(plan_type, apr_bps, term_months, principal_cents):
    """Return (monthly_payment_cents, total_cost_cents) per §3.6 (round per
    installment, then multiply)."""
    if plan_type == "DEFERRED_INTEREST":
        monthly = rhu(D(principal_cents) / D(term_months))
        total = principal_cents
    else:  # AMORTIZED
        r = (D(apr_bps) / D(10000)) / D(12)
        if r == 0:
            monthly = rhu(D(principal_cents) / D(term_months))
        else:
            factor = D(1) - (D(1) + r) ** (-int(term_months))
            exact = D(principal_cents) * r / factor
            monthly = rhu(exact)
        total = monthly * int(term_months)
    return monthly, total


def compute_install_days(feet):
    return int(math.ceil(D(feet) / D(FEET_PER_CREW_DAY)))


def compute_deposit(total_cents):
    return rhu(D(total_cents) * DEPOSIT_PCT)


def compute_referral_payout(referee_total_cents):
    return min(rhu(D(referee_total_cents) * REFERRAL_PCT), REFERRAL_MAX_CENTS)


def compute_remediation(issue_type, feet):
    base = REMEDIATION_BASE[issue_type]
    return base + rhu(D(feet) * REMEDIATION_CENTS_PER_FOOT)
