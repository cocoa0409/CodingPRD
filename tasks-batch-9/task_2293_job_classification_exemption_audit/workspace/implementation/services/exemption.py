"""calculations.exemption_test_evaluation (PRD 3.4)."""
from constants import (
    COMPUTER_HOURLY_MIN_CENTS,
    EXECUTIVE_MIN_SUPERVISED,
    FEDERAL_HCE_ANNUAL_CENTS,
    FEDERAL_MIN_WEEKLY_SALARY_CENTS,
    FEDERAL_PRIMARY_DUTY_MIN_PCT,
    HCE_MIN_DUTY_PCT,
)
from services.derive import (
    duty_statements_of,
    duty_view,
    floors_for_position,
    hourly_rate_cents,
    weekly_salary_cents,
)
from services.numbers import dec


def evaluate(position, applied_test):
    salary_floor, duty_floor, threshold_source, st = floors_for_position(position)

    state_hce_annual = st["hce_annual_cents"] if st else 0
    computer_ok_state = st["computer_exemption_recognized"] if st else True
    outside_ok_state = st["outside_sales_recognized"] if st else True
    hce_ok_state = st["hce_shortcut_recognized"] if st else True

    view = duty_view(position)
    primary_duty_pct = dec(view["primary_duty_pct"])

    weekly = weekly_salary_cents(position)
    hourly = hourly_rate_cents(position)
    hce_floor = max(FEDERAL_HCE_ANNUAL_CENTS, state_hce_annual)

    def duties_gate():
        if applied_test == "EXECUTIVE":
            return (
                view["corroborated_supervises_headcount"] >= EXECUTIVE_MIN_SUPERVISED
                and view["corroborated_hire_fire_influence"] is True
            )
        if applied_test == "ADMINISTRATIVE":
            return any(
                d["is_exempt_duty"] and d["discretion_level"] == "INDEPENDENT_JUDGMENT"
                for d in duty_statements_of(position["id"])
            )
        if applied_test == "PROFESSIONAL":
            return position["requires_advanced_degree"] is True
        if applied_test == "COMPUTER":
            return True
        if applied_test == "OUTSIDE_SALES":
            return position["works_primarily_offsite"] is True
        return False

    def salary_ok(floor_cents):
        if applied_test == "OUTSIDE_SALES":
            return True
        if position["salary_basis"] != "HOURLY":
            return weekly >= floor_cents
        if applied_test == "COMPUTER":
            return hourly >= COMPUTER_HOURLY_MIN_CENTS
        return False

    def duties_ok(floor_pct):
        if applied_test == "OUTSIDE_SALES":
            return True
        return primary_duty_pct >= dec(floor_pct) and duties_gate()

    if applied_test == "COMPUTER":
        recognized_state = computer_ok_state
    elif applied_test == "OUTSIDE_SALES":
        recognized_state = outside_ok_state
    else:
        recognized_state = True

    hce_eligible = (
        position["annual_salary_cents"] >= hce_floor
        and weekly >= FEDERAL_MIN_WEEKLY_SALARY_CENTS
        and primary_duty_pct >= HCE_MIN_DUTY_PCT
        and applied_test in ("EXECUTIVE", "ADMINISTRATIVE", "PROFESSIONAL")
    )

    federal_duties_ok = duties_ok(FEDERAL_PRIMARY_DUTY_MIN_PCT)
    federal_pass = bool(
        (salary_ok(FEDERAL_MIN_WEEKLY_SALARY_CENTS) and federal_duties_ok)
        or hce_eligible
    )
    state_pass = bool(
        recognized_state
        and salary_ok(salary_floor)
        and (duties_ok(duty_floor) or (hce_eligible and hce_ok_state))
    )
    hce_shortcut_applied = bool(hce_eligible and not federal_duties_ok)

    if view["duties_validation_status"] == "PENDING":
        outcome = "INDETERMINATE"
    elif federal_pass and state_pass:
        outcome = "EXEMPT"
    else:
        outcome = "NONEXEMPT"

    return {
        "weekly_salary_cents_snapshot": weekly,
        "primary_duty_pct_snapshot": view["primary_duty_pct"],
        "applicable_salary_floor_cents": salary_floor,
        "applicable_duty_floor_pct": duty_floor,
        "salary_threshold_source": threshold_source,
        "federal_pass": federal_pass,
        "state_pass": state_pass,
        "hce_shortcut_applied": hce_shortcut_applied,
        "outcome": outcome,
    }
