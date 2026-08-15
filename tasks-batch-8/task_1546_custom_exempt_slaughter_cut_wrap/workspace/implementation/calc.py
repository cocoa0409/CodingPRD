"""Logical clock, time arithmetic, and money/weight calculations.

Implements SCAFFOLD.yaml §1.3 (calculation rules) and PRD §2.4-2.6 exactly.
All money is integer cents (round-half-up); weights are pounds at exactly one
decimal (round-half-up); day counts are whole calendar days measured on
logical-clock date boundaries.
"""

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import db
from errors import ERR_INVALID_REQUEST, raise_error

CENT = Decimal("1")
TENTH = Decimal("0.1")

# ---------------------------------------------------------------------------
# Constants (SCAFFOLD calculations[].constants)
# ---------------------------------------------------------------------------
SPECIES = ("BEEF", "HOG", "LAMB", "GOAT")

DEPOSIT_FLAT_PER_HEAD_CENTS = {"BEEF": 15000, "HOG": 7500, "LAMB": 5000, "GOAT": 5000}
AVG_LIVE_WEIGHT_LBS = {"BEEF": Decimal("1200"), "HOG": Decimal("280"),
                       "LAMB": Decimal("130"), "GOAT": Decimal("90")}
DRESS_PCT = {"BEEF": Decimal("0.62"), "HOG": Decimal("0.75"),
             "LAMB": Decimal("0.52"), "GOAT": Decimal("0.50")}
ELEVATED_DEPOSIT_PCT = Decimal("0.50")
SLAUGHTER_FEE_CENTS = {"BEEF": 12000, "HOG": 6000, "LAMB": 4500, "GOAT": 4500}

TIER1_MAX_LBS = Decimal("200")
RATE_A_CENTS_PER_LB = {"BEEF": 95, "HOG": 85, "LAMB": 110, "GOAT": 110}
RATE_B_CENTS_PER_LB = {"BEEF": 85, "HOG": 75, "LAMB": 95, "GOAT": 95}

DEPOSIT_WINDOW_HOURS = 48
MIN_LEAD_DAYS = 14
CANCEL_FULL_REFUND_DAYS = 7
MIN_HANG_DAYS = 3
MAX_GRIND_PCT = 60
FREEZER_CAPACITY_UNITS = 4
FREEZER_UNITS_PER_SHARE = 1
FREE_STORAGE_DAYS = 7
STORAGE_DAILY_CENTS = 500
ABANDON_AFTER_DAYS = 21
ABANDON_SURCHARGE_CENTS = 5000
STRIKE_BLOCK_THRESHOLD = 2

INTENDED_USES = ("OWNER_USE", "RESALE")

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# Time helpers (logical clock)
# ---------------------------------------------------------------------------

def parse_dt(value, field="to_iso8601"):
    """Parse an ISO 8601 datetime string to a naive UTC datetime."""
    if not isinstance(value, str):
        raise_error(ERR_INVALID_REQUEST, f"Field '{field}' must be an ISO 8601 datetime string")
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise_error(ERR_INVALID_REQUEST, f"Field '{field}' is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def parse_date(value, field="date"):
    """Parse a strict YYYY-MM-DD calendar date."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise_error(ERR_INVALID_REQUEST, f"Field '{field}' must be an ISO 8601 date (YYYY-MM-DD)")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise_error(ERR_INVALID_REQUEST, f"Field '{field}' is not a valid calendar date")


def get_now():
    """Current logical instant (naive UTC datetime)."""
    return parse_dt(db.current_utc_iso)


def today():
    return get_now().date()


def fmt_ts(dt):
    """Format a naive UTC datetime as the logical-clock string.

    Matches the clock's own surface form: no fractional part when the instant
    is whole-second ('2026-08-01T00:00:00Z'), three fractional digits
    otherwise.
    """
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_ts():
    return fmt_ts(get_now())


def whole_days_between(dt_from, dt_to):
    """Whole calendar days between two instants, on logical-clock date
    boundaries (PRD §2.4)."""
    return (dt_to.date() - dt_from.date()).days


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------

def dec(value, field):
    """Convert a JSON numeric input to Decimal via str() (exact)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise_error(ERR_INVALID_REQUEST, f"Field '{field}' must be a number")
    return Decimal(str(value))


def decimal_places_ok(d, places):
    quantum = Decimal(1).scaleb(-places)
    return d == d.quantize(quantum, rounding=ROUND_HALF_UP)


def round_cents(d):
    """Round a Decimal to integer cents, half-up."""
    return int(d.quantize(CENT, rounding=ROUND_HALF_UP))


def round_lb(d):
    """Round a Decimal to one decimal pound, half-up."""
    return d.quantize(TENTH, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Calculation: customer_strike_policy
# ---------------------------------------------------------------------------

def customer_status(strikes):
    if strikes <= 0:
        return "ACTIVE"
    if strikes < STRIKE_BLOCK_THRESHOLD:
        return "ELEVATED_DEPOSIT"
    return "BLOCKED"


# ---------------------------------------------------------------------------
# Calculation: invoice_settlement — tiered processing schedule
# ---------------------------------------------------------------------------

def tiered_processing_cents(w_lbs, species):
    """Two-tier marginal hanging-weight processing fee (integer cents)."""
    w_lbs = Decimal(w_lbs)
    if w_lbs <= TIER1_MAX_LBS:
        return round_cents(w_lbs * RATE_A_CENTS_PER_LB[species])
    base = int(TIER1_MAX_LBS) * RATE_A_CENTS_PER_LB[species]
    return base + round_cents((w_lbs - TIER1_MAX_LBS) * RATE_B_CENTS_PER_LB[species])


def slaughter_share_cents(species, share_fraction):
    return round_cents(Decimal(SLAUGHTER_FEE_CENTS[species]) * Decimal(share_fraction))


# ---------------------------------------------------------------------------
# Calculation: deposit_quote (STANDARD / ELEVATED variants)
# ---------------------------------------------------------------------------

def deposit_quote_cents(cust_status, species, head_count):
    if cust_status == "ELEVATED_DEPOSIT":
        est_hanging = AVG_LIVE_WEIGHT_LBS[species] * DRESS_PCT[species] * head_count
        est_processing = tiered_processing_cents(est_hanging, species)
        est_value = est_processing + SLAUGHTER_FEE_CENTS[species] * head_count
        return round_cents(ELEVATED_DEPOSIT_PCT * est_value)
    # STANDARD (ACTIVE). BLOCKED customers are rejected before this point.
    return DEPOSIT_FLAT_PER_HEAD_CENTS[species] * head_count


# ---------------------------------------------------------------------------
# Calculation: share_weight_allocation (per-share round, residual to largest)
# ---------------------------------------------------------------------------

def allocate_share_weights(shares_sorted, hanging_weight_lbs, live_weight_lbs, species):
    """Mutates each share dict: share_hanging_weight_lbs + estimated_share_weight_lbs.

    shares_sorted: the animal's shares ordered by created_at ASC (creation
    order). Invariant: allocated weights sum to hanging_weight_lbs exactly.
    """
    hanging = Decimal(hanging_weight_lbs)
    weights = []
    for sh in shares_sorted:
        weights.append(round_lb(hanging * Decimal(sh["share_fraction"])))
    residual = hanging - sum(weights, Decimal("0"))
    if residual != 0 and shares_sorted:
        target = _largest_fraction_index(shares_sorted)
        weights[target] = round_lb(weights[target] + residual)
    for sh, w in zip(shares_sorted, weights):
        sh["share_hanging_weight_lbs"] = w
        sh["estimated_share_weight_lbs"] = round_lb(
            Decimal(live_weight_lbs) * DRESS_PCT[species] * Decimal(sh["share_fraction"]))


def _largest_fraction_index(shares_sorted):
    """Largest share_fraction; ties break to the earliest created (list order)."""
    best = 0
    best_frac = Decimal(shares_sorted[0]["share_fraction"])
    for i, sh in enumerate(shares_sorted):
        f = Decimal(sh["share_fraction"])
        if f > best_frac:
            best = i
            best_frac = f
    return best


# ---------------------------------------------------------------------------
# Calculation: deposit_credit_allocation (two-level waterfall)
# ---------------------------------------------------------------------------

def animal_deposit_pool_cents(appointment, animal):
    """Level 1 (appointment -> animal): base share per head, residual cents to
    the earliest-created animal of the appointment."""
    paid = appointment["deposit_paid_cents"]
    head = appointment["head_count"]
    base = round_cents(Decimal(paid) / Decimal(head))
    animals_sorted = sorted(
        (a for a in db.animals.values() if a["appointment_id"] == appointment["id"]),
        key=lambda a: a["_seq"],
    )
    residual = paid - base * head
    if animals_sorted and animals_sorted[0]["id"] == animal["id"]:
        return base + residual
    return base


def allocate_deposit_credit(shares_sorted, pool_cents):
    """Level 2 (animal -> shares): per-share round_half_up FIRST, then the
    residual is reconciled onto the largest-fraction share (tie: earliest)."""
    credits = []
    for sh in shares_sorted:
        credits.append(round_cents(Decimal(pool_cents) * Decimal(sh["share_fraction"])))
    residual = pool_cents - sum(credits)
    if residual != 0 and shares_sorted:
        credits[_largest_fraction_index(shares_sorted)] += residual
    return credits


# ---------------------------------------------------------------------------
# Calculation: storage_fee
# ---------------------------------------------------------------------------

def storage_days_stored(ready_dt, end_dt):
    return max(0, whole_days_between(ready_dt, end_dt))


def storage_accrued_cents(days_stored):
    return max(0, days_stored - FREE_STORAGE_DAYS) * STORAGE_DAILY_CENTS
