"""Calculation rules (SCAFFOLD 1.3 / PRD 2.7, 3.5, 3.6, 3.7, 3.9).

All money is integer cents; rounding is round-half-up at exactly the points the
specification pins.
"""
import math
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

# ---------------------------------------------------------------- constants --
# blight_priority_score
GRADE_POINTS = {"A": 0, "B": 8, "C": 18, "D": 30, "F": 44}
W_VACANCY = Decimal("0.25")
VACANCY_CAP_MONTHS = 60
W_COMPLAINT = Decimal("1.5")
COMPLAINT_TERM_CAP = Decimal(12)
W_VIOLATION = Decimal(3)
VIOLATION_TERM_CAP = Decimal(15)
ADJACENT_INVENTORY_MIN = 2
ADJACENT_INVENTORY_BONUS = Decimal(10)
W_HOLDING = Decimal("0.5")
HOLDING_TERM_CAP = Decimal(12)
SCORE_CEILING = Decimal(100)

# maintenance_order_estimate
MOW_RATE_PER_KSQFT_CENTS = Decimal(1850)
SECURE_BASE_CENTS = Decimal(45000)
SECURE_RATE_PER_OPENING_CENTS = Decimal(12750)
DEMO_BASE_CENTS = Decimal(950000)
DEMO_RATE_PER_SQFT_CENTS = Decimal(62)
ASBESTOS_SURCHARGE_PCT = Decimal("0.18")
ASBESTOS_GRADES = ("D", "F")
COUNTY_OVERHEAD_PCT = Decimal("0.065")

# demolition_run_allocation
MIN_SCORE_THRESHOLD = Decimal(40)
ADMIN_RATE = Decimal("0.075")
MAX_PROPERTIES_PER_RUN = 5
DEMOLITION_WINDOW_DAYS = 45
DEMOLITION_BUFFER_HOURS = 72

# disposition_price_quote
SIDE_LOT_BASE_CENTS = Decimal(10000)
SIDE_LOT_FREE_AREA_SQFT = 5000
SIDE_LOT_MARGINAL_CENTS_PER_SQFT = Decimal(2)
SIDE_LOT_ASSESSED_CAP_PCT = Decimal("0.25")
HOMEOWNER_ASSESSED_PCT = Decimal("0.55")
HOMEOWNER_FLOOR_CENTS = Decimal(100000)
DEVELOPER_ASSESSED_PCT = Decimal("0.90")
DEVELOPER_FLOOR_CENTS = Decimal(500000)
COMMUNITY_USE_CENTS = Decimal(100)
STRUCTURE_DISCOUNT_PCT = Decimal("0.15")
DISCOUNT_GRADES = ("D", "F")

# tax_discharge_and_abatement
NEGOTIATED_DISCHARGE_CAP_PCT = Decimal("0.40")
CURE_PERIOD_DAYS = 90
COUNTY_MILLAGE_RATE = Decimal("0.0142")
ABATEMENT_ANNUAL_CAP_CENTS = 250000
MAX_ABATEMENT_YEARS = 10

# buyer_eligibility_evaluation
CODE_VIOLATION_BAR = 2
REVERTER_LOOKBACK_DAYS = 1825
SIDE_LOT_MIN_SHARED_BOUNDARY_FEET = Decimal(20)
DISQUALIFIER_PENALTY = 25
HOMEOWNER_MAX_CONVEYED = 2
MAX_REVISION_ROUNDS = 2

# funding_ledger_position
RESERVE_FLOOR_PCT = Decimal("0.05")

# hearing_support_ratio
HEARING_VALIDITY_DAYS = 180
HEARING_QUORUM_COMMENTS = 5
HEARING_SUPPORT_MIN_RATIO = Decimal("0.60")

PROGRAMS = ("SIDE_LOT", "HOMEOWNER_SALE", "DEVELOPER_RFP", "COMMUNITY_USE")
WORK_TYPES = ("SECURE", "MOW", "DEMOLITION")


# ------------------------------------------------------------------ helpers --

def rhu(value, places=0):
    """Round half up to `places` decimal places."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    exponent = Decimal(1).scaleb(-places)
    return value.quantize(exponent, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def floor_div_decimal(numerator, denominator):
    value = Decimal(numerator) / Decimal(denominator)
    return int(value.to_integral_value(rounding=ROUND_FLOOR))


# --------------------------------------------------- blight_priority_score --

def blight_priority_score(prop, variant, clock_now, inventory_neighbor_count):
    """Weighted score; rounding and the ceiling apply once, at the very end."""
    if prop["structure_present"]:
        grade_pts = Decimal(GRADE_POINTS[prop["structure_condition_grade"]])
    else:
        grade_pts = Decimal(0)
    vac_pts = W_VACANCY * Decimal(min(prop["vacancy_months"], VACANCY_CAP_MONTHS))
    comp_pts = min(COMPLAINT_TERM_CAP, W_COMPLAINT * Decimal(prop["nuisance_complaint_count"]))
    viol_pts = min(VIOLATION_TERM_CAP, W_VIOLATION * Decimal(prop["open_code_violation_count"]))
    adj_bonus = (
        ADJACENT_INVENTORY_BONUS
        if inventory_neighbor_count >= ADJACENT_INVENTORY_MIN
        else Decimal(0)
    )
    hold_pts = Decimal(0)
    if variant == "SWEEP_FINAL" and prop.get("acquired_at") is not None:
        elapsed = clock_now - prop["acquired_at"]
        months = int(elapsed.total_seconds() // (30 * 86400))
        if months < 0:
            months = 0
        hold_pts = min(HOLDING_TERM_CAP, W_HOLDING * Decimal(months))
    raw = grade_pts + vac_pts + comp_pts + viol_pts + adj_bonus + hold_pts
    score = min(SCORE_CEILING, rhu(raw, 1))
    return float(score)


# ------------------------------------------------ maintenance_order_estimate --

def maintenance_order_estimate(work_type, lot_area_sqft, grade, openings_count=None):
    """Two-stage pinned rounding: line items first, then county overhead."""
    if work_type == "MOW":
        thousands = int(math.ceil(Decimal(lot_area_sqft) / Decimal(1000)))
        lines = [rhu(Decimal(thousands) * MOW_RATE_PER_KSQFT_CENTS)]
    elif work_type == "SECURE":
        lines = [
            rhu(SECURE_BASE_CENTS),
            rhu(Decimal(openings_count or 0) * SECURE_RATE_PER_OPENING_CENTS),
        ]
    else:  # DEMOLITION
        per_sqft = rhu(Decimal(lot_area_sqft) * DEMO_RATE_PER_SQFT_CENTS)
        if grade in ASBESTOS_GRADES:
            asbestos = rhu(ASBESTOS_SURCHARGE_PCT * (DEMO_BASE_CENTS + per_sqft))
        else:
            asbestos = Decimal(0)
        lines = [rhu(DEMO_BASE_CENTS), per_sqft, asbestos]
    subtotal = sum(lines, Decimal(0))
    overhead = rhu(COUNTY_OVERHEAD_PCT * subtotal)
    return int(subtotal + overhead)


def demolition_estimate(prop):
    return maintenance_order_estimate(
        "DEMOLITION", prop["lot_area_sqft"], prop["structure_condition_grade"]
    )


# --------------------------------------------------- disposition_price_quote --

def disposition_price_quote(prop, program):
    """Returns the full breakdown the computed read answers with."""
    assessed = Decimal(prop["assessed_value_cents"])
    lot_area = prop["lot_area_sqft"]
    marginal_area = 0
    if program == "SIDE_LOT":
        marginal_area = max(0, lot_area - SIDE_LOT_FREE_AREA_SQFT)
        raw = SIDE_LOT_BASE_CENTS + Decimal(marginal_area) * SIDE_LOT_MARGINAL_CENTS_PER_SQFT
        cap = rhu(SIDE_LOT_ASSESSED_CAP_PCT * assessed)
        quoted = max(SIDE_LOT_BASE_CENTS, min(raw, cap))
        floor_cents = SIDE_LOT_BASE_CENTS
        assessed_cap = cap
    elif program == "HOMEOWNER_SALE":
        assessed_cap = rhu(HOMEOWNER_ASSESSED_PCT * assessed)
        quoted = max(HOMEOWNER_FLOOR_CENTS, assessed_cap)
        floor_cents = HOMEOWNER_FLOOR_CENTS
    elif program == "DEVELOPER_RFP":
        assessed_cap = rhu(DEVELOPER_ASSESSED_PCT * assessed)
        quoted = max(DEVELOPER_FLOOR_CENTS, assessed_cap)
        floor_cents = DEVELOPER_FLOOR_CENTS
    else:  # COMMUNITY_USE
        quoted = COMMUNITY_USE_CENTS
        floor_cents = COMMUNITY_USE_CENTS
        assessed_cap = Decimal(0)

    discount_applied = False
    if (
        program != "COMMUNITY_USE"
        and prop["structure_present"]
        and prop["structure_condition_grade"] in DISCOUNT_GRADES
    ):
        discount_applied = True
        quoted = max(floor_cents, quoted - rhu(STRUCTURE_DISCOUNT_PCT * quoted))

    return {
        "program": program,
        "quoted_price_cents": int(quoted),
        "tier_applied": program,
        "marginal_area_sqft": int(marginal_area),
        "assessed_cap_cents": int(assessed_cap),
        "discount_applied": discount_applied,
    }


def quoted_price_cents(prop, program):
    return disposition_price_quote(prop, program)["quoted_price_cents"]


# ------------------------------------------------ tax_discharge_and_abatement --

def tax_discharge_and_abatement(prop, discharge_mode, sale_price_cents,
                                projected_improved_value_cents, abatement_years):
    frozen = int(prop["pre_acquisition_delinquency_cents"])
    if discharge_mode == "STATUTORY":
        discharged = frozen
        abatement_base = Decimal(projected_improved_value_cents)
    else:  # NEGOTIATED
        capped = rhu(NEGOTIATED_DISCHARGE_CAP_PCT * Decimal(sale_price_cents))
        discharged = min(frozen, int(capped))
        abatement_base = Decimal(prop["assessed_value_cents"])
    annual = min(ABATEMENT_ANNUAL_CAP_CENTS, rhu_int(COUNTY_MILLAGE_RATE * abatement_base))
    total = annual * int(abatement_years)
    return {
        "discharged_tax_cents": int(discharged),
        "abatement_annual_cents": int(annual),
        "abatement_total_cents": int(total),
    }


# ------------------------------------------------------ hearing_support_ratio --

def hearing_support_ratio(support_count, comment_count):
    if comment_count >= 1:
        return float(rhu(Decimal(support_count) / Decimal(comment_count), 4))
    return 0.0


# ----------------------------------------------------- funding reserve floor --

def reserve_floor_cents(authorized_cents):
    return rhu_int(RESERVE_FLOOR_PCT * Decimal(authorized_cents))


# ------------------------------------------------------------ eligibility ----

def eligibility_score(disqualifier_count):
    return max(0, 100 - DISQUALIFIER_PENALTY * disqualifier_count)
