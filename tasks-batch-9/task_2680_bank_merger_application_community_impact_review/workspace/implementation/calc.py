"""Deterministic arithmetic: rounding, concentration, capital, waiting periods.

Every money figure is a whole-dollar integer (PRD 2.7). Percentages and ratios
are Decimal-rounded half-up to two decimal places; share percentages to four.
"""
from decimal import Decimal, ROUND_HALF_UP

HUNDRED = Decimal("100")
Q2 = Decimal("0.01")
Q4 = Decimal("0.0001")
Q0 = Decimal("1")

# concentration constants
HHI_POST_THRESHOLD_MSA = 1800
HHI_POST_THRESHOLD_RURAL = 2200
HHI_DELTA_SAFE_HARBOR = 200
HHI_PRESUMPTION_LEVEL = 2500
HHI_PRESUMPTION_DELTA = 400
DIVESTITURE_STEP_USD = 1000000

# pro forma capital constants
DTA_ALLOWANCE_PCT = Decimal("0.10")
STRESS_LOSS_RATE = Decimal("0.025")
STRESS_RWA_INFLATION_PCT = Decimal("0.05")
WELL_CAPITALIZED_CET1_PCT = Decimal("7.00")
WELL_CAPITALIZED_LEVERAGE_PCT = Decimal("5.00")
ADEQUATE_CET1_PCT = Decimal("4.50")
ADEQUATE_LEVERAGE_PCT = Decimal("4.00")

# management scoring constants
W_OFFICER = Decimal("0.35")
W_RISK = Decimal("0.30")
W_COMPLIANCE = Decimal("0.175")
W_INTEGRATION = Decimal("0.175")
SATISFACTORY_FLOOR = Decimal("70.00")
CONDITIONAL_FLOOR = Decimal("55.00")

# commitment monitoring constants
QUARTERS_PER_YEAR = 4
DEFICIENCY_THRESHOLD_PCT = Decimal("90.00")
CONSECUTIVE_DEFICIENT_BREACH = 2

# statutory waiting period constants
BASE_WAIT_BANK_DAYS = 15
BASE_WAIT_HOLDCO_DAYS = 30
HEARING_WAIT_ADDITION_DAYS = 15
PROTEST_WAIT_ADDITION_DAYS = 10
EXPEDITED_WAIT_REDUCTION_DAYS = 10
MIN_WAIT_DAYS = 5
CONSUMMATION_DEADLINE_DAYS = 180

# comment window constants
COMMENT_GRACE_DAYS = 3
POST_COMMENT_REVIEW_DAYS = 15
DEFAULT_COMMENT_DURATION_DAYS = 30
HEARING_EXTENSION_DAYS = 30

# branch / conversion constants
CLOSURE_NOTICE_MIN_DAYS = 90
CONVERSION_BUFFER_DAYS = 15
DISCLOSURE_MIN_LEAD_DAYS = 30

INCLUDABLE_BRANCH_STATUSES = ("OPEN", "DESIGNATED_FOR_DIVESTITURE", "DESIGNATED_FOR_CLOSURE")


def r2(value):
    """Round half-up to two decimal places, returned as a float for JSON."""
    return float(Decimal(value).quantize(Q2, rounding=ROUND_HALF_UP))


def d2(value):
    return Decimal(value).quantize(Q2, rounding=ROUND_HALF_UP)


def trunc_dollars(value):
    """Truncate an intermediate dollar amount toward zero (PRD 2.7)."""
    return int(Decimal(value).to_integral_value(rounding="ROUND_DOWN"))


def floor_div(numerator, denominator):
    if denominator == 0:
        return 0
    return int(numerator) // int(denominator)


def pct_2dp(numerator, denominator):
    """numerator / denominator * 100, half-up to two decimals."""
    if denominator == 0:
        return d2(0)
    return d2(Decimal(numerator) / Decimal(denominator) * HUNDRED)


# --------------------------------------------------------------------------
# concentration
# --------------------------------------------------------------------------
def share_pct_4dp(deposits, denominator):
    if denominator == 0:
        return Decimal("0.0000")
    return (Decimal(deposits) / Decimal(denominator) * HUNDRED).quantize(
        Q4, rounding=ROUND_HALF_UP
    )


def hhi_from_deposits(deposit_amounts, denominator):
    """Square each 4dp share percentage, sum, round half-up to an integer."""
    total = Decimal("0")
    for amount in deposit_amounts:
        share = share_pct_4dp(amount, denominator)
        total += share * share
    return int(total.quantize(Q0, rounding=ROUND_HALF_UP))


def market_ceiling(market_type):
    return HHI_POST_THRESHOLD_RURAL if market_type == "RURAL_COUNTY" else HHI_POST_THRESHOLD_MSA


def screen_result_for(hhi_post_unmitigated, hhi_delta_unmitigated, ceiling):
    """PRD 3.5 step 3 — evaluated in this exact order."""
    if hhi_post_unmitigated < ceiling:
        return "PASS"
    if hhi_delta_unmitigated <= HHI_DELTA_SAFE_HARBOR:
        return "PASS"
    if (
        hhi_post_unmitigated >= HHI_PRESUMPTION_LEVEL
        and hhi_delta_unmitigated > HHI_PRESUMPTION_DELTA
    ):
        return "PRESUMPTIVE_VIOLATION"
    return "MITIGATION_REQUIRED"


def clears(index_value, hhi_pre_merger, ceiling):
    return index_value < ceiling or (index_value - hhi_pre_merger) <= HHI_DELTA_SAFE_HARBOR


def required_divestiture(other_deposits, combined_deposits, denominator, hhi_pre_merger, ceiling):
    """PRD 3.5 step 4 — smallest whole million that clears the screen."""
    candidate = DIVESTITURE_STEP_USD
    while candidate <= combined_deposits:
        trial = list(other_deposits) + [combined_deposits - candidate, candidate]
        trial_index = hhi_from_deposits(trial, denominator)
        if clears(trial_index, hhi_pre_merger, ceiling):
            return candidate
        candidate += DIVESTITURE_STEP_USD
    return combined_deposits


SCREEN_SEVERITY = {"PRESUMPTIVE_VIOLATION": 0, "MITIGATION_REQUIRED": 1, "PASS": 2}
POSTURE_SEVERITY = {
    "BLOCKED": 0,
    "MITIGATION_REQUIRED": 1,
    "CLEARED_WITH_DIVESTITURE": 2,
    "CLEARED": 3,
    "NOT_ANALYZED": 4,
}


# --------------------------------------------------------------------------
# management scoring (PRD 3.2)
# --------------------------------------------------------------------------
def management_composite(officer, risk, compliance, integration):
    """Each weighted product is rounded to 2dp BEFORE any addition happens."""
    products = [
        d2(Decimal(int(officer)) * W_OFFICER),
        d2(Decimal(int(risk)) * W_RISK),
        d2(Decimal(int(compliance)) * W_COMPLIANCE),
        d2(Decimal(int(integration)) * W_INTEGRATION),
    ]
    total = products[0]
    for product in products[1:]:
        total = total + product
    return d2(total)


def management_rating(composite):
    composite = Decimal(str(composite))
    if composite >= SATISFACTORY_FLOOR:
        return "SATISFACTORY"
    if composite >= CONDITIONAL_FLOOR:
        return "CONDITIONAL"
    return "UNSATISFACTORY"


# --------------------------------------------------------------------------
# pro forma capital (PRD 3.3)
# --------------------------------------------------------------------------
def pro_forma_ratios(basis, acquirer, target, sched):
    """Return (cet1_pct, leverage_pct, capital_adequacy_flag).

    Every intermediate dollar amount is truncated toward zero before use.
    """
    goodwill = int(sched["goodwill_created_usd"])
    cdi = int(sched["core_deposit_intangible_usd"])
    aoci = int(sched["aoci_markdown_usd"])
    dta = int(sched["deferred_tax_asset_usd"])
    txn_costs = int(sched["transaction_costs_usd"])
    cash = int(sched["cash_consideration_usd"])

    intangibles = goodwill + cdi

    cet1_sum = int(acquirer["cet1_capital_usd"]) + int(target["cet1_capital_usd"])
    tier1_sum = int(acquirer["tier1_capital_usd"]) + int(target["tier1_capital_usd"])
    rwa_sum = int(acquirer["risk_weighted_assets_usd"]) + int(target["risk_weighted_assets_usd"])
    ata_sum = int(acquirer["average_total_assets_usd"]) + int(target["average_total_assets_usd"])

    # the leverage denominator is identical on both bases
    ata_denominator = trunc_dollars(ata_sum - intangibles - cash)

    if basis == "REGULATORY_ADJUSTED":
        pre_deduction_ce = trunc_dollars(cet1_sum - intangibles)
        allowance = trunc_dollars(Decimal(pre_deduction_ce) * DTA_ALLOWANCE_PCT)
        excess_dta = dta - allowance
        if excess_dta < 0:
            excess_dta = 0
        cet1_numerator = trunc_dollars(pre_deduction_ce - txn_costs - excess_dta)
        tier1_numerator = trunc_dollars(tier1_sum - intangibles - txn_costs - excess_dta)
        rwa_denominator = trunc_dollars(rwa_sum - intangibles)
    else:
        credit_mark = trunc_dollars(Decimal(int(target["total_loans_usd"])) * STRESS_LOSS_RATE)
        cet1_numerator = trunc_dollars(
            cet1_sum - intangibles - aoci - dta - txn_costs - credit_mark
        )
        tier1_numerator = trunc_dollars(
            tier1_sum - intangibles - aoci - dta - txn_costs - credit_mark
        )
        inflation = trunc_dollars(
            Decimal(int(target["risk_weighted_assets_usd"])) * STRESS_RWA_INFLATION_PCT
        )
        rwa_denominator = trunc_dollars(rwa_sum - intangibles + inflation)

    cet1_pct = pct_2dp(cet1_numerator, rwa_denominator)
    leverage_pct = pct_2dp(tier1_numerator, ata_denominator)
    return float(cet1_pct), float(leverage_pct), capital_flag(cet1_pct, leverage_pct)


def capital_flag(cet1_pct, leverage_pct):
    cet1_pct = Decimal(str(cet1_pct))
    leverage_pct = Decimal(str(leverage_pct))
    if cet1_pct >= WELL_CAPITALIZED_CET1_PCT and leverage_pct >= WELL_CAPITALIZED_LEVERAGE_PCT:
        return "WELL_CAPITALIZED"
    if cet1_pct >= ADEQUATE_CET1_PCT and leverage_pct >= ADEQUATE_LEVERAGE_PCT:
        return "ADEQUATELY_CAPITALIZED"
    return "UNDERCAPITALIZED"


# --------------------------------------------------------------------------
# statutory waiting period (PRD 3.10)
# --------------------------------------------------------------------------
def expedited_eligible(unresolved_protest_count, hearing_granted, max_hhi_delta, rating):
    return bool(
        int(unresolved_protest_count) == 0
        and not hearing_granted
        and int(max_hhi_delta) <= HHI_DELTA_SAFE_HARBOR
        and rating == "SATISFACTORY"
    )


def waiting_period_days(structure, hearing_granted, unresolved_protest_count, expedited):
    base = BASE_WAIT_HOLDCO_DAYS if structure == "HOLDCO_ACQUISITION" else BASE_WAIT_BANK_DAYS
    days = base
    if hearing_granted:
        days += HEARING_WAIT_ADDITION_DAYS
    if int(unresolved_protest_count) > 0:
        days += PROTEST_WAIT_ADDITION_DAYS
    if expedited:
        days -= EXPEDITED_WAIT_REDUCTION_DAYS
    return days if days > MIN_WAIT_DAYS else MIN_WAIT_DAYS


# --------------------------------------------------------------------------
# commitment targets and fulfilment (PRD 3.9, 3.12)
# --------------------------------------------------------------------------
def line_item_targets(committed_usd, term_years):
    annual = floor_div(committed_usd, term_years)
    final_year = int(committed_usd) - annual * (int(term_years) - 1)
    return annual, final_year


def fulfillment_annual(credited_usd, quarterly_target_total_usd):
    return float(pct_2dp(credited_usd, quarterly_target_total_usd))


def fulfillment_cumulative(cumulative_credited, quarterly_target_total_usd, period_index):
    denominator = int(quarterly_target_total_usd) * int(period_index)
    return float(pct_2dp(cumulative_credited, denominator))


def compliance_status_for(consecutive_deficient_periods):
    run = int(consecutive_deficient_periods)
    if run <= 0:
        return "COMPLIANT"
    if run == 1:
        return "WATCH"
    return "DEFICIENT"
