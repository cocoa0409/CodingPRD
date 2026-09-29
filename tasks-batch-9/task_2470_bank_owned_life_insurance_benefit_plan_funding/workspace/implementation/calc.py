"""All ten declared calculations (PRD 3.x, SCAFFOLD calculations)."""

from decimal import Decimal, ROUND_FLOOR

from errors import ApiError
from store import db, ordered
from util import bps as to_bps, money, round_half_up, to_decimal

ZERO = Decimal("0.00")

# ---- constants -----------------------------------------------------------

RATING_POINTS = {
    "A_PLUS_PLUS": 100,
    "A_PLUS": 90,
    "A": 80,
    "A_MINUS": 70,
    "B_PLUS_PLUS": 55,
    "B_PLUS": 40,
    "B": 20,
}
SURPLUS_UNIT_USD = Decimal("500000000")
MIN_APPROVAL_SCORE = 65
WATCH_LIST_SCORE_CAP = 60
INFO_REQUEST_LIMIT = 2

BASE_AGGREGATE_LIMIT_PCT = Decimal("0.25")
TIER_1_BREAK_BPS = 6000
TIER_2_BREAK_BPS = 8500
TIER_0 = Decimal("0.25")
TIER_1 = Decimal("0.22")
TIER_2 = Decimal("0.20")
SINGLE_CARRIER_LIMIT_GENERAL_BPS = 1500
SINGLE_CARRIER_LIMIT_SEPARATE_BPS = 1000

FUNDED_MIN_BPS = 10000
UNDERFUNDED_MIN_BPS = 8000

SURRENDER_CHARGE_BPS_BY_YEAR = {1: 600, 2: 500, 3: 400, 4: 300, 5: 200, 6: 100, 7: 0}
FEDERAL_TAX_RATE_BPS = 2100
STATE_TAX_RATE_BPS = 600

FAMILY_CAP_PCT = Decimal("0.60")
SURVIVOR_MULTIPLE = Decimal("2.0")
ALLOCATION_BPS_TOTAL = 10000

ME_DRIFT_TOLERANCE_BPS = 25
MIN_ACCEPTABLE_NET_YIELD_BPS = 150
CONSECUTIVE_LOW_YIELD_LIMIT = 2
CARRIER_RESTRICT_BPS = 1500
CARRIER_RELEASE_BPS = 1200

W_RESTRICTED_CARRIER = 20
W_WATCH_CARRIER = 15
W_ON_WATCH_PRODUCT = 5
W_CLOSED_PRODUCT = 10
W_CRITICAL_PLAN = 25
W_UNDERFUNDED_PLAN = 10
MODERATE_MIN_POINTS = 15
HIGH_MIN_POINTS = 35
SEVERE_MIN_POINTS = 60

INSURABLE_INTEREST_MIN_SALARY_USD = Decimal("250000.00")
NOTICE_THRESHOLD_USD = Decimal("25000000.00")
NOTICE_WAITING_PERIOD_DAYS = 30
CONSENT_GAP_DAYS = 30

LIVE_POLICY_STATUSES = ("IN_FORCE", "PENDING_EXCHANGE", "CLAIM_PENDING")
RESERVED_REQUEST_STATUSES = (
    "CAPACITY_RESERVED",
    "NOTICE_FILED",
    "CONCURRENCE_PENDING",
    "APPROVED",
)


# ---- capital snapshots ---------------------------------------------------


def latest_capital_position():
    """Greatest as_of_date, ties broken by created_at ascending."""
    rows = list(db.capital_positions.values())
    if not rows:
        return None
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    best = rows[0]
    for row in rows[1:]:
        if row["_as_of_date"] > best["_as_of_date"]:
            best = row
    return best


def tier1_capital(required=True):
    snapshot = latest_capital_position()
    if snapshot is None:
        if required:
            raise ApiError("ERR_NO_CAPITAL_POSITION")
        return None
    return snapshot["tier1_capital_usd"]


# ---- 1. carrier_financial_strength_score --------------------------------


def carrier_financial_strength_score(carrier):
    rating_points = RATING_POINTS[carrier["am_best_rating"]]
    steps = (carrier["statutory_surplus_usd"] / SURPLUS_UNIT_USD).to_integral_value(
        rounding=ROUND_FLOOR
    )
    surplus_points = int(min(Decimal(100), steps * 10))
    raw_concentration = Decimal(100) - (Decimal(carrier["concentration_bps"]) / Decimal(20))
    if raw_concentration < 0:
        raw_concentration = Decimal(0)
    concentration_points = round_half_up(raw_concentration, 1)
    raw = (
        Decimal("0.50") * Decimal(rating_points)
        + Decimal("0.30") * Decimal(surplus_points)
        + Decimal("0.20") * concentration_points
    )
    score = int(round_half_up(raw, 0))
    if carrier.get("watch_list_flag"):
        score = min(WATCH_LIST_SCORE_CAP, score)
    return {
        "rating_points": rating_points,
        "surplus_points": surplus_points,
        "concentration_points": concentration_points,
        "financial_strength_score": score,
    }


# ---- 2. purchase_capacity_headroom --------------------------------------


def purchase_capacity_headroom(request, carrier, product):
    tier1 = tier1_capital(required=True)
    base_limit = money(tier1 * BASE_AGGREGATE_LIMIT_PCT)

    committed = ZERO
    for row in db.carriers.values():
        committed += row["reserved_premium_usd"]
    for policy in db.policies.values():
        if policy["status"] in LIVE_POLICY_STATUSES:
            committed += policy["single_premium_usd"]
    committed = money(committed)

    premium = request["single_premium_usd"]
    prospective = money(committed + premium)

    if base_limit == 0:
        base_ratio_bps = 0
    else:
        base_ratio_bps = to_bps(prospective / base_limit * 10000)

    if base_ratio_bps <= TIER_1_BREAK_BPS:
        effective_limit_pct = TIER_0
    elif base_ratio_bps <= TIER_2_BREAK_BPS:
        effective_limit_pct = TIER_1
    else:
        effective_limit_pct = TIER_2

    aggregate_limit = money(tier1 * effective_limit_pct)
    headroom = money(aggregate_limit - prospective)

    carrier_concentration_bps = to_bps(
        (carrier["reserved_premium_usd"] + carrier["in_force_premium_usd"] + premium)
        / tier1
        * 10000
    )
    if product["account_type"] == "SEPARATE":
        single_carrier_limit_bps = SINGLE_CARRIER_LIMIT_SEPARATE_BPS
    else:
        single_carrier_limit_bps = SINGLE_CARRIER_LIMIT_GENERAL_BPS

    return {
        "tier1_capital_usd": tier1,
        "base_limit_usd": base_limit,
        "committed_usd": committed,
        "prospective_usd": prospective,
        "base_ratio_bps": base_ratio_bps,
        "effective_limit_pct": effective_limit_pct,
        "aggregate_limit_usd": aggregate_limit,
        "headroom_usd": headroom,
        "carrier_concentration_bps": carrier_concentration_bps,
        "single_carrier_limit_bps": single_carrier_limit_bps,
    }


# ---- 3. nqdc_liability_valuation ---------------------------------------


def discounted_benefit(plan, liability):
    rate = Decimal(1) + Decimal(plan["discount_rate_bps"]) / Decimal(10000)
    factor = rate ** int(liability["years_to_payout"])
    return money(liability["projected_benefit_usd"] / factor)


def plan_liabilities(plan_id, active_only=True):
    rows = [
        row
        for row in db.nqdc_liabilities.values()
        if row["nqdc_plan_id"] == plan_id and (not active_only or row["status"] == "ACTIVE")
    ]
    return ordered(rows)


def plan_totals(plan):
    accrual = ZERO
    pbo = ZERO
    matched = ZERO
    count = 0
    for liability in plan_liabilities(plan["id"]):
        count += 1
        accrual += liability["accrued_to_date_usd"]
        pbo += liability["discounted_benefit_usd"]
        policy_id = liability.get("matched_policy_id")
        if policy_id:
            policy = db.policies.get(policy_id)
            if policy is not None and policy["status"] in LIVE_POLICY_STATUSES:
                matched += policy["cash_surrender_value_usd"]
    return {
        "accrual_liability_usd": money(accrual),
        "pbo_liability_usd": money(pbo),
        "matched_cash_value_usd": money(matched),
        "participant_count": count,
    }


def funded_ratio_bps(matched_cash_value, basis_liability):
    if basis_liability == 0:
        return FUNDED_MIN_BPS
    return to_bps(matched_cash_value / basis_liability * 10000)


def funding_posture(ratio_bps):
    if ratio_bps >= FUNDED_MIN_BPS:
        return "FUNDED"
    if ratio_bps >= UNDERFUNDED_MIN_BPS:
        return "UNDERFUNDED"
    return "CRITICAL"


def plan_view(plan, basis="ACCRUAL"):
    totals = plan_totals(plan)
    if basis == "PBO":
        basis_liability = totals["pbo_liability_usd"]
    else:
        basis_liability = totals["accrual_liability_usd"]
    ratio = funded_ratio_bps(totals["matched_cash_value_usd"], basis_liability)
    return {
        "basis": basis,
        "accrual_liability_usd": totals["accrual_liability_usd"],
        "pbo_liability_usd": totals["pbo_liability_usd"],
        "matched_cash_value_usd": totals["matched_cash_value_usd"],
        "basis_liability_usd": basis_liability,
        "funded_ratio_bps": ratio,
        "funding_posture": funding_posture(ratio),
        "participant_count": totals["participant_count"],
    }


# ---- 4. policy_taxable_gain --------------------------------------------


def cost_recovery_method(product):
    return "LIFO_INCOME_FIRST" if product["mec_status"] == "MEC" else "FIFO_BASIS_FIRST"


def surrender_charge_bps(policy_year):
    year = int(policy_year)
    if year < 1:
        year = 1
    if year > 7:
        year = 7
    return SURRENDER_CHARGE_BPS_BY_YEAR[year]


def policy_taxable_gain(policy, product, disposition_type, requested_withdrawal):
    method = cost_recovery_method(product)
    charge_bps = surrender_charge_bps(policy["policy_year"])
    basis = policy["cost_basis_usd"]
    csv = policy["cash_surrender_value_usd"]

    if disposition_type == "FULL_SURRENDER":
        gross = csv
        taxable_gain = csv - basis
        if taxable_gain < 0:
            taxable_gain = ZERO
    elif disposition_type == "PARTIAL_SURRENDER":
        gross = to_decimal(requested_withdrawal or 0)
        gain_in_policy = csv - basis
        if gain_in_policy < 0:
            gain_in_policy = ZERO
        if method == "FIFO_BASIS_FIRST":
            taxable_gain = gross - basis
            if taxable_gain < 0:
                taxable_gain = ZERO
        else:
            taxable_gain = min(gross, gain_in_policy)
    else:  # EXCHANGE_1035
        gross = csv
        taxable_gain = ZERO

    taxable_gain = money(taxable_gain)
    surrender_charge = money(gross * Decimal(charge_bps) / Decimal(10000))
    tax_liability = money(
        taxable_gain * Decimal(FEDERAL_TAX_RATE_BPS + STATE_TAX_RATE_BPS) / Decimal(10000)
    )
    net_proceeds = money(money(gross) - surrender_charge - tax_liability)
    return {
        "cost_recovery_method": method,
        "taxable_gain_usd": taxable_gain,
        "surrender_charge_usd": surrender_charge,
        "tax_liability_usd": tax_liability,
        "net_proceeds_usd": net_proceeds,
    }


# ---- 5. death_benefit_split -------------------------------------------


def death_benefit_split(policy, claim, employee):
    total = money(policy["face_amount_usd"] + claim["terminal_dividend_usd"])
    cap = money(total * FAMILY_CAP_PCT)
    multiple = money(employee["annual_salary_usd"] * SURVIVOR_MULTIPLE)
    survivor = min(cap, multiple)
    return {
        "total_death_benefit_usd": total,
        "survivor_entitlement_usd": survivor,
        "bank_portion_usd": money(total - survivor),
    }


def active_allocations(claim_id):
    rows = [
        row
        for row in db.beneficiary_allocations.values()
        if row["claim_id"] == claim_id and row["status"] == "ACTIVE"
    ]
    return ordered(rows)


def allocation_shares(survivor_entitlement, allocations):
    """Round per allocation, then push the single signed residual onto the
    greatest-bps allocation (ties broken by created_at ascending)."""
    shares = []
    running = ZERO
    for allocation in allocations:
        share = money(
            survivor_entitlement * Decimal(allocation["allocation_pct_bps"]) / Decimal(10000)
        )
        shares.append(share)
        running += share
    residual = money(survivor_entitlement - running)
    if allocations:
        target_index = 0
        for index in range(1, len(allocations)):
            if allocations[index]["allocation_pct_bps"] > allocations[target_index]["allocation_pct_bps"]:
                target_index = index
        shares[target_index] = money(shares[target_index] + residual)
    return shares


# ---- 6. valuation_net_yield -------------------------------------------


def valuation_figures(prior_cash_value, credited_interest, me_charge, mva, product):
    cash_value = money(prior_cash_value + credited_interest - me_charge + mva)
    if prior_cash_value == 0:
        net_yield = 0
        me_charge_bps = 0
    else:
        net_yield = to_bps((credited_interest - me_charge) / prior_cash_value * 10000)
        me_charge_bps = to_bps(me_charge / prior_cash_value * 10000)
    return {
        "cash_value_usd": cash_value,
        "net_yield_bps": net_yield,
        "me_charge_bps": me_charge_bps,
        "me_drift_bps": me_charge_bps - int(product["disclosed_me_charge_bps"]),
    }


# ---- 7. risk_assessment_rating ----------------------------------------


def risk_assessment_counts():
    restricted = 0
    watch_list = 0
    for carrier in db.carriers.values():
        if carrier["status"] == "TERMINATED":
            continue
        if carrier["concentration_bps"] > CARRIER_RESTRICT_BPS:
            restricted += 1
        if carrier.get("watch_list_flag"):
            watch_list += 1

    on_watch = 0
    closed = 0
    for product in db.product_types.values():
        if product["status"] == "ON_WATCH":
            on_watch += 1
        elif product["status"] == "CLOSED_TO_NEW":
            closed += 1

    critical = 0
    underfunded = 0
    for plan in db.nqdc_plans.values():
        if plan["status"] == "TERMINATED":
            continue
        view = plan_view(plan, "PBO")
        if view["funding_posture"] == "CRITICAL":
            critical += 1
        elif view["funding_posture"] == "UNDERFUNDED":
            underfunded += 1

    points = (
        restricted * W_RESTRICTED_CARRIER
        + watch_list * W_WATCH_CARRIER
        + on_watch * W_ON_WATCH_PRODUCT
        + closed * W_CLOSED_PRODUCT
        + critical * W_CRITICAL_PLAN
        + underfunded * W_UNDERFUNDED_PLAN
    )
    if points >= SEVERE_MIN_POINTS:
        rating = "SEVERE"
    elif points >= HIGH_MIN_POINTS:
        rating = "HIGH"
    elif points >= MODERATE_MIN_POINTS:
        rating = "MODERATE"
    else:
        rating = "LOW"
    return {
        "restricted_carrier_count": restricted,
        "watch_list_carrier_count": watch_list,
        "on_watch_product_count": on_watch,
        "closed_product_count": closed,
        "critical_plan_count": critical,
        "underfunded_plan_count": underfunded,
        "risk_points": points,
        "risk_rating": rating,
    }


# ---- 8. purchase_request_gating ---------------------------------------


def derive_insurable_interest(employee):
    if (
        employee["annual_salary_usd"] >= INSURABLE_INTEREST_MIN_SALARY_USD
        or employee.get("officer_flag") is True
    ):
        return "ESTABLISHED"
    return "NOT_ESTABLISHED"


def notice_required(single_premium_usd):
    return single_premium_usd > NOTICE_THRESHOLD_USD


# ---- 9. consent_window_conflict ---------------------------------------


def consent_window_conflicts(employee_id, start, end, exclude_id=None):
    from util import add_days

    for record in db.consent_records.values():
        if record["employee_id"] != employee_id:
            continue
        if record["id"] == exclude_id:
            continue
        if record["status"] not in ("DRAFT", "EXECUTED"):
            continue
        existing_start = record["_coverage_start_date"]
        existing_end = record["_coverage_end_date"]
        if start <= add_days(existing_end, CONSENT_GAP_DAYS) and existing_start <= add_days(
            end, CONSENT_GAP_DAYS
        ):
            return True
    return False


# ---- 10. valuation_period_conflict ------------------------------------


def valuation_period_conflicts(policy_id, start, as_of):
    for row in db.policy_valuations.values():
        if row["policy_id"] != policy_id:
            continue
        if start < row["_as_of_date"] and row["_period_start_date"] < as_of:
            return True
    return False
