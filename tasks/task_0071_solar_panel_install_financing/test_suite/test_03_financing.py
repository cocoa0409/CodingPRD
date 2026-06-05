"""Financing plans: ITC attribution, monthly-payment variants, model validation."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    design_payload,
    make_homeowner_headers, make_installer_headers,
    register_homeowner, register_installer,
    create_designed_project, create_draft_plan, create_active_plan,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# --- Difficulty: dual_variant_calc / itc_attribution_homeowner_vs_financier ---

def test_loan_plan_itc_beneficiary_is_homeowner(api):
    """PRD 3.4: "under a LOAN, the homeowner books the credit, so the beneficiary
    is HOMEOWNER; under a PPA or a LEASE, the third-party financier owns the
    system and books the credit, so the beneficiary is FINANCIER and the
    homeowner receives none."

    Design: Difficulty/dual_variant_calc/itc_attribution_homeowner_vs_financier
    """
    homeowner, installer, project, plan = create_active_plan(
        model="LOAN", gross_system_cost_cents=3000000, state_code="CA",
    )
    assert plan["itc_beneficiary"] == "HOMEOWNER"
    # CA adder 0.00 -> rate 0.30; 3000000 * 0.30 == 900000
    proj = get_success_data(api.get_project(project["id"], make_homeowner_headers(homeowner["id"])))
    assert proj["itc_credit_cents"] == 900000


def test_ppa_plan_itc_beneficiary_is_financier_same_credit(api):
    """PRD 3.4: "under a LOAN, the homeowner books the credit, so the beneficiary
    is HOMEOWNER; under a PPA or a LEASE, the third-party financier owns the
    system and books the credit, so the beneficiary is FINANCIER and the
    homeowner receives none."

    Design: Difficulty/dual_variant_calc/itc_attribution_homeowner_vs_financier
    """
    homeowner, installer, project, plan = create_active_plan(
        model="PPA", gross_system_cost_cents=3000000, state_code="CA",
        term_years=20, ppa_rate_cents_per_kwh=12.5, ppa_escalator_pct=0.029,
    )
    assert plan["itc_beneficiary"] == "FINANCIER"
    proj = get_success_data(api.get_project(project["id"], make_homeowner_headers(homeowner["id"])))
    # Identical cost inputs produce the SAME credit value regardless of beneficiary.
    assert proj["itc_credit_cents"] == 900000


# --- Difficulty: combinatorial_formula / loan_amortization_three_input_nonlinear ---

def test_loan_monthly_payment_annuity_amortization(api):
    """PRD 3.5: "otherwise the payment is the principal multiplied by the annuity
    factor, where that factor is the monthly rate times the quantity one plus the
    monthly rate raised to the number of payments, all divided by the quantity one
    plus the monthly rate raised to the number of payments minus one, again
    rounded half up."

    Design: Difficulty/combinatorial_formula/loan_amortization_three_input_nonlinear
    """
    homeowner, installer, project, plan = create_active_plan(
        model="LOAN", term_years=10, loan_principal_cents=2500000, loan_apr=0.06,
    )
    assert plan["monthly_payment_cents"] == 27755


def test_loan_payment_is_not_linear_principal_over_n(api):
    """PRD 3.5: "For a LOAN it is a standard amortization over the term: let the
    monthly rate be the loan_apr divided by twelve and the number of payments be
    the term_years multiplied by twelve"

    Design: Difficulty/combinatorial_formula/loan_amortization_three_input_nonlinear
    """
    homeowner, installer, project, plan = create_active_plan(
        model="LOAN", term_years=10, loan_principal_cents=2500000, loan_apr=0.06,
    )
    # Interest-bearing annuity (27755) != linear principal/n (2500000/120 == 20833).
    assert plan["monthly_payment_cents"] != 20833
    assert plan["monthly_payment_cents"] == 27755


# --- Corner: calculations / payment + srec_owner variants ---

def test_ppa_monthly_payment_production_based(api):
    """PRD 3.5: "For a PPA, the year-one monthly payment is an estimate derived
    from production with the escalator ignored in the first year: take the
    project's estimated_annual_production_kwh multiplied by ppa_rate_cents_per_kwh
    to get the annual figure, divide by twelve, and round half up."

    Design: Corner/calculations/ppa_monthly_payment_production_based
    """
    homeowner, installer, project, plan = create_active_plan(
        model="PPA", term_years=20, ppa_rate_cents_per_kwh=12.5, ppa_escalator_pct=0.029,
    )
    # est 9592 * 12.5 == 119900; /12 round_half_up == 9992
    assert plan["monthly_payment_cents"] == 9992
    assert plan["srec_owner"] == "FINANCIER"


def test_lease_monthly_payment_fixed(api):
    """PRD 3.5: "For a LEASE it is simply the lease_monthly_cents, a flat
    contractual amount independent of production."

    Design: Corner/calculations/lease_monthly_payment_fixed
    """
    homeowner, installer, project, plan = create_active_plan(
        model="LEASE", term_years=25, lease_monthly_cents=8500,
    )
    assert plan["monthly_payment_cents"] == 8500
    assert plan["srec_owner"] == "FINANCIER"


def test_itc_nj_adder_caps_at_forty_pct(api):
    """PRD 3.4: "New Jersey, Massachusetts, and Arizona each add ten percentage
    points, while California and Texas add nothing. The effective rate is the base
    rate plus the state's adder, but never more than the forty-percent cap."

    Design: Corner/calculations/itc_state_adder_nj_caps_at_forty_pct
    """
    homeowner = register_homeowner(state_code="NJ")
    installer = register_installer(licensed_states=["NJ"], company_name="NjCo")
    homeowner, installer, project = create_designed_project(
        homeowner=homeowner, installer=installer, gross_system_cost_cents=4000000,
    )
    # min(0.30+0.10, 0.40)=0.40; 4000000 * 0.40 == 1600000
    assert project["itc_credit_cents"] == 1600000


def test_size_system_area_cap_binds_when_roof_small(api):
    """PRD 3.3: "The area cap in kilowatts is the roof area divided by the constant
    seventy square feet per kilowatt; that quotient is truncated toward zero to
    two decimal places."

    Design: Corner/calculations/size_system_area_binds_when_roof_small
    """
    homeowner = register_homeowner(state_code="CA", annual_kwh_usage=20000)
    installer = register_installer(licensed_states=["CA"])
    homeowner, installer, project = create_designed_project(
        homeowner=homeowner, installer=installer, roof_area_sqft=420,
        shading_factor=0.0, peak_sun_hours=5.0, gross_system_cost_cents=2800000,
    )
    # 420/70 == 6.0 (area cap) < usage target -> system_size_kw 6.0
    assert project["system_size_kw"] == 6.0
    assert project["estimated_annual_production_kwh"] == 8760


# --- Corner: validations / financing field + already-active ---

def test_loan_plan_missing_required_fields_rejected(api):
    """PRD 3.5: "the system rejects a create that omits the model-specific fields
    with ERR_FINANCING_FIELDS_MISSING (HTTP 422): ... a LOAN requires
    loan_principal_cents (the principal in cents, zero or greater) and loan_apr
    (the nominal annual rate as a fraction between 0.0 and 0.30 inclusive)."

    Design: Corner/validations/financing_fields_missing_for_loan
    """
    homeowner, installer, project = create_designed_project()
    ho_headers = make_homeowner_headers(homeowner["id"])
    resp = api.create_financing_plan(
        {"project_id": project["id"], "model": "LOAN", "term_years": 10},
        ho_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FINANCING_FIELDS_MISSING, 422)


def test_second_financing_activate_already_active_rejected(api):
    """PRD 3.5: "A project may hold at most one non-terminated financing plan; an
    attempt to activate a second plan while one is already active is rejected with
    ERR_FINANCING_ALREADY_ACTIVE (HTTP 409)."

    Design: Corner/validations/second_financing_activate_already_active
    """
    homeowner, installer, project = create_designed_project()
    ho_headers = make_homeowner_headers(homeowner["id"])
    plan1 = create_draft_plan(homeowner, project, model="LEASE")
    plan2 = create_draft_plan(homeowner, project, model="LOAN")
    get_success_data(api.activate_financing_plan(
        plan1["id"], {"expected_project_version": project["version"]}, ho_headers
    ))
    proj = get_success_data(api.get_project(project["id"], ho_headers))
    resp = api.activate_financing_plan(
        plan2["id"], {"expected_project_version": proj["version"]}, ho_headers
    )
    validate_error(resp, ApiErrorId.ERR_FINANCING_ALREADY_ACTIVE, 409)


# --- Difficulty: transitive_cascade / cancel_project_depth2_terminates_plan ---

def test_cancel_designed_project_moves_to_cancelled(api):
    """PRD 3.6: "A Homeowner who owns a project may cancel it while it remains in
    REQUESTED, ASSESSED, or DESIGNED. Cancellation moves the project to the
    terminal CANCELLED state, increments its version, and — if the project already
    has an attached financing plan — cascades that plan to TERMINATED, incrementing
    the plan's version as well."

    Design: Difficulty/transitive_cascade/cancel_project_depth2_terminates_plan
    """
    homeowner, installer, project, plan = create_active_plan(model="LEASE")
    ho_headers = make_homeowner_headers(homeowner["id"])
    resp = api.cancel_project(project["id"], ho_headers)
    data = validate_success(resp, 200)
    assert data["status"] == "CANCELLED"


def test_cancel_project_cascades_plan_to_terminated(api):
    """PRD 2.7: "Cancelling a project, when that project already has an attached
    financing plan, terminates that plan as a depth-one cascade."
    PRD 3.6: "A plan in either DRAFT or ACTIVE status is terminated by this
    cascade; the cascade only fires while the project is still in a cancellable
    state."

    Design: Difficulty/transitive_cascade/cancel_project_depth2_terminates_plan
    """
    homeowner, installer, project, plan = create_active_plan(model="LEASE")
    ho_headers = make_homeowner_headers(homeowner["id"])
    get_success_data(api.cancel_project(project["id"], ho_headers))
    refreshed = get_success_data(api.get_financing_plan(plan["id"], ho_headers))
    assert refreshed["status"] == "TERMINATED"
