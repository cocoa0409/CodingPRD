"""Every calculation in SCAFFOLD.calculations / PRD 3.

All money is integer cents.  All rounding is ROUND_HALF_UP -- money to whole
cents (0 dp), scores / percentages / hour aggregates to 2 dp.  No float
arithmetic is used anywhere in this module.
"""

from decimal import Decimal, ROUND_HALF_UP

ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")
CENT = Decimal("1")
TWO_DP = Decimal("0.01")

# PRD 2.8 -- external billing rate card, cents per hour, constant across clients.
GRADE_RATE = {
    "PARTNER": Decimal("92500"),
    "MANAGER": Decimal("57500"),
    "CONSULTANT": Decimal("36500"),
    "ANALYST": Decimal("21500"),
}
GRADES = ("PARTNER", "MANAGER", "CONSULTANT", "ANALYST")

DECISION_PROCESSES = ("SINGLE_APPROVER", "COMMITTEE", "PROCUREMENT_LED")
INDUSTRY_CODES = ("RETAIL", "INDUSTRIAL", "FINSVC", "PUBLIC", "HEALTH")
PRACTICE_CODES = ("OPS", "STRATEGY", "DIGITAL", "RISK")
PRICING_MODELS = ("FIXED_FEE", "TIME_AND_MATERIALS", "OUTCOME_BASED")

QUALIFICATION_THRESHOLD = Decimal("60.00")
DECISION_PROCESS_FACTOR = {
    "SINGLE_APPROVER": Decimal("1.0"),
    "COMMITTEE": Decimal("0.8"),
    "PROCUREMENT_LED": Decimal("0.6"),
}
HISTORY_FACTOR_DIVISOR = Decimal("3")

DISCOUNT_TIER_1_MIN_HOURS = Decimal("200")
DISCOUNT_TIER_2_MIN_HOURS = Decimal("500")
DISCOUNT_TIER_1_PCT = Decimal("0.05")
DISCOUNT_TIER_2_PCT = Decimal("0.10")

RISK_PRICING_COMPONENT = {
    "FIXED_FEE": 25,
    "TIME_AND_MATERIALS": 10,
    "OUTCOME_BASED": 40,
}
RISK_DECISION_COMPONENT = {
    "SINGLE_APPROVER": 5,
    "COMMITTEE": 15,
    "PROCUREMENT_LED": 20,
}
SPECIFICATION_BASE_POINTS = 20
SPECIFICATION_POINTS_PER_STATEMENT = 4
DEPENDENCY_POINTS_PER_LINK = 5
DEPENDENCY_POINTS_CAP = 15
OBLIGATION_POINTS_PER_RESPONSIBILITY = 3
OBLIGATION_POINTS_CAP = 15
RISK_TIER_MEDIUM_MIN = 30
RISK_TIER_HIGH_MIN = 60
RISK_PREMIUM_PCT = {
    "LOW": Decimal("0.05"),
    "MEDIUM": Decimal("0.12"),
    "HIGH": Decimal("0.20"),
}
T_AND_M_NTE_MULTIPLIER = {
    "LOW": Decimal("1.05"),
    "MEDIUM": Decimal("1.10"),
    "HIGH": Decimal("1.15"),
}
OUTCOME_FIXED_SHARE = Decimal("0.70")
OUTCOME_FEE_CAP_PCT = Decimal("0.35")
OUTCOME_BENEFIT_SHARE_PCT = Decimal("0.20")

BLENDED_FORECAST_COST_RATE_CENTS_PER_HOUR = Decimal("34000")
OVERRUN_VARIANCE_PCT = Decimal("30.00")
OVERRUN_MARGIN_PCT = Decimal("0.00")
AT_RISK_VARIANCE_PCT = Decimal("15.00")
AT_RISK_MARGIN_PCT = Decimal("15.00")

LEADERSHIP_ROUTING_PCT = Decimal("20.00")
MATERIALITY_CEILING_PCT = Decimal("40.00")

DELIVERY_WEIGHT = Decimal("0.40")
VALUE_WEIGHT = Decimal("0.35")
COMMUNICATION_WEIGHT = Decimal("0.25")
REFERRAL_BONUS_POINTS = Decimal("0.25")
CSAT_MAX = Decimal("10.00")
FOLLOW_ON_MIN_CSAT = Decimal("7.50")

MAX_CONCURRENT_LEAD_DELIVERABLES = 2
TIMESHEET_HOURS_MAX = Decimal("60.00")


def D(value):
    if isinstance(value, Decimal):
        return value
    if value is None:
        return ZERO
    return Decimal(str(value))


def rc(value):
    """Round half up to whole cents; returns int."""
    return int(D(value).quantize(CENT, rounding=ROUND_HALF_UP))


def r2(value):
    """Round half up to 2 decimal places; returns Decimal."""
    return D(value).quantize(TWO_DP, rounding=ROUND_HALF_UP)


# ------------------------------------------------------------------ 1. qualification_score


def qualification_score(opportunity, client, budget_basis_cents):
    factor = DECISION_PROCESS_FACTOR[client["decision_process"]]
    estimated = D(opportunity["estimated_value_cents"])
    budget_ratio = D(budget_basis_cents) / estimated
    if budget_ratio > ONE:
        budget_ratio = ONE
    sponsor = ONE if opportunity["decision_maker_identified"] else ZERO
    history = D(client["completed_engagement_count"]) / HISTORY_FACTOR_DIVISOR
    if history > ONE:
        history = ONE
    raw = (
        Decimal("30") * factor
        + Decimal("40") * budget_ratio
        + Decimal("20") * sponsor
        + Decimal("10") * history
    )
    return r2(raw)


# ------------------------------------------------------------------ 2. scope_baseline_cost


def scope_discount_for_hours(total_hours):
    total = D(total_hours)
    if total < DISCOUNT_TIER_1_MIN_HOURS:
        return Decimal("0.00")
    if total < DISCOUNT_TIER_2_MIN_HOURS:
        return DISCOUNT_TIER_1_PCT
    return DISCOUNT_TIER_2_PCT


def line_cost_cents(effort_hours, grade, discount_pct):
    return rc(D(effort_hours) * GRADE_RATE[grade] * (ONE - D(discount_pct)))


def longest_dependency_chain(deliverables):
    """Node count of the longest depends_on path inside one opportunity."""
    by_id = {d["id"]: d for d in deliverables}
    memo = {}

    def depth(did, seen):
        if did in memo:
            return memo[did]
        if did in seen:
            return 0
        seen = seen | {did}
        row = by_id.get(did)
        parent = row.get("depends_on_deliverable_id") if row else None
        if parent is None or parent not in by_id:
            value = 1
        else:
            value = 1 + depth(parent, seen)
        memo[did] = value
        return value

    best = 0
    for d in deliverables:
        value = depth(d["id"], frozenset())
        if value > best:
            best = value
    return best


def has_dependency_cycle(deliverables):
    by_id = {d["id"]: d for d in deliverables}
    state = {}

    def visit(did):
        mark = state.get(did)
        if mark == 1:
            return True
        if mark == 2:
            return False
        state[did] = 1
        row = by_id.get(did)
        parent = row.get("depends_on_deliverable_id") if row else None
        if parent is not None and parent in by_id:
            if visit(parent):
                return True
        state[did] = 2
        return False

    for d in deliverables:
        if visit(d["id"]):
            return True
    return False


# ------------------------------------------------------------------ 3. engagement_risk_score


def engagement_risk_score(pricing_model, client, opportunity):
    pricing_component = RISK_PRICING_COMPONENT[pricing_model]
    decision_component = RISK_DECISION_COMPONENT[client["decision_process"]]
    statements = len(opportunity.get("assumptions") or []) + len(
        opportunity.get("exclusions") or []
    )
    specification_component = max(
        0, SPECIFICATION_BASE_POINTS - SPECIFICATION_POINTS_PER_STATEMENT * statements
    )
    chain = opportunity.get("longest_dependency_chain") or 0
    dependency_component = min(DEPENDENCY_POINTS_CAP, DEPENDENCY_POINTS_PER_LINK * chain)
    obligations = len(opportunity.get("client_responsibilities") or [])
    obligation_component = min(
        OBLIGATION_POINTS_CAP, OBLIGATION_POINTS_PER_RESPONSIBILITY * obligations
    )
    return min(
        100,
        pricing_component
        + decision_component
        + specification_component
        + dependency_component
        + obligation_component,
    )


def risk_tier(risk_score):
    if risk_score < RISK_TIER_MEDIUM_MIN:
        return "LOW"
    if risk_score < RISK_TIER_HIGH_MIN:
        return "MEDIUM"
    return "HIGH"


# ------------------------------------------------------------------ 4. sow_quoted_fee


def sow_quoted_fee(pricing_model, baseline_cost_cents, risk_premium_pct, tier, target_bonus_cents):
    B = D(baseline_cost_cents)
    risk_loaded_cents = rc(B * (ONE + D(risk_premium_pct)))
    out = {
        "risk_loaded_cents": risk_loaded_cents,
        "fixed_component_cents": 0,
        "at_risk_component_cents": 0,
        "not_to_exceed_cents": None,
        "quoted_fee_cents": 0,
    }
    if pricing_model == "FIXED_FEE":
        out["fixed_component_cents"] = risk_loaded_cents
        out["at_risk_component_cents"] = 0
        out["not_to_exceed_cents"] = None
        out["quoted_fee_cents"] = risk_loaded_cents
    elif pricing_model == "TIME_AND_MATERIALS":
        nte = rc(B * T_AND_M_NTE_MULTIPLIER[tier])
        out["fixed_component_cents"] = 0
        out["at_risk_component_cents"] = 0
        out["not_to_exceed_cents"] = nte
        out["quoted_fee_cents"] = nte
    else:  # OUTCOME_BASED
        fixed = rc(B * OUTCOME_FIXED_SHARE)
        uncapped = risk_loaded_cents - fixed
        risk_loaded_cap = rc(D(risk_loaded_cents) * OUTCOME_FEE_CAP_PCT)
        benefit_cap = rc(D(target_bonus_cents) * OUTCOME_BENEFIT_SHARE_PCT)
        at_risk = min(uncapped, risk_loaded_cap, benefit_cap)
        out["fixed_component_cents"] = fixed
        out["at_risk_component_cents"] = at_risk
        out["not_to_exceed_cents"] = None
        out["quoted_fee_cents"] = fixed + at_risk
    return out


# ------------------------------------------------------------------ 5. time_entry_costing


def time_entry_costing(hours, consultant, pinned_scope_discount_pct, billable):
    cost = rc(D(hours) * D(consultant["cost_rate_cents_per_hour"]))
    if billable:
        billed = rc(
            D(hours) * GRADE_RATE[consultant["grade"]] * (ONE - D(pinned_scope_discount_pct))
        )
    else:
        billed = 0
    return cost, billed


# ------------------------------------------------------------------ 6. engagement_economics


def engagement_economics(engagement, accepted_weight_sum):
    contracted_hours = D(engagement["contracted_hours"])
    burned_hours = D(engagement["approved_hours_burned"])
    if contracted_hours == ZERO:
        hours_burn_pct = Decimal("0.00")
    else:
        hours_burn_pct = r2(HUNDRED * burned_hours / contracted_hours)
    completion_pct = r2(accepted_weight_sum)
    progress_variance_pct = r2(hours_burn_pct - completion_pct)
    remaining = contracted_hours - burned_hours
    if remaining < ZERO:
        remaining = ZERO
    projected_cost_cents = int(engagement["burned_cost_cents"]) + rc(
        remaining * BLENDED_FORECAST_COST_RATE_CENTS_PER_HOUR
    )
    fee = D(engagement["contracted_fee_cents"])
    if fee == ZERO:
        projected_margin_pct = Decimal("0.00")
    else:
        projected_margin_pct = r2(HUNDRED * (fee - D(projected_cost_cents)) / fee)
    if progress_variance_pct >= OVERRUN_VARIANCE_PCT or projected_margin_pct < OVERRUN_MARGIN_PCT:
        state = "OVERRUN"
    elif progress_variance_pct >= AT_RISK_VARIANCE_PCT or projected_margin_pct < AT_RISK_MARGIN_PCT:
        state = "AT_RISK"
    else:
        state = "ON_TRACK"
    return {
        "hours_burn_pct": hours_burn_pct,
        "completion_pct": completion_pct,
        "progress_variance_pct": progress_variance_pct,
        "projected_cost_cents": projected_cost_cents,
        "projected_margin_pct": projected_margin_pct,
        "economics_state": state,
    }


# ------------------------------------------------------------------ 7. change_request_impact


def change_request_impact(
    added_hours, added_grade, pinned_scope_discount_pct, pinned_risk_premium_pct,
    approved_delta_sum, original_fee_cents,
):
    gross = rc(D(added_hours) * GRADE_RATE[added_grade] * (ONE - D(pinned_scope_discount_pct)))
    fee_delta = rc(D(gross) * (ONE + D(pinned_risk_premium_pct)))
    original = D(original_fee_cents)
    if original == ZERO:
        cumulative = Decimal("0.00")
    else:
        cumulative = r2(HUNDRED * (D(approved_delta_sum) + D(fee_delta)) / original)
    return gross, fee_delta, cumulative


def routing_for(cumulative_pct):
    return (
        "LEADERSHIP_THEN_CLIENT"
        if D(cumulative_pct) >= LEADERSHIP_ROUTING_PCT
        else "CLIENT_ONLY"
    )


# ------------------------------------------------------------------ 8. satisfaction_csat


def satisfaction_csat(delivery_score, value_score, communication_score, would_refer):
    raw = (
        DELIVERY_WEIGHT * D(delivery_score)
        + VALUE_WEIGHT * D(value_score)
        + COMMUNICATION_WEIGHT * D(communication_score)
        + (REFERRAL_BONUS_POINTS if would_refer else ZERO)
    )
    if raw > CSAT_MAX:
        raw = CSAT_MAX
    return r2(raw)


# ------------------------------------------------------------------ 9. consultant_lead_load


def windows_overlap(start_a, end_a, start_b, end_b):
    """Half-open [start, end) overlap test."""
    return start_a < end_b and start_b < end_a
