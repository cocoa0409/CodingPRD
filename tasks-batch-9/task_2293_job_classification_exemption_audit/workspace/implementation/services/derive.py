"""Derived-field derivation: positions, job families, engagements (PRD 2.8, 3.3, 3.6, 3.8).

Every derived value in this domain is a pure function of stored state, so it is
computed here rather than cached. Version/updated_at bookkeeping stays with the
operations that the PRD says mutate a row.
"""
from decimal import Decimal

import db
from constants import (
    CORROBORATION_SPREAD_MAX_PCT,
    FEDERAL_MIN_WEEKLY_SALARY_CENTS,
    FEDERAL_PRIMARY_DUTY_MIN_PCT,
    INCUMBENT_WEIGHT_PCT,
    LOOKBACK_WEEKS_STANDARD,
    LOOKBACK_WEEKS_WILLFUL,
    MANAGER_WEIGHT_PCT,
    MISCLASSIFICATION_STATUS_RISK,
    SCREENING_UNCERTAINTY_PREMIUM,
    STANDARD_WORKWEEK_HOURS,
    STRICT_ENUM_DUTY_FLOOR_PCT,
)
from services.numbers import clamp, dec, rhu

RISK_EXCLUDED_STATUSES = ("CONFIRMED_NONEXEMPT", "RECLASSIFIED")


# --------------------------------------------------------------- jurisdiction
def state_rule_for(code):
    if code is None:
        return None
    for rule in db.state_rules.values():
        if rule["state_code"] == code:
            return rule
    return None


def floors_for_state(code):
    """(applicable_salary_floor_cents, applicable_duty_floor_pct,
    salary_threshold_source, state_rule)."""
    st = state_rule_for(code)
    state_min_weekly = (
        st["min_weekly_salary_cents"] if st else FEDERAL_MIN_WEEKLY_SALARY_CENTS
    )
    salary_floor = max(FEDERAL_MIN_WEEKLY_SALARY_CENTS, state_min_weekly)
    duty_floor = (
        STRICT_ENUM_DUTY_FLOOR_PCT
        if st and st["duties_test_variant"] == "STRICT_ENUM"
        else FEDERAL_PRIMARY_DUTY_MIN_PCT
    )
    source = "STATE" if state_min_weekly > FEDERAL_MIN_WEEKLY_SALARY_CENTS else "FEDERAL"
    return salary_floor, duty_floor, source, st


def floors_for_position(position):
    return floors_for_state(position["work_state_code"])


# ------------------------------------------------------------------- position
def weekly_salary_cents(position):
    return position["annual_salary_cents"] // 52


def hourly_rate_cents(position):
    return position["annual_salary_cents"] // 2080


def duty_statements_of(position_id):
    return db.ordered(
        [d for d in db.duty_statements.values() if d["position_id"] == position_id]
    )


def interviews_of(position_id):
    return db.ordered(
        [i for i in db.interviews.values() if i["position_id"] == position_id]
    )


def _attested(position_id, respondent_type):
    for row in db.ordered(
        [
            i
            for i in db.interviews.values()
            if i["position_id"] == position_id
            and i["respondent_type"] == respondent_type
            and i["status"] == "ATTESTED"
        ]
    ):
        return row
    return None


def self_reported_exempt_pct(position):
    if position.get("self_reported_exempt_pct_override") is not None:
        return dec(position["self_reported_exempt_pct_override"])
    total = Decimal(0)
    for statement in db.duty_statements.values():
        if statement["position_id"] == position["id"] and statement["is_exempt_duty"]:
            total += dec(statement["claimed_time_pct"])
    return total


def duty_view(position):
    """calculations.duties_corroboration."""
    self_reported = self_reported_exempt_pct(position)
    mgr = _attested(position["id"], "MANAGER")
    inc = _attested(position["id"], "INCUMBENT")

    if mgr is None or inc is None:
        return {
            "self_reported_exempt_pct": self_reported,
            "duties_validation_status": "PENDING",
            "primary_duty_pct": rhu(self_reported, 1),
            "validated_weekly_hours": position["avg_weekly_hours"],
            "corroborated_supervises_headcount": 0,
            "corroborated_hire_fire_influence": False,
        }

    mgr_pct = dec(mgr["reported_exempt_duty_pct"])
    inc_pct = dec(inc["reported_exempt_duty_pct"])
    spread = abs(mgr_pct - inc_pct)
    if spread > CORROBORATION_SPREAD_MAX_PCT:
        status = "CONFLICTED"
        primary = rhu(min(mgr_pct, inc_pct), 1)
    else:
        status = "CORROBORATED"
        primary = rhu(
            (mgr_pct * MANAGER_WEIGHT_PCT + inc_pct * INCUMBENT_WEIGHT_PCT) / Decimal(100),
            1,
        )

    mgr_hours = mgr["reported_weekly_hours"]
    inc_hours = inc["reported_weekly_hours"]
    validated_hours = mgr_hours if dec(mgr_hours) >= dec(inc_hours) else inc_hours
    return {
        "self_reported_exempt_pct": self_reported,
        "duties_validation_status": status,
        "primary_duty_pct": primary,
        "validated_weekly_hours": validated_hours,
        "corroborated_supervises_headcount": min(
            mgr["supervises_headcount"], inc["supervises_headcount"]
        ),
        "corroborated_hire_fire_influence": bool(
            mgr["has_hire_fire_influence"] and inc["has_hire_fire_influence"]
        ),
    }


def position_view(position):
    view = duty_view(position)
    view["weekly_salary_cents"] = weekly_salary_cents(position)
    view["overtime_eligible"] = position["current_fls_status"] == "NONEXEMPT"
    return view


# ----------------------------------------------------------------- job family
def positions_of_family(family_id):
    return db.ordered(
        [p for p in db.positions.values() if p["job_family_id"] == family_id]
    )


def _position_risk(position):
    salary_floor, duty_floor, _source, _st = floors_for_position(position)
    view = duty_view(position)

    margin = dec(view["primary_duty_pct"]) - dec(duty_floor)
    duty_risk = clamp(0, 40, rhu(Decimal(40) - margin * Decimal(2)))

    weekly = weekly_salary_cents(position)
    comfort = rhu(dec(salary_floor) * Decimal("1.15"))
    if weekly >= comfort:
        salary_risk = 0
    elif weekly >= salary_floor:
        salary_risk = 15
    else:
        salary_risk = 30

    over = dec(view["validated_weekly_hours"]) - STANDARD_WORKWEEK_HOURS
    if over < 0:
        over = Decimal(0)
    hours_risk = min(20, rhu(over * Decimal(2)))

    status_risk = (
        MISCLASSIFICATION_STATUS_RISK
        if position["classification_status"] == "MISCLASSIFIED"
        else 0
    )
    return min(100, duty_risk + salary_risk + hours_risk + status_risk)


def _risk_tier(score):
    if score >= 75:
        return "CRITICAL"
    if score >= 55:
        return "HIGH"
    if score >= 30:
        return "MEDIUM"
    return "LOW"


def family_view(family):
    """calculations.job_family_risk_score."""
    all_positions = positions_of_family(family["id"])
    population = [
        p
        for p in all_positions
        if p["classification_status"] not in RISK_EXCLUDED_STATUSES
    ]
    family_headcount = sum(p["incumbent_count"] for p in population)
    open_misclassified_count = len(
        [p for p in all_positions if p["classification_status"] == "MISCLASSIFIED"]
    )

    if family_headcount == 0:
        return {
            "risk_variant": "EVIDENCE_WEIGHTED",
            "risk_score": 0,
            "risk_tier": "LOW",
            "family_headcount": 0,
            "open_misclassified_count": open_misclassified_count,
        }

    weighted_sum = Decimal(0)
    screening = False
    for position in population:
        weighted_sum += Decimal(_position_risk(position)) * Decimal(
            position["incumbent_count"]
        )
        if duty_view(position)["duties_validation_status"] == "PENDING":
            screening = True

    variant = "SCREENING" if screening else "EVIDENCE_WEIGHTED"
    premium = Decimal(SCREENING_UNCERTAINTY_PREMIUM) if screening else Decimal(0)
    weighted_mean = weighted_sum / Decimal(family_headcount)
    score = min(100, rhu(weighted_mean + premium))
    return {
        "risk_variant": variant,
        "risk_score": score,
        "risk_tier": _risk_tier(score),
        "family_headcount": family_headcount,
        "open_misclassified_count": open_misclassified_count,
    }


# --------------------------------------------------------------- audit project
def families_of_project(project_id):
    return db.ordered(
        [f for f in db.job_families.values() if f["audit_project_id"] == project_id]
    )


def positions_of_project(project_id):
    family_ids = {f["id"] for f in families_of_project(project_id)}
    return db.ordered(
        [p for p in db.positions.values() if p["job_family_id"] in family_ids]
    )


def project_of_family(family):
    return db.audit_projects.get(family["audit_project_id"])


def family_of_position(position):
    return db.job_families.get(position["job_family_id"])


def project_of_position(position):
    family = family_of_position(position)
    return project_of_family(family) if family else None


def cases_of_project(project_id):
    position_ids = {p["id"] for p in positions_of_project(project_id)}
    return db.ordered(
        [
            c
            for c in db.reclassification_cases.values()
            if c["position_id"] in position_ids
        ]
    )


def corrections_of_project(project_id):
    case_ids = {c["id"] for c in cases_of_project(project_id)}
    return db.ordered(
        [
            v
            for v in db.voluntary_corrections.values()
            if v["reclassification_case_id"] in case_ids
        ]
    )


def reviews_of_project(project_id):
    return db.ordered(
        [
            r
            for r in db.contractor_reviews.values()
            if r["audit_project_id"] == project_id
        ]
    )


def estimates_of_case(case_id):
    return db.ordered(
        [
            e
            for e in db.back_wage_estimates.values()
            if e["reclassification_case_id"] == case_id
        ]
    )


def active_estimate_of_case(case_id):
    for estimate in estimates_of_case(case_id):
        if estimate["status"] == "ACTIVE":
            return estimate
    return None


def case_exposure_cents(case):
    estimate = active_estimate_of_case(case["id"])
    return estimate["total_exposure_cents"] if estimate else 0


def case_status(case):
    if (
        case["pay_conversion_status"] == "CONVERTED"
        and case["communication_status"] == "ACKNOWLEDGED"
    ):
        return "COMPLETED"
    return "OPEN"


def remediation_posture(project):
    """calculations.project_remediation_posture — evaluated top-down."""
    families = families_of_project(project["id"])
    positions = positions_of_project(project["id"])
    for family in families:
        view = family_view(family)
        if view["risk_tier"] == "CRITICAL" and view["open_misclassified_count"] >= 1:
            return "FROZEN"
    if any(p["classification_status"] == "MISCLASSIFIED" for p in positions):
        return "RESTRICTED"
    if any(
        r["status"] == "FINALIZED_EMPLOYEE" for r in reviews_of_project(project["id"])
    ):
        return "RESTRICTED"
    return "OPEN"


def project_view(project):
    positions = positions_of_project(project["id"])
    position_by_id = {p["id"]: p for p in positions}
    cases = cases_of_project(project["id"])

    open_headcount = sum(
        p["incumbent_count"]
        for p in positions
        if p["classification_status"] == "MISCLASSIFIED"
    )

    exposure = 0
    for estimate in db.back_wage_estimates.values():
        if estimate["status"] != "ACTIVE":
            continue
        case = db.reclassification_cases.get(estimate["reclassification_case_id"])
        if case is None:
            continue
        position = position_by_id.get(case["position_id"])
        if position is None:
            continue
        if position["classification_status"] in ("MISCLASSIFIED", "RECLASSIFIED"):
            exposure += estimate["total_exposure_cents"]

    delta = 0
    for case in cases:
        if case["pay_conversion_status"] == "CONVERTED" and case[
            "cost_delta_cents"
        ] is not None:
            delta += case["cost_delta_cents"]

    committed = 0
    for correction in corrections_of_project(project["id"]):
        if correction["status"] == "APPROVED" and correction[
            "approved_amount_cents"
        ] is not None:
            committed += correction["approved_amount_cents"]

    return {
        "remediation_posture": remediation_posture(project),
        "open_misclassified_headcount": open_headcount,
        "total_back_wage_exposure_cents": exposure,
        "converted_annual_payroll_delta_cents": delta,
        "committed_correction_cents": committed,
    }


def lookback_policy_weeks(project):
    return (
        LOOKBACK_WEEKS_WILLFUL
        if project["lookback_policy"] == "WILLFUL_3Y"
        else LOOKBACK_WEEKS_STANDARD
    )
