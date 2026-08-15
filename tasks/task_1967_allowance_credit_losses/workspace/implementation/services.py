"""Business logic, calculations, and shared helpers for the CECL Allowance API."""

import uuid
from decimal import Decimal, ROUND_HALF_UP

import db
from errors import ApiError, ERR_NOT_FOUND
from response import make_timestamp
from validation import quarter_index

# ---------------------------------------------------------------------------
# Constants (from the scaffold calculation tables)
# ---------------------------------------------------------------------------
INDIVIDUAL_EVAL_THRESHOLD_CENTS = 100000000
WATCH_RATE_THRESHOLD_BPS = 200
BASE_RATE_BY_BAND = {
    "PRIME": 50,
    "NEAR_PRIME": 150,
    "SUBPRIME": 400,
    "DEEP_SUBPRIME": 900,
}
U_NEUTRAL_BPS = 500
SENS_U = 20
GDP_NEUTRAL_BPS = 200
SENS_G = 10
MIN_MULT_BPS = 5000
MAX_MULT_BPS = 30000
REMAINING_LIFE_QUARTERS = 8
COST_TO_SELL_BPS = 1000
CAP_PERCENT = Decimal("0.10")
BREACH_VARIANCE_THRESHOLD_BPS = 150
BREACH_COUNT_THRESHOLD = 2

IN_FLIGHT_RUN_STATUSES = ("DRAFT", "EXECUTED", "UNDER_REVIEW", "APPROVED")

RISK_BANDS = ("PRIME", "NEAR_PRIME", "SUBPRIME", "DEEP_SUBPRIME")
PRODUCT_TYPES = ("CREDIT_CARD", "AUTO", "MORTGAGE", "SMALL_BUSINESS", "PERSONAL")
RISK_RATINGS = ("PASS", "SPECIAL_MENTION", "SUBSTANDARD", "DOUBTFUL", "LOSS")
SCENARIO_TYPES = ("BASELINE", "ADVERSE", "OPTIMISTIC")
FACTOR_CODES = (
    "CONCENTRATION_RISK",
    "POLICY_CHANGE",
    "ECONOMIC_UNCERTAINTY",
    "COLLATERAL_VALUATION",
    "MODEL_LIMITATION",
)
MODEL_METHODS = ("LOSS_RATE", "DISCOUNTED_CASH_FLOW", "VINTAGE")
REVERSION_METHODS = ("IMMEDIATE", "STRAIGHT_LINE")
EVAL_METHODS = ("COLLATERAL_FAIR_VALUE", "DISCOUNTED_CASH_FLOW")
INDIVIDUAL_RATINGS = ("SUBSTANDARD", "DOUBTFUL", "LOSS")


def round_half_up_int(value):
    """Round a Decimal to the nearest integer, half away from zero."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def new_id():
    return str(uuid.uuid4())


def touch(resource):
    """Refresh updated_at and bump version (common-field resources only)."""
    resource["updated_at"] = make_timestamp()
    resource["version"] = resource.get("version", 0) + 1


def stamp_new(resource, with_version=True):
    now = make_timestamp()
    resource["id"] = new_id()
    resource["created_at"] = now
    if with_version:
        resource["updated_at"] = now
        resource["version"] = 1
    resource["_seq"] = db.next_creation_seq()
    return resource


def get_or_404(collection, resource_id, label):
    resource = collection.get(resource_id)
    if resource is None:
        raise ApiError(ERR_NOT_FOUND, 404, "%s not found: %s" % (label, resource_id))
    return resource


def public(resource):
    """Strip internal bookkeeping keys from a stored resource dict."""
    return {k: v for k, v in resource.items() if not k.startswith("_")}


def compute_individually_evaluated(risk_rating, amortized_cost_cents):
    return risk_rating in INDIVIDUAL_RATINGS or (
        amortized_cost_cents >= INDIVIDUAL_EVAL_THRESHOLD_CENTS
    )


def recompute_segment_rate(segment):
    """Recompute charge_off_rate_bps; returns the new rate (int bps)."""
    if segment["origination_total_cents"] == 0:
        segment["charge_off_rate_bps"] = 0
        return 0
    net = segment["ytd_gross_charge_offs_cents"] - segment["ytd_recoveries_cents"]
    rate = round_half_up_int(
        (Decimal(net) * Decimal(10000)) / Decimal(segment["origination_total_cents"])
    )
    segment["charge_off_rate_bps"] = rate
    return rate


def flag_draft_runs_for_segmentation_review():
    for run in db.runs.values():
        if run["status"] == "DRAFT":
            if not run.get("needs_segmentation_review"):
                run["needs_segmentation_review"] = True
            touch(run)


# ---------------------------------------------------------------------------
# Economic scenario multiplier and quantitative reserve
# ---------------------------------------------------------------------------

def scenario_mult_bps(scenario):
    """Exact integer multiplier in bps, clamped last."""
    mult = (
        10000
        + (scenario["unemployment_rate_bps"] - U_NEUTRAL_BPS) * SENS_U
        + (GDP_NEUTRAL_BPS - scenario["gdp_growth_bps"]) * SENS_G
    )
    if mult < MIN_MULT_BPS:
        mult = MIN_MULT_BPS
    if mult > MAX_MULT_BPS:
        mult = MAX_MULT_BPS
    return mult


def blended_multiplier(scenario_weights):
    """Exact decimal blended multiplier M per the single/weighted variants."""
    if len(scenario_weights) == 1:
        entry = scenario_weights[0]
        scenario = db.scenarios[entry["scenario_id"]]
        return Decimal(scenario_mult_bps(scenario)) / Decimal(10000)
    total = 0
    for entry in scenario_weights:
        scenario = db.scenarios[entry["scenario_id"]]
        total += entry["weight_bps"] * scenario_mult_bps(scenario)
    return Decimal(total) / Decimal(10000) / Decimal(10000)


def effective_multiplier(model, M):
    """Exact decimal effective horizon multiplier E over the 8-quarter life."""
    L = REMAINING_LIFE_QUARTERS
    F = model["forecast_period_quarters"]
    R = model["reversion_period_quarters"]
    one = Decimal(1)
    if model["reversion_method"] == "IMMEDIATE":
        return (Decimal(F) * M + Decimal(L - F) * one) / Decimal(L)
    # STRAIGHT_LINE
    rev = Decimal(0)
    for i in range(1, R + 1):
        rev += M - (M - one) * Decimal(i) / Decimal(R + 1)
    return (Decimal(F) * M + rev + Decimal(L - F - R) * one) / Decimal(L)


def compute_quantitative_reserve(model, segment, exposure_cents, M):
    """Returns (lifetime_loss_rate_bps, quantitative_reserve_cents)."""
    base = BASE_RATE_BY_BAND[segment["risk_rating_band"]]
    E = effective_multiplier(model, M)
    lifetime_rate = round_half_up_int(Decimal(base) * E)
    reserve = round_half_up_int(
        (Decimal(exposure_cents) * Decimal(lifetime_rate)) / Decimal(10000)
    )
    return lifetime_rate, reserve


def compute_qualitative_adjustment(segment, as_of_period, exposure_cents, quant_reserve):
    """Returns (qualitative_bps, qualitative_adjustment_cents) with the floor."""
    run_idx = quarter_index(as_of_period)
    q_bps = 0
    for factor in db.factors.values():
        if factor["segment_id"] != segment["id"]:
            continue
        if factor["status"] != "APPROVED":
            continue
        if quarter_index(factor["effective_from_period"]) <= run_idx <= quarter_index(
            factor["effective_to_period"]
        ):
            q_bps += factor["adjustment_bps"]
    q_cents = round_half_up_int(
        (Decimal(exposure_cents) * Decimal(q_bps)) / Decimal(10000)
    )
    if quant_reserve + q_cents < 0:
        q_cents = -quant_reserve
    return q_bps, q_cents


# ---------------------------------------------------------------------------
# Individual evaluation specific reserve
# ---------------------------------------------------------------------------

def compute_specific_reserve(evaluation, loan_amortized_cost_cents):
    if evaluation["method"] == "COLLATERAL_FAIR_VALUE":
        collateral = evaluation["collateral_value_cents"]
        haircut = round_half_up_int(
            (Decimal(collateral) * Decimal(COST_TO_SELL_BPS)) / Decimal(10000)
        )
        net_collateral = collateral - haircut
        reserve = loan_amortized_cost_cents - net_collateral
        return reserve if reserve > 0 else 0
    # DISCOUNTED_CASH_FLOW
    r = Decimal(evaluation["discount_rate_bps"]) / Decimal(10000)
    pv = Decimal(0)
    for t, cf in enumerate(evaluation["expected_quarterly_cash_flows_cents"], start=1):
        pv += Decimal(cf) / ((Decimal(1) + r) ** t)
    pv_rounded = round_half_up_int(pv)
    reserve = loan_amortized_cost_cents - pv_rounded
    return reserve if reserve > 0 else 0


# ---------------------------------------------------------------------------
# Run totals
# ---------------------------------------------------------------------------

def resync_run_totals(run):
    """Re-derive individual/management components and the total allowance."""
    individual = sum(
        ev["specific_reserve_cents"]
        for ev in db.evaluations.values()
        if ev["run_id"] == run["id"]
    )
    management = sum(
        adj["amount_cents"]
        for adj in db.adjustments.values()
        if adj["run_id"] == run["id"] and adj["status"] == "APPROVED"
    )
    run["individual_reserve_cents"] = individual
    run["management_adjustment_cents"] = management
    run["total_allowance_cents"] = (
        run["quantitative_reserve_cents"]
        + run["qualitative_adjustment_cents"]
        + individual
        + management
    )


def recompute_reviewed_count(run):
    count = sum(
        1
        for ev in db.evaluations.values()
        if ev["run_id"] == run["id"] and ev["status"] == "REVIEWED"
    )
    run["reviewed_evaluation_count"] = count
