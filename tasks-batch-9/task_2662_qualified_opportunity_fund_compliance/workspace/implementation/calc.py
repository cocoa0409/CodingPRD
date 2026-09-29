"""The calculation engine (SCAFFOLD calculations / PRD section 2.6-2.7).

Every money figure is 2 dp ROUND_HALF_UP, every percentage 4 dp ROUND_HALF_UP,
and thresholds always compare the already-rounded value.
"""

from datetime import timedelta
from decimal import Decimal

from core import (
    ZERO2, ZERO4, add_months, dec, now_logical, q2, q4, rows, whole_days,
)

DEFERRAL_WINDOW_DAYS = 180
QUALIFIED_ASSET_MIN_PCT = Decimal("90.0000")
SHORTFALL_TARGET_RATIO = Decimal("0.90")
GROSS_INCOME_MIN_PCT = Decimal("50.0000")
INTANGIBLES_MIN_PCT = Decimal("40.0000")
NQFP_MAX_PCT = Decimal("5.0000")
MGMT_SAFE_HARBOR_CREDIT = Decimal("1.25")
SI_WINDOW_MONTHS = 30
SI_REQUIRED_PCT = Decimal("100.0000")
WCSH_WINDOW_MONTHS = 31
WCSH_PACING_TOLERANCE_PCT = Decimal("10.0")
WCSH_AGGREGATE_CAP_PCT = Decimal("0.31")
UNDERPAYMENT_ANNUAL_RATE = Decimal("0.08")
CURE_CREDIT_TIER_BREAK = Decimal("1000.00")
CURE_CREDIT_HIGH_CAP_PCT = Decimal("0.60")
CURE_CREDIT_LOW_CAP_PCT = Decimal("0.40")
CURE_CREDIT_FLOOR = Decimal("250.00")
FIVE_YEAR_DAYS = 1826
SEVEN_YEAR_DAYS = 2557
TEN_YEAR_DAYS = 3653
HUNDRED = Decimal("100")


# ---------------------------------------------------------------------------
# eligible_gain_investment_deadline
# ---------------------------------------------------------------------------

def window_basis_date(deadline_basis, realization_date, pass_through_year_end):
    if deadline_basis == "SALE_DATE":
        return realization_date
    return pass_through_year_end


def investment_deadline(basis_date):
    return basis_date + timedelta(days=DEFERRAL_WINDOW_DAYS)


def days_from_basis(investment_date, basis_date):
    return whole_days(investment_date, basis_date)


# ---------------------------------------------------------------------------
# semiannual_asset_test_ratio
# ---------------------------------------------------------------------------

def asset_test_included(fund_id, period_end):
    def keep(a):
        if a["fund_id"] != fund_id:
            return False
        if a["status"] not in ("HELD", "IMPROVING"):
            return False
        if not a["acquisition_date"] < period_end:
            return False
        if a["disposed_at"] is not None and not a["disposed_at"] >= period_end:
            return False
        return True
    return rows("fund_assets", keep)


def asset_value(asset, valuation_method):
    if valuation_method == "UNADJUSTED_COST_BASIS":
        return asset["unadjusted_cost_basis"]
    return asset["afs_fair_value"]


def asset_test_ratio(test):
    included = asset_test_included(test["fund_id"], test["period_end"])
    method = test["valuation_method"]
    total = q2(sum((asset_value(a, method) for a in included), ZERO2))
    qualified = q2(sum((asset_value(a, method) for a in included
                        if a["qualification"] == "QUALIFIED"), ZERO2))
    if total == ZERO2:
        ratio = ZERO4
    else:
        ratio = q4(qualified / total * HUNDRED)
    result = "PASS" if ratio >= QUALIFIED_ASSET_MIN_PCT else "FAIL"
    if result == "PASS":
        shortfall = ZERO2
        failed_months = 0
    else:
        shortfall = q2(SHORTFALL_TARGET_RATIO * total - qualified)
        md = test["measurement_date"]
        ps = test["period_start"]
        failed_months = ((md.year - ps.year) * 12
                         + (md.month - ps.month)
                         + (1 if md.day >= ps.day else 0))
    return {
        "qualified_numerator": qualified,
        "total_denominator": total,
        "ratio_pct": ratio,
        "included_asset_count": len(included),
        "result": result,
        "shortfall_amount": shortfall,
        "failed_month_count": failed_months,
    }


# ---------------------------------------------------------------------------
# qozb_prong_evaluation
# ---------------------------------------------------------------------------

def prong_evaluation(test, live_nqfp_amount):
    harbor = test["safe_harbor_used"]
    int_zone = test["intangibles_zone_use_amount"]
    int_total = test["intangibles_total_amount"]
    total_assets = test["total_asset_value_measured"]
    nqfp_measured = q2(live_nqfp_amount)

    if int_total == ZERO2:
        intangibles_pct = ZERO4
    else:
        intangibles_pct = q4(int_zone / int_total * HUNDRED)

    if harbor == "FIFTY_PCT_HOURS":
        gross_income_pct = q4(test["hours_zone_pct"])
    elif harbor == "FIFTY_PCT_AMOUNTS_PAID":
        gross_income_pct = q4(test["amounts_paid_zone_pct"])
    elif harbor == "GROSS_INCOME_ACTUAL":
        gi_total = test["gross_income_total_amount"]
        if gi_total == ZERO2:
            gross_income_pct = ZERO4
        else:
            gross_income_pct = q4(test["gross_income_zone_amount"] / gi_total * HUNDRED)
    else:  # MANAGEMENT_AND_TANGIBLE
        mgmt = ZERO4 if int_total == ZERO2 else q4(int_zone / int_total * HUNDRED)
        tangible = q4((total_assets - nqfp_measured) / total_assets * HUNDRED)
        composite = q4(min(mgmt, tangible) * MGMT_SAFE_HARBOR_CREDIT)
        gross_income_pct = min(Decimal("100.0000"), composite)

    nqfp_pct = q4(nqfp_measured / total_assets * HUNDRED)

    return {
        "nqfp_amount_measured": nqfp_measured,
        "gross_income_pct": gross_income_pct,
        "intangibles_pct": intangibles_pct,
        "nqfp_pct": nqfp_pct,
        "gross_income_prong": "PASS" if gross_income_pct >= GROSS_INCOME_MIN_PCT else "FAIL",
        "intangibles_prong": "PASS" if intangibles_pct >= INTANGIBLES_MIN_PCT else "FAIL",
        "nqfp_prong": "PASS" if nqfp_pct <= NQFP_MAX_PCT else "FAIL",
    }


# ---------------------------------------------------------------------------
# substantial_improvement_ratio
# ---------------------------------------------------------------------------

def improvement_window_end(window_start):
    return add_months(window_start, SI_WINDOW_MONTHS)


def project_additions(project):
    def keep(e):
        return (e["improvement_project_id"] == project["id"]
                and e["expenditure_kind"] == "CAPITALIZED_IMPROVEMENT"
                and project["window_start"] <= e["spend_date"] < project["window_end"])
    return q2(sum((e["amount"] for e in rows("capital_expenditures", keep)), ZERO2))


def improvement_group(project):
    members = rows("improvement_projects", lambda p: (
        p["aggregation_method"] == "AGGREGATED_GROUP"
        and p["group_key"] == project["group_key"]
        and p["status"] in ("OPEN", "SATISFIED")))
    members.sort(key=lambda p: (p["window_start"], p["_seq"]))
    return members


def improvement_ratio(project):
    if project["aggregation_method"] == "ASSET_BY_ASSET":
        additions = project_additions(project)
        denominator = project["basis_at_acquisition"]
    else:
        group = improvement_group(project)
        additions = q2(sum((project_additions(p) for p in group), ZERO2))
        denominator = q2(sum((p["basis_at_acquisition"] for p in group), ZERO2))
    if denominator == ZERO2:
        ratio = ZERO4
    else:
        ratio = q4(additions / denominator * HUNDRED)
    return {"qualified_additions_total": additions, "improvement_ratio_pct": ratio}


def improvement_outcome(ratio_pct, window_end):
    clock = now_logical()
    if ratio_pct >= SI_REQUIRED_PCT and clock < window_end:
        return "SATISFIED"
    if ratio_pct < SI_REQUIRED_PCT and clock >= window_end:
        return "LAPSED"
    return "OPEN"


# ---------------------------------------------------------------------------
# wcsh_pacing_compliance
# ---------------------------------------------------------------------------

def wcsh_window_end(window_start):
    return add_months(window_start, WCSH_WINDOW_MONTHS)


def wcsh_eligible_spends(plan):
    def keep(e):
        return (e["wcsh_plan_id"] == plan["id"]
                and e["expenditure_kind"] in ("OPERATING_WORKING_CAPITAL",
                                              "CAPITALIZED_IMPROVEMENT")
                and plan["window_start"] <= e["spend_date"] < plan["window_end"])
    spends = rows("capital_expenditures", keep)
    spends.sort(key=lambda e: (e["spend_date"], e["_seq"]))
    return spends


def wcsh_waterfall(plan):
    """Run the waterfall; writes schedule_month_index onto each eligible spend."""
    spends = wcsh_eligible_spends(plan)
    buckets = sorted(plan["spend_schedule"], key=lambda b: b["month_index"])
    filled = dict((b["month_index"], ZERO2) for b in buckets)
    overspill = ZERO2
    for spend in spends:
        remaining = spend["amount"]
        reached = None
        for bucket in buckets:
            idx = bucket["month_index"]
            room = q2(bucket["planned_amount"] - filled[idx])
            take = min(remaining, room)
            if take > ZERO2:
                filled[idx] = q2(filled[idx] + take)
                remaining = q2(remaining - take)
                reached = idx
            if remaining == ZERO2:
                break
        spend["schedule_month_index"] = reached
        overspill = q2(overspill + remaining)
    spent_total = q2(sum((e["amount"] for e in spends), ZERO2))
    unspent = max(ZERO2, q2(plan["covered_amount"] - spent_total))
    return {
        "filled": filled,
        "buckets": buckets,
        "overspill_amount": overspill,
        "spent_total": spent_total,
        "unspent_amount": unspent,
        "spends": spends,
    }


def wcsh_checkpoint(plan, month_index):
    run = wcsh_waterfall(plan)
    buckets = run["buckets"]
    filled = run["filled"]
    required = q2(sum((b["planned_amount"] for b in buckets
                       if b["month_index"] <= month_index), ZERO2))
    actual = q2(sum((filled[b["month_index"]] for b in buckets
                     if b["month_index"] <= month_index), ZERO2))
    shortfall = max(ZERO2, q2(required - actual))
    tolerance = q2(required * WCSH_PACING_TOLERANCE_PCT / HUNDRED)
    if shortfall > tolerance:
        status = "BLOWN"
    elif month_index >= plan["schedule_month_count"] and shortfall == ZERO2:
        status = "COMPLETED"
    else:
        status = "ACTIVE"
    run["pacing_shortfall"] = shortfall
    run["tolerance"] = tolerance
    run["status"] = status
    run["last_checkpoint_month_index"] = month_index
    return run


# ---------------------------------------------------------------------------
# failed_test_penalty / penalty_cure_credit_netting
# ---------------------------------------------------------------------------

def failed_test_penalty(shortfall_amount, failed_month_count):
    monthly = q2(shortfall_amount * UNDERPAYMENT_ANNUAL_RATE / Decimal(12))
    gross = q2(monthly * Decimal(failed_month_count))
    return {
        "monthly_penalty_amount": monthly,
        "gross_penalty_amount": gross,
        "cure_credit_amount": ZERO2,
        "net_penalty_amount": q2(gross - ZERO2),
    }


def cure_credit(gross):
    tier_basis = gross
    cap_pct = (CURE_CREDIT_HIGH_CAP_PCT if tier_basis >= CURE_CREDIT_TIER_BREAK
               else CURE_CREDIT_LOW_CAP_PCT)
    credit = q2(min(gross, max(CURE_CREDIT_FLOOR, q2(cap_pct * tier_basis))))
    return {"cure_credit_amount": credit, "net_penalty_amount": q2(gross - credit)}


# ---------------------------------------------------------------------------
# inclusion_event_amount / ten_year_step_up_grant
# ---------------------------------------------------------------------------

def holding_tier(holding_days):
    if holding_days >= TEN_YEAR_DAYS:
        return "TEN_YEAR"
    if holding_days >= SEVEN_YEAR_DAYS:
        return "SEVEN_YEAR"
    if holding_days >= FIVE_YEAR_DAYS:
        return "FIVE_YEAR"
    return "UNDER_FIVE"


def step_up_pct(tier):
    if tier in ("SEVEN_YEAR", "TEN_YEAR"):
        return Decimal("0.15")
    if tier == "FIVE_YEAR":
        return Decimal("0.10")
    return Decimal("0.00")


def inclusion_amounts(election, included_fraction, event_date):
    holding_days = whole_days(event_date, election["investment_date"])
    tier = holding_tier(holding_days)
    pct = step_up_pct(tier)
    elected = election["elected_amount"]
    gross = q2(elected * included_fraction)
    offset = q2(elected * included_fraction * pct)
    net = q2(gross - offset)
    is_full = q4(election["included_fraction_total"] + included_fraction) == Decimal("1.0000")
    return {
        "holding_days": holding_days,
        "holding_tier_applied": tier,
        "gross_inclusion_amount": gross,
        "basis_offset_amount": offset,
        "net_inclusion_amount": net,
        "is_full": is_full,
    }
