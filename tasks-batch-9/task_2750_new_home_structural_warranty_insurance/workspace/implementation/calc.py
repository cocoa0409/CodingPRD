"""Every pinned calculation of the program (SCAFFOLD 1.3 / PRD 2.5 and 3.x).

All money is integer cents.  Every rounding in this document is round half up,
so `float` is never used for an arithmetic step -- only for JSON serialisation
of already-rounded rates.
"""

import calendar
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

# --- builder_risk_score ----------------------------------------------------
STRENGTH_BONUS = {"TIER_1": 15, "TIER_2": 8, "TIER_3": 0}
VOLUME_BUCKET_SIZE = 25
VOLUME_POINTS_PER_BUCKET = 8
VOLUME_WEIGHT = Decimal("0.25")
VOLUME_CAP = 40
TENURE_CAP = 20
OBSERVED_LOSS_WEIGHT = 60
CLASS_B_FLOOR = Decimal("25.00")
CLASS_C_FLOOR = Decimal("45.00")
CLASS_D_FLOOR = Decimal("65.00")
HISTORY_MULTIPLIER = Decimal("0.50")
SCORE_BASE = Decimal("50")

# --- policy_premium --------------------------------------------------------
BASE_RATE_BP = {"A": 38, "B": 52, "C": 71, "D": 95}
STRUCTURAL_LOADING = {
    "A": Decimal("1.00"),
    "B": Decimal("1.10"),
    "C": Decimal("1.25"),
    "D": Decimal("1.45"),
}
SHARE_WORKMANSHIP = Decimal("0.18")
SHARE_SYSTEMS = Decimal("0.27")
SHARE_STRUCTURAL = Decimal("0.55")
STATE_SURCHARGE = {"TX": 4500, "FL": 9500, "CO": 2500, "AZ": 0, "NC": 1500}

# --- coverage_term_schedule ------------------------------------------------
WORKMANSHIP_YEARS = 1
SYSTEMS_YEARS = 2
STRUCTURAL_YEARS = 10
WORKMANSHIP_LIMIT_CAP_CENTS = 2000000
SYSTEMS_LIMIT_CAP_CENTS = 6000000
STANDARD_DEDUCTIBLE_CENTS = 100000
STRUCTURAL_DEDUCTIBLE_CENTS = 250000
WORKMANSHIP_LIMIT_SHARE = Decimal("0.10")
SYSTEMS_LIMIT_SHARE = Decimal("0.25")

# --- structural_designation ------------------------------------------------
LOAD_BEARING_ELEMENTS = frozenset(
    ["FOOTING", "FOUNDATION_WALL", "BEAM", "LOAD_BEARING_WALL", "ROOF_TRUSS", "SLAB"]
)
ALL_ELEMENTS = frozenset(
    list(LOAD_BEARING_ELEMENTS) + ["NON_BEARING_PARTITION", "FINISH"]
)
DEFLECTION_THRESHOLD = Decimal("0.0033")

# --- claim_net_payable -----------------------------------------------------
BETTERMENT_TIER_1_FLOOR = 500000
BETTERMENT_TIER_2_FLOOR = 1500000
BETTERMENT_TIER_1_PCT = Decimal("0.05")
BETTERMENT_TIER_2_PCT = Decimal("0.08")

# --- builder_loss_ratio ----------------------------------------------------
POSTURE_WATCH_FLOOR = Decimal("0.6500")
POSTURE_RESTRICTED_FLOOR = Decimal("0.9000")
POSTURE_FROZEN_FLOOR = Decimal("1.2000")

# --- transfer_fee ----------------------------------------------------------
TRANSFER_BASE_FEE_CENTS = 7500
REPEAT_TRANSFER_FEE_CENTS = 2500

# --- escalation_deadline ---------------------------------------------------
MEDIATION_WINDOW_DAYS = 60
ARBITRATION_WINDOW_DAYS = 30

# --- neutral calendar ------------------------------------------------------
NEUTRAL_TURNAROUND_MINUTES = 120

# --- enumerations ----------------------------------------------------------
STATE_CODES = frozenset(["TX", "CO", "AZ", "FL", "NC"])
FINANCIAL_TIERS = frozenset(["TIER_1", "TIER_2", "TIER_3"])
COVERAGE_TYPES = frozenset(["WORKMANSHIP", "SYSTEMS", "STRUCTURAL"])
DEFECT_CATEGORIES = frozenset([
    "WORKMANSHIP_DEFECT", "SYSTEM_FAILURE", "STRUCTURAL_CRACKING",
    "LOAD_BEARING_FAILURE", "WATER_INTRUSION",
])
CREDENTIALS = frozenset(["MEDIATOR", "ARBITRATOR", "BOTH"])
CLAIM_TERMINAL_STATES = frozenset([
    "CLOSED_REPAIRED", "CLOSED_PAID", "CLOSED_SETTLED", "CLOSED_AWARDED",
    "CLOSED_DENIED_FINAL", "SUSPENDED_NO_LIMIT",
])


# ---------------------------------------------------------------------------
# Rounding helpers -- round half up everywhere (PRD 2.5).
# ---------------------------------------------------------------------------
def round_cents(value):
    """Round a Decimal to a whole number of cents, half up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_places(value, places):
    quant = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


def dec(value):
    return Decimal(str(value))


# ---------------------------------------------------------------------------
# calculations.builder_risk_score
# ---------------------------------------------------------------------------
def risk_score(effective_claims_score, effective_home_volume, years_in_business,
               financial_strength_tier):
    history_penalty = (Decimal(100) - dec(effective_claims_score)) * HISTORY_MULTIPLIER
    buckets = int(effective_home_volume) // VOLUME_BUCKET_SIZE
    volume_factor = min(VOLUME_CAP, buckets * VOLUME_POINTS_PER_BUCKET)
    tenure_credit = min(TENURE_CAP, int(years_in_business) * 2)
    strength_bonus = STRENGTH_BONUS[financial_strength_tier]
    raw = (SCORE_BASE + history_penalty + (Decimal(volume_factor) * VOLUME_WEIGHT)
           - Decimal(tenure_credit) - Decimal(strength_bonus))
    clamped = max(Decimal(0), min(Decimal(100), raw))
    return round_places(clamped, 2)


def risk_class_for(score):
    score = Decimal(score)
    if score < CLASS_B_FLOOR:
        return "A"
    if score < CLASS_C_FLOOR:
        return "B"
    if score < CLASS_D_FLOOR:
        return "C"
    return "D"


def observed_claims_score(loss_ratio):
    """renewal_reassessment variant: effective claims score from realised loss."""
    raw = round_places(Decimal(100) - (dec(loss_ratio) * Decimal(OBSERVED_LOSS_WEIGHT)), 2)
    return max(Decimal(0), min(Decimal(100), raw))


# ---------------------------------------------------------------------------
# calculations.policy_premium
# ---------------------------------------------------------------------------
def premium_components(purchase_price_cents, risk_class, state_code):
    bp = Decimal(BASE_RATE_BP[risk_class])
    load = STRUCTURAL_LOADING[risk_class]
    price = Decimal(purchase_price_cents)
    workmanship = round_cents(price * SHARE_WORKMANSHIP * bp / Decimal(10000))
    systems = round_cents(price * SHARE_SYSTEMS * bp / Decimal(10000))
    structural = round_cents(price * SHARE_STRUCTURAL * bp / Decimal(10000) * load)
    surcharge = STATE_SURCHARGE[state_code]
    total = workmanship + systems + structural + surcharge
    return {
        "premium_component_workmanship_cents": workmanship,
        "premium_component_systems_cents": systems,
        "premium_component_structural_cents": structural,
        "state_surcharge_cents": surcharge,
        "premium_cents": total,
    }


# ---------------------------------------------------------------------------
# calculations.coverage_term_schedule
# ---------------------------------------------------------------------------
def add_years(anchor, years):
    target_year = anchor.year + years
    last_day = calendar.monthrange(target_year, anchor.month)[1]
    return date(target_year, anchor.month, min(anchor.day, last_day))


def anniversary_end(anchor, years):
    """add_years(d, n) - 1 day."""
    return add_years(anchor, years) - timedelta(days=1)


def base_term_specs(closing_date, purchase_price_cents):
    price = Decimal(purchase_price_cents)
    workmanship_limit = min(round_cents(price * WORKMANSHIP_LIMIT_SHARE),
                            WORKMANSHIP_LIMIT_CAP_CENTS)
    systems_limit = min(round_cents(price * SYSTEMS_LIMIT_SHARE), SYSTEMS_LIMIT_CAP_CENTS)
    return [
        {
            "coverage_type": "WORKMANSHIP",
            "end_date": anniversary_end(closing_date, WORKMANSHIP_YEARS),
            "limit_cents": workmanship_limit,
            "deductible_cents": STANDARD_DEDUCTIBLE_CENTS,
        },
        {
            "coverage_type": "SYSTEMS",
            "end_date": anniversary_end(closing_date, SYSTEMS_YEARS),
            "limit_cents": systems_limit,
            "deductible_cents": STANDARD_DEDUCTIBLE_CENTS,
        },
        {
            "coverage_type": "STRUCTURAL",
            "end_date": anniversary_end(closing_date, STRUCTURAL_YEARS),
            "limit_cents": purchase_price_cents,
            "deductible_cents": STRUCTURAL_DEDUCTIBLE_CENTS,
        },
    ]


# ---------------------------------------------------------------------------
# calculations.structural_designation
# ---------------------------------------------------------------------------
def structural_designation(affected_elements, deflection_ratio, load_bearing_affected):
    hits = sum(1 for element in affected_elements if element in LOAD_BEARING_ELEMENTS)
    return (bool(load_bearing_affected)
            and hits >= 1
            and dec(deflection_ratio) >= DEFLECTION_THRESHOLD)


# ---------------------------------------------------------------------------
# calculations.claim_net_payable -- the seven pinned steps.
# ---------------------------------------------------------------------------
def gross_adjusted(claimed_amount_cents, substantiation_ratio):
    """Step 1."""
    return round_cents(Decimal(claimed_amount_cents) * dec(substantiation_ratio))


def betterment_pct(provisional_net_cents):
    """Step 5 -- selected from the provisional net, BEFORE betterment."""
    if provisional_net_cents < BETTERMENT_TIER_1_FLOOR:
        return Decimal("0.00")
    if provisional_net_cents < BETTERMENT_TIER_2_FLOOR:
        return BETTERMENT_TIER_1_PCT
    return BETTERMENT_TIER_2_PCT


def settlement_waterfall(claimed_amount_cents, substantiation_ratio,
                         designated_structural, variant, term_remaining_limit_cents):
    """Returns the four settlement figures.  `variant` is 'builder' or 'insurer'."""
    gross = gross_adjusted(claimed_amount_cents, substantiation_ratio)
    schedule = (STRUCTURAL_DEDUCTIBLE_CENTS if designated_structural
                else STANDARD_DEDUCTIBLE_CENTS)
    if variant == "builder":
        deductible = 0
    else:
        deductible = min(schedule, gross)
    provisional = gross - deductible
    pct = betterment_pct(provisional)
    betterment = round_cents(Decimal(provisional) * pct)
    net = min(provisional - betterment, term_remaining_limit_cents)
    return {
        "gross_adjusted_cents": gross,
        "deductible_applied_cents": deductible,
        "betterment_cents": betterment,
        "net_payable_cents": net,
    }


# ---------------------------------------------------------------------------
# calculations.builder_loss_ratio
# ---------------------------------------------------------------------------
def loss_ratio_of(incurred_loss_cents, earned_premium_cents):
    if earned_premium_cents == 0:
        return Decimal("0.0000")
    return round_places(Decimal(incurred_loss_cents) / Decimal(earned_premium_cents), 4)


def posture_for(loss_ratio):
    ratio = Decimal(loss_ratio)
    if ratio < POSTURE_WATCH_FLOOR:
        return "OPEN"
    if ratio < POSTURE_RESTRICTED_FLOOR:
        return "WATCH"
    if ratio < POSTURE_FROZEN_FLOOR:
        return "RESTRICTED"
    return "FROZEN"


# ---------------------------------------------------------------------------
# calculations.transfer_fee
# ---------------------------------------------------------------------------
def transfer_fee(transfer_count):
    return TRANSFER_BASE_FEE_CENTS + (REPEAT_TRANSFER_FEE_CENTS * int(transfer_count))
