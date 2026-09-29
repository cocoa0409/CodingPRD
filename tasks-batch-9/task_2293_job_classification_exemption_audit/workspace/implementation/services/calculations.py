"""Back-wage exposure, pay-structure conversion and contractor classification."""
from decimal import Decimal

from constants import (
    ANNUAL_HOURS_DIVISOR,
    ECONOMIC_REALITY_KEYS,
    STANDARD_WORKWEEK_HOURS,
)
from services.derive import (
    duty_view,
    floors_for_state,
    lookback_policy_weeks,
    state_rule_for,
    weekly_salary_cents,
)
from services.numbers import dec, rhu


# ------------------------------------------------------- back-wage exposure
def back_wage_exposure(position, project, method):
    """calculations.back_wage_exposure (PRD 3.8). Rounding order is pinned."""
    st = state_rule_for(position["work_state_code"])
    policy_weeks = lookback_policy_weeks(project)
    override = st["back_wage_lookback_weeks_override"] if st else None
    lookback_weeks = max(policy_weeks, override if override is not None else 0)

    weekly = weekly_salary_cents(position)
    validated_hours = duty_view(position)["validated_weekly_hours"]
    hours = dec(validated_hours)
    ot_hours = hours - STANDARD_WORKWEEK_HOURS
    if ot_hours < 0:
        ot_hours = Decimal(0)

    if ot_hours == 0:
        week_ot_cents = 0
    elif method == "FULL_RATE":
        regular_rate = dec(weekly) / STANDARD_WORKWEEK_HOURS
        week_ot_cents = rhu(ot_hours * regular_rate * Decimal("1.5"))
    else:  # HALF_TIME
        if hours == 0:
            week_ot_cents = 0
        else:
            regular_rate = dec(weekly) / hours
            week_ot_cents = rhu(ot_hours * regular_rate * Decimal("0.5"))

    gross = week_ot_cents * lookback_weeks * position["incumbent_count"]
    multiplier = dec(st["liquidated_damages_multiplier"]) if st else Decimal("0.0")
    liquidated = rhu(dec(gross) * multiplier)
    return {
        "lookback_weeks": lookback_weeks,
        "weekly_ot_hours": ot_hours,
        "week_ot_cents": week_ot_cents,
        "gross_exposure_cents": gross,
        "liquidated_damages_cents": liquidated,
        "total_exposure_cents": gross + liquidated,
    }


# ------------------------------------------------- pay structure conversion
def pay_structure_conversion(position, conversion_method, expected_weekly_hours):
    """calculations.pay_structure_conversion (PRD 3.7). Evaluation order pinned."""
    annual = position["annual_salary_cents"]
    hours = dec(expected_weekly_hours)
    ot_hours = hours - STANDARD_WORKWEEK_HOURS
    if ot_hours < 0:
        ot_hours = Decimal(0)

    if conversion_method == "SALARY_DIV_2080":
        rate = rhu(dec(annual) / Decimal(ANNUAL_HOURS_DIVISOR))
    else:  # COST_NEUTRAL_WITH_OT
        denom_hours = STANDARD_WORKWEEK_HOURS + Decimal("1.5") * ot_hours
        rate = rhu(dec(annual) / (Decimal(52) * denom_hours))

    r = dec(rate)
    projected = rhu(
        Decimal(52)
        * (STANDARD_WORKWEEK_HOURS * r + ot_hours * Decimal("1.5") * r)
    )
    return {
        "converted_hourly_rate_cents": rate,
        "projected_annual_cost_cents": projected,
        "cost_delta_cents": projected - annual,
    }


# ------------------------------------------------- contractor classification
def contractor_required_inputs_present(review, applied_ic_test):
    if applied_ic_test == "ABC":
        return all(
            review[key] is not None
            for key in ("free_from_control", "outside_usual_course", "independent_trade")
        )
    if applied_ic_test == "ECONOMIC_REALITY":
        factors = review["economic_reality_factors"]
        if not isinstance(factors, dict):
            return False
        return all(isinstance(factors.get(key), bool) for key in ECONOMIC_REALITY_KEYS)
    return all(
        review[key] is not None
        for key in (
            "behavioral_control_score",
            "financial_control_score",
            "relationship_score",
        )
    )


def contractor_classification(review, applied_ic_test):
    """calculations.contractor_classification (PRD 3.9)."""
    if applied_ic_test == "ABC":
        outcome = (
            "CONTRACTOR"
            if (
                review["free_from_control"]
                and review["outside_usual_course"]
                and review["independent_trade"]
            )
            else "EMPLOYEE"
        )
        return {"ic_score": None, "outcome": outcome}

    if applied_ic_test == "ECONOMIC_REALITY":
        factors = review["economic_reality_factors"]
        score = sum(1 for key in ECONOMIC_REALITY_KEYS if factors.get(key) is True)
        if score >= 5:
            outcome = "CONTRACTOR"
        elif score <= 2:
            outcome = "EMPLOYEE"
        else:
            outcome = "INDETERMINATE"
        return {"ic_score": score, "outcome": outcome}

    score = (
        review["behavioral_control_score"] * 3
        + review["financial_control_score"] * 2
        + review["relationship_score"] * 1
    )
    if score >= 20:
        outcome = "CONTRACTOR"
    elif score <= 11:
        outcome = "EMPLOYEE"
    else:
        outcome = "INDETERMINATE"
    return {"ic_score": score, "outcome": outcome}


def ic_test_for_state(code):
    st = state_rule_for(code)
    return st["ic_test"] if st else "ECONOMIC_REALITY"


# --------------------------------------------------- re-analysis requirement
def reanalysis_requirement(position, trigger_type, payload):
    """calculations.reanalysis_requirement (PRD 3.9)."""
    old_floor_cents, old_floor_pct, _src, _st = floors_for_state(
        position["work_state_code"]
    )
    old_weekly = weekly_salary_cents(position)

    if trigger_type == "SALARY_CHANGE":
        new_weekly = payload["new_annual_salary_cents"] // 52
        requires = (old_weekly >= old_floor_cents) != (new_weekly >= old_floor_cents)
        reason = "SALARY_CROSSED_THRESHOLD" if requires else "NO_REANALYSIS_REQUIRED"
    elif trigger_type == "DUTIES_CHANGE":
        current = dec(duty_view(position)["primary_duty_pct"])
        delta = rhu(abs(dec(payload["new_exempt_duty_pct"]) - current), 1)
        requires = delta >= dec("10.0")
        reason = "DUTY_DELTA_EXCEEDED" if requires else "NO_REANALYSIS_REQUIRED"
    elif trigger_type == "REPORTING_CHANGE":
        requires = (
            position["claimed_exemption_test"] == "EXECUTIVE"
            and payload["new_supervises_headcount"] < 2
        )
        reason = "EXEC_SUPERVISION_LOST" if requires else "NO_REANALYSIS_REQUIRED"
    elif trigger_type == "STATE_CHANGE":
        new_floor_cents, new_floor_pct, _s2, _st2 = floors_for_state(
            payload["new_work_state_code"]
        )
        requires = (new_floor_cents != old_floor_cents) or (
            dec(new_floor_pct) != dec(old_floor_pct)
        )
        reason = "JURISDICTION_FLOOR_CHANGED" if requires else "NO_REANALYSIS_REQUIRED"
    else:  # FLSA_THRESHOLD_UPDATE
        requires = True
        reason = "THRESHOLD_UPDATE_MANDATED"

    return bool(requires), reason
