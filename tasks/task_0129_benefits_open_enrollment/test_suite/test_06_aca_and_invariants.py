"""ACA affordability threshold (boundary, both indicator branches) and conserved-quantity
invariants on covered-dependent counts.

Covers Difficulty/boundary_precision_check (ACA affordability) and
Difficulty/compensating_invariant (dependent count).
"""
from test_helpers import (
    get_success_data, validate_success,
    setup_lowest_cost_medical_for_employee,
    setup_verified_dependent_on_active_enrollment,
    api_client as api,
    TEST_USERS,
)

_ADMIN = TEST_USERS["benefits_admin_headers"]
_COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def test_aca_affordable_at_threshold():
    """PRD §3.10: "The form's affordability_indicator is AFFORDABLE when the
    lowest_cost_monthly_premium_cents is less than or equal to the
    affordability_threshold_cents, and UNAFFORDABLE otherwise — a cost exactly equal to
    the threshold counts as AFFORDABLE."
    PRD §3.10: "The form's affordability_threshold_cents is the employee's
    monthly_household_income_cents multiplied by the ACA affordability percentage of 9.02
    percent (the decimal factor 0.0902), rounded half up to whole cents."

    Design: Difficulty/boundary_precision_check/aca_affordability_at_threshold_is_affordable
    """
    ctx = setup_lowest_cost_medical_for_employee(monthly_household_income_cents=100000,
                                                 monthly_premium_cents=30000,
                                                 employer_contribution_pct=0.70)
    data = validate_success(api.generate_form_1095c(
        ctx["employee"]["id"], {"tax_year": 2026}, _COMPLIANCE), expected_status=201)
    # lowest cost = 30000 - round(30000*0.70=21000) = 9000
    assert data["lowest_cost_monthly_premium_cents"] == 9000, data
    # threshold = round_half_up(100000 * 0.0902) = round(9020.0) = 9020
    assert data["affordability_threshold_cents"] == 9020, data
    # 9000 <= 9020 -> AFFORDABLE (at/below threshold)
    assert data["affordability_indicator"] == "AFFORDABLE", data


def test_aca_unaffordable_below_threshold():
    """PRD §3.10: "The form's affordability_indicator is AFFORDABLE when the
    lowest_cost_monthly_premium_cents is less than or equal to the
    affordability_threshold_cents, and UNAFFORDABLE otherwise — a cost exactly equal to
    the threshold counts as AFFORDABLE."

    Design: Difficulty/boundary_precision_check/aca_affordability_at_threshold_is_affordable
    """
    # Income 99000 -> threshold round(99000*0.0902)=round(8929.8)=8930 < lowest cost 9000.
    ctx = setup_lowest_cost_medical_for_employee(monthly_household_income_cents=99000,
                                                 monthly_premium_cents=30000,
                                                 employer_contribution_pct=0.70)
    data = validate_success(api.generate_form_1095c(
        ctx["employee"]["id"], {"tax_year": 2026}, _COMPLIANCE), expected_status=201)
    assert data["lowest_cost_monthly_premium_cents"] == 9000, data
    assert data["affordability_threshold_cents"] == 8930, data
    assert data["affordability_indicator"] == "UNAFFORDABLE", data


def test_dependent_count_after_add_is_one():
    """PRD §3.9: "A successful attachment increments the enrollment's
    covered_dependent_count by one and increments the enrollment's version."

    Design: Difficulty/compensating_invariant/dependent_count_conserved_add_then_remove
    """
    ctx = setup_verified_dependent_on_active_enrollment()
    enr_id = ctx["enrollment"]["id"]
    dep_id = ctx["dependent"]["id"]
    data = get_success_data(api.add_dependent_to_enrollment(enr_id, {"dependent_id": dep_id}, _ADMIN))
    assert data["covered_dependent_count"] == 1, data


def test_dependent_count_conserved_after_add_then_remove():
    """PRD §3.9: "a BenefitsAdmin may detach a dependent from an enrollment by supplying
    the dependent_id; this decrements the enrollment's covered_dependent_count by one and
    increments the enrollment's version."

    Design: Difficulty/compensating_invariant/dependent_count_conserved_add_then_remove
    """
    ctx = setup_verified_dependent_on_active_enrollment()
    enr_id = ctx["enrollment"]["id"]
    dep_id = ctx["dependent"]["id"]
    after_add = get_success_data(api.add_dependent_to_enrollment(enr_id, {"dependent_id": dep_id}, _ADMIN))
    assert after_add["covered_dependent_count"] == 1, after_add
    after_remove = get_success_data(api.remove_dependent_from_enrollment(enr_id, {"dependent_id": dep_id}, _ADMIN))
    assert after_remove["covered_dependent_count"] == 0, after_remove
