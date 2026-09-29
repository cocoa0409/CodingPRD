"""Calculation rules (PRD 2.5, 3.6, 3.7, 3.8, 3.9).

Every monetary amount is an integer number of cents.  Decimal is used wherever a
rounding discipline is attached; float never touches money.
"""

import calendar
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

# --- category partition (PRD 3.6) -------------------------------------------
NON_QRE_CATEGORIES = {
    "ACQUISITION",
    "ENLARGEMENT",
    "SITE_WORK",
    "PERSONAL_PROPERTY",
    "FFE",
    "LANDSCAPING",
}
QRE_ELIGIBLE_CATEGORIES = {
    "HARD_CONSTRUCTION",
    "ARCHITECTURAL_ENGINEERING",
    "DEVELOPER_FEE",
    "CONSTRUCTION_INTEREST",
}
ALL_CATEGORIES = NON_QRE_CATEGORIES | QRE_ELIGIBLE_CATEGORIES

CLASSIFIED_STATES = {"QRE", "NON_QRE", "LOCKED_QRE", "LOCKED_NON_QRE"}

# --- constants ---------------------------------------------------------------
DEVELOPER_FEE_CAP_NUMERATOR = 15          # DEVELOPER_FEE_CAP_RATE = 0.15
DEVELOPER_FEE_CAP_DENOMINATOR = 100
SUBSTANTIAL_TEST_FLOOR_CENTS = 500000
CREDIT_RATE_PER_YEAR = Decimal("0.04")
RATABLE_YEARS = 5

BASE_RISK = 10
BUILDING_USEFUL_LIFE_YEARS = 39
LEASE_TERM_SAFE_HARBOR_RATIO = Decimal("0.80")
LEASE_TERM_POINTS_CAP = 30
ELECTION_PENDING_POINTS = 12
COVENANT_BREACH_POINTS = 20
UNRESOLVED_VIOLATION_POINTS = 10
IN_SERVICE_ADDER_CAP = 60
HIGH_RISK_THRESHOLD = 70
TAX_STATUS_POINTS = {
    "TAXABLE_C_CORP": 0,
    "PARTNERSHIP": 10,
    "GOVERNMENTAL_UNIT": 35,
    "TAX_EXEMPT_ORG": 45,
}

COMPLIANCE_PERIOD_YEARS = 5
RECAPTURE_STEP_RATE = Decimal("0.20")
DAYS_PER_YEAR = 365

SHPO_REVIEW_WINDOW_DAYS = 30
REVIEWER_WINDOW_CAPACITY = 2
MAX_REVIEW_ROUNDS = 3
CURE_WINDOW_DAYS = 90
NPS_CONCURRENCE_DELTA_CENTS = 5000000
MAX_ALLOCATION_PCT = Decimal("100.00")


def round_half_up(value):
    """Round a Decimal half up to a whole unit and return an int."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def add_months(start, months):
    """Advance by calendar months preserving the day of month (PRD 2.11)."""
    total = start.month - 1 + months
    year = start.year + total // 12
    month = total % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def add_days(start, days):
    return start + timedelta(days=days)


def days_between(start, end):
    return (end - start).days


def half_open_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap: a.start < b.end AND b.start < a.end."""
    return a_start < b_end and b_start < a_end


def closed_overlap(a_start, a_end, b_start, b_end):
    """Closed [start, end] overlap: a.start <= b.end AND b.start <= a.end."""
    return a_start <= b_end and b_start <= a_end


# --- qre_totals -------------------------------------------------------------
def qre_totals(items, variant):
    """Segregate qualified from non-qualified costs for one variant (PRD 3.6).

    `items` are every CostLineItem row of the project; only in-period rows
    participate.
    """
    in_period = [i for i in items if i["in_measuring_period"]]

    if variant == "FINAL":
        counted = [i for i in in_period if i["classification"] in ("QRE", "LOCKED_QRE")]
    else:  # PROVISIONAL
        counted = [
            i
            for i in in_period
            if i["classification"] in ("QRE", "LOCKED_QRE")
            or (
                i["classification"] == "PENDING_CLASSIFICATION"
                and i["category"] in QRE_ELIGIBLE_CATEGORIES
            )
        ]

    hard_qre = sum(i["amount_cents"] for i in counted if i["category"] != "DEVELOPER_FEE")
    fee_claimed = sum(i["amount_cents"] for i in counted if i["category"] == "DEVELOPER_FEE")

    # Developer-fee cap: 15% of hard costs, floored to a whole cent.
    fee_cap = (hard_qre * DEVELOPER_FEE_CAP_NUMERATOR) // DEVELOPER_FEE_CAP_DENOMINATOR
    fee_allowed = min(fee_claimed, fee_cap)
    fee_disallowed = fee_claimed - fee_allowed

    qre_total = hard_qre + fee_allowed

    nonqualified_total = (
        sum(
            i["amount_cents"]
            for i in in_period
            if i["classification"] in ("NON_QRE", "LOCKED_NON_QRE")
        )
        + fee_disallowed
    )

    classified_cost_total = sum(
        i["amount_cents"] for i in in_period if i["classification"] in CLASSIFIED_STATES
    )

    return {
        "variant": variant,
        "hard_qre": hard_qre,
        "fee_claimed": fee_claimed,
        "fee_cap": fee_cap,
        "fee_allowed": fee_allowed,
        "fee_disallowed": fee_disallowed,
        "qre_total": qre_total,
        "nonqualified_total": nonqualified_total,
        "classified_cost_total": classified_cost_total,
        "in_period_item_count": len(in_period),
        "pending_classification_item_count": sum(
            1 for i in in_period if i["classification"] == "PENDING_CLASSIFICATION"
        ),
    }


def substantial_threshold(adjusted_basis_cents):
    return max(adjusted_basis_cents, SUBSTANTIAL_TEST_FLOOR_CENTS)


def substantial_status(qre_total_cents, threshold_cents):
    return "MET" if qre_total_cents >= threshold_cents else "NOT_MET"


def ratable_credit(qre_total_final_cents, test_status):
    """Per-year amount is rounded FIRST; the total is the rounded product."""
    if test_status != "MET":
        return 0, 0
    annual = round_half_up(Decimal(qre_total_final_cents) * CREDIT_RATE_PER_YEAR)
    return annual, annual * RATABLE_YEARS


# --- investor_disqualification_risk ----------------------------------------
def safe_harbor_years():
    return int(
        (Decimal(BUILDING_USEFUL_LIFE_YEARS) * LEASE_TERM_SAFE_HARBOR_RATIO).to_integral_value(
            rounding="ROUND_FLOOR"
        )
    )


def lease_term_points(interest):
    if interest["kind"] != "MASTER_LEASE_LESSEE" or interest.get("lease_term_years") is None:
        return 0
    harbor = safe_harbor_years()
    years = interest["lease_term_years"]
    if years >= harbor:
        return LEASE_TERM_POINTS_CAP
    return round_half_up(Decimal(LEASE_TERM_POINTS_CAP * years) / Decimal(harbor))


def base_risk_score(interest, election_state=None):
    election = election_state if election_state is not None else interest["pass_through_election"]
    points = BASE_RISK
    points += TAX_STATUS_POINTS[interest["party_tax_status"]]
    points += lease_term_points(interest)
    if election == "PENDING":
        points += ELECTION_PENDING_POINTS
    return points


def risk_score(interest, variant, breached_covenant_count=0, unresolved_violation_total=0,
               election_state=None):
    base = base_risk_score(interest, election_state)
    if variant == "ADMISSION":
        return min(100, base)
    adder = (
        COVENANT_BREACH_POINTS * breached_covenant_count
        + UNRESOLVED_VIOLATION_POINTS * unresolved_violation_total
    )
    return min(100, base + min(IN_SERVICE_ADDER_CAP, adder))


# --- recapture_assessment ---------------------------------------------------
def recapture_assessment(placed_in_service_date, event_date, event_type,
                         credit_claimed_to_date_cents):
    elapsed_days = days_between(placed_in_service_date, event_date)
    full_years = elapsed_days // DAYS_PER_YEAR if elapsed_days >= 0 else -((-elapsed_days) // DAYS_PER_YEAR + 1)
    if event_type == "SUBSTANTIAL_TEST_FAILURE":
        pct = Decimal("1.00")
    else:
        remaining = COMPLIANCE_PERIOD_YEARS - full_years
        pct = (Decimal(remaining) * RECAPTURE_STEP_RATE).quantize(Decimal("0.01"))
    amount = round_half_up(Decimal(credit_claimed_to_date_cents) * pct)
    return full_years, pct, amount
