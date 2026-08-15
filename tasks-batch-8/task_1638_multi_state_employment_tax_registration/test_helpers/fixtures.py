"""Composite setup helpers for multi-step test prerequisites.

Setup calls use get_success_data() (lenient) so a setup failure surfaces as a
clear "Setup step failed" error rather than a confusing assertion failure.
Every helper builds its preconditions from scratch: the harness restarts the
server before each test, so each test starts against an empty database.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_agency_notice_payload,
    create_employee_payload,
    create_employer_payload,
    create_location_change_payload,
    create_nexus_case_payload,
    create_reciprocity_agreement_payload,
    create_registration_payload,
    create_tax_agency_payload,
    create_ui_rate_payload,
    create_voluntary_contribution_payload,
    create_withholding_election_payload,
    create_work_location_payload,
)
from .test_users import (
    TEST_USERS,
    make_employee_headers,
    make_nexus_analyst_headers,
    make_payroll_compliance_lead_headers,
    make_tax_director_headers,
    make_ui_specialist_headers,
)

DIRECTOR = TEST_USERS["tax_director_headers"]
ANALYST = TEST_USERS["nexus_analyst_headers"]
SPECIALIST = TEST_USERS["ui_specialist_headers"]
PCL = TEST_USERS["payroll_compliance_lead_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# --------------------------------------------------------------------------
# Tier 0: single-call primitives
# --------------------------------------------------------------------------

def create_employer(**overrides) -> dict:
    res = api_client.create_employer(create_employer_payload(**overrides), DIRECTOR)
    return get_success_data(res)


def get_employer(employer_id) -> dict:
    return get_success_data(api_client.get_employer(employer_id, DIRECTOR))


def create_state_withholding_agency(state_code="OR", agency_name="Oregon DOR",
                                    withholding_rate_bp=500, **overrides) -> dict:
    payload = create_tax_agency_payload(
        agency_kind="STATE_WITHHOLDING", state_code=state_code,
        agency_name=agency_name, withholding_rate_bp=withholding_rate_bp, **overrides,
    )
    return get_success_data(api_client.create_tax_agency(payload, DIRECTOR))


def create_state_ui_agency(state_code="PA", agency_name="PA UC",
                           new_employer_rate_bp=270, solvency_surcharge_bp=30,
                           ui_wage_base_cents=5_000_000, **overrides) -> dict:
    payload = create_tax_agency_payload(
        agency_kind="STATE_UI", state_code=state_code, agency_name=agency_name,
        new_employer_rate_bp=new_employer_rate_bp,
        solvency_surcharge_bp=solvency_surcharge_bp,
        ui_wage_base_cents=ui_wage_base_cents, **overrides,
    )
    payload.pop("withholding_rate_bp", None)
    return get_success_data(api_client.create_tax_agency(payload, DIRECTOR))


def create_local_agency(state_code, locality_code, agency_name,
                        resident_rate_bp, nonresident_rate_bp,
                        precedence_rank=10, **overrides) -> dict:
    payload = create_tax_agency_payload(
        agency_kind="LOCAL", state_code=state_code, locality_code=locality_code,
        agency_name=agency_name, resident_rate_bp=resident_rate_bp,
        nonresident_rate_bp=nonresident_rate_bp, precedence_rank=precedence_rank,
        **overrides,
    )
    payload.pop("withholding_rate_bp", None)
    return get_success_data(api_client.create_tax_agency(payload, DIRECTOR))


def create_reciprocity_agreement(**overrides) -> dict:
    return get_success_data(
        api_client.create_reciprocity_agreement(
            create_reciprocity_agreement_payload(**overrides), DIRECTOR
        )
    )


def create_work_location(state_code="OR", **overrides) -> dict:
    return get_success_data(
        api_client.create_work_location(
            create_work_location_payload(state_code=state_code, **overrides), ANALYST
        )
    )


def create_employee(work_location_id, employee_ref="E-0001", full_name="Test Employee",
                    resident_state_code="OR", annual_wage_cents=3_000_000,
                    hire_date=None, resident_locality_code=None) -> dict:
    overrides = {}
    if hire_date is not None:
        overrides["hire_date"] = hire_date
    if resident_locality_code is not None:
        overrides["resident_locality_code"] = resident_locality_code
    payload = create_employee_payload(
        work_location_id, employee_ref=employee_ref, full_name=full_name,
        resident_state_code=resident_state_code,
        annual_wage_cents=annual_wage_cents, **overrides,
    )
    return get_success_data(api_client.create_employee(payload, ANALYST))


def set_clock(to_iso8601) -> dict:
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, DIRECTOR)
    )


def open_nexus_case(state_code) -> dict:
    return get_success_data(
        api_client.create_nexus_case(create_nexus_case_payload(state_code), ANALYST)
    )


def recompute_nexus_case(case_id) -> dict:
    return get_success_data(api_client.recompute_nexus_case(case_id, ANALYST))


def confirm_nexus_case(case_id) -> dict:
    return get_success_data(api_client.confirm_nexus_case(case_id, ANALYST))


def create_registration(agency_id, projected_annual_withholding_cents,
                        expected_employer_version) -> dict:
    payload = create_registration_payload(
        agency_id, expected_employer_version,
        projected_annual_withholding_cents=projected_annual_withholding_cents,
    )
    return get_success_data(api_client.create_registration(payload, ANALYST))


def submit_registration(registration_id) -> dict:
    return get_success_data(api_client.submit_registration(registration_id, ANALYST))


def activate_registration(registration_id, account_number) -> dict:
    return get_success_data(
        api_client.activate_registration(
            registration_id, {"account_number": account_number}, ANALYST
        )
    )


def create_employee_election(employee, **overrides) -> dict:
    """Create a WithholdingElection as the owning Employee (ownership-gated)."""
    payload = create_withholding_election_payload(
        employee["id"], employee["version"], **overrides,
    )
    return api_client.create_withholding_election(
        payload, make_employee_headers(employee["id"])
    )


def create_penalty_notice(penalty_amount_cents, received_date="2026-08-10T00:00:00Z",
                          response_due_date="2026-09-10T00:00:00Z",
                          registration_id=None, filing_obligation_id=None,
                          user_id="pcl-1") -> dict:
    overrides = {"penalty_amount_cents": penalty_amount_cents,
                 "received_date": received_date,
                 "response_due_date": response_due_date}
    if registration_id is not None:
        overrides["registration_id"] = registration_id
    if filing_obligation_id is not None:
        overrides["filing_obligation_id"] = filing_obligation_id
    payload = create_agency_notice_payload(**overrides)
    return get_success_data(
        api_client.create_agency_notice(
            payload, make_payroll_compliance_lead_headers(user_id)
        )
    )


# --------------------------------------------------------------------------
# Tier 1/2: confirmed-nexus and activated-registration composites
# --------------------------------------------------------------------------

def setup_confirmed_nexus(state_code="OR", employee_wages=(3_000_000,),
                          clock=TEST_DEFAULTS["SETUP_CLOCK"],
                          with_employer=True, with_agency=False,
                          agency_rate_bp=500, agency_name=None,
                          resident_state_code=None):
    """Work location + employees + NexusCase driven to CONFIRMED at `clock`.

    Employee(s) hired 2026-08-01 accrue 20 attributable days by 2026-08-20,
    which crosses the 20-day nexus threshold (PRD §3.3).
    Returns dict of created entities.
    """
    out = {}
    if with_employer:
        out["employer"] = create_employer()
    location = create_work_location(state_code)
    out["location"] = location
    employees = []
    for i, wage in enumerate(employee_wages, start=1):
        employees.append(create_employee(
            location["id"], employee_ref=f"E-{state_code}-{i:03d}",
            full_name=f"Worker {state_code} {i}",
            resident_state_code=resident_state_code or state_code,
            annual_wage_cents=wage,
        ))
    out["employees"] = employees
    if with_agency:
        out["agency"] = create_state_withholding_agency(
            state_code=state_code,
            agency_name=agency_name or f"{state_code} DOR",
            withholding_rate_bp=agency_rate_bp,
        )
    case = open_nexus_case(state_code)
    set_clock(clock)
    case = recompute_nexus_case(case["id"])
    case = confirm_nexus_case(case["id"])
    out["nexus_case"] = case
    return out


def setup_withholding_registration_active(
    state_code="OR", rate_bp=500, agency_name="Oregon DOR",
    projected=200_000, account_number="OR-00000001",
    employee_wages=(3_000_000,), resident_state_code=None,
    clock=TEST_DEFAULTS["SETUP_CLOCK"],
):
    """Full chain through an ACTIVE withholding registration.

    Employer -> WH agency -> location -> employees -> NexusCase CONFIRMED ->
    Registration DRAFT -> SUBMITTED -> ACTIVE. Returns all entities plus the
    post-activation registration version.
    """
    out = setup_confirmed_nexus(
        state_code=state_code, employee_wages=employee_wages, clock=clock,
        with_employer=True, with_agency=False,
        resident_state_code=resident_state_code,
    )
    agency = create_state_withholding_agency(
        state_code=state_code, agency_name=agency_name, withholding_rate_bp=rate_bp,
    )
    out["agency"] = agency
    employer = get_employer(out["employer"]["id"])
    out["employer"] = employer
    registration = create_registration(agency["id"], projected, employer["version"])
    submit_registration(registration["id"])
    registration = activate_registration(registration["id"], account_number)
    out["registration"] = registration
    out["registration_version"] = registration["version"]
    return out


def setup_ui_registration_active(
    state_code="PA", agency_name="PA UC",
    new_employer_rate_bp=270, solvency_surcharge_bp=30,
    ui_wage_base_cents=5_000_000,
    account_number="PA-UI-0001",
    employee_wages=(6_000_000, 6_000_000, 6_000_000, 6_000_000, 6_000_000),
    clock=TEST_DEFAULTS["SETUP_CLOCK"], projected=0,
):
    """Full chain through an ACTIVE STATE_UI registration (always QUARTERLY)."""
    out = setup_confirmed_nexus(
        state_code=state_code, employee_wages=employee_wages, clock=clock,
        with_employer=True, with_agency=False,
    )
    agency = create_state_ui_agency(
        state_code=state_code, agency_name=agency_name,
        new_employer_rate_bp=new_employer_rate_bp,
        solvency_surcharge_bp=solvency_surcharge_bp,
        ui_wage_base_cents=ui_wage_base_cents,
    )
    out["agency"] = agency
    employer = get_employer(out["employer"]["id"])
    out["employer"] = employer
    registration = create_registration(agency["id"], projected, employer["version"])
    submit_registration(registration["id"])
    registration = activate_registration(registration["id"], account_number)
    out["registration"] = registration
    out["registration_version"] = registration["version"]
    return out


# --------------------------------------------------------------------------
# Tier 3: UI rate lifecycle and voluntary contributions
# --------------------------------------------------------------------------

def create_effective_ui_rate(registration_id, registration_version,
                             rate_year=2026, experience_rated=True,
                             assigned_rate_bp=420,
                             contributions_paid_3yr_cents=600_000,
                             benefits_charged_3yr_cents=200_000,
                             taxable_payroll_3yr_cents=10_000_000) -> dict:
    """Intake a UIRate then walk RECEIVED -> UNDER_REVIEW -> EFFECTIVE."""
    payload = create_ui_rate_payload(
        registration_id, registration_version,
        rate_year=rate_year, experience_rated=experience_rated,
        assigned_rate_bp=assigned_rate_bp,
        contributions_paid_3yr_cents=contributions_paid_3yr_cents,
        benefits_charged_3yr_cents=benefits_charged_3yr_cents,
        taxable_payroll_3yr_cents=taxable_payroll_3yr_cents,
    )
    rate = get_success_data(api_client.create_ui_rate(payload, SPECIALIST))
    get_success_data(api_client.review_ui_rate(rate["id"], SPECIALIST))
    return get_success_data(api_client.make_ui_rate_effective(rate["id"], SPECIALIST))


def setup_ui_rate_effective(**scenario_overrides) -> dict:
    """ACTIVE PA-UI registration + EFFECTIVE experience-rated UIRate.

    Default rate inputs (600,000 / 200,000 / 10,000,000) give reserve 400bp ->
    bracket 360 + 30 surcharge = final_rate_bp 390 (PRD §3.7 pinned order).
    """
    rate_overrides = scenario_overrides.pop("rate_overrides", {})
    out = setup_ui_registration_active(**scenario_overrides)
    rate = create_effective_ui_rate(
        out["registration"]["id"], out["registration_version"], **rate_overrides,
    )
    out["ui_rate"] = rate
    return out


def propose_vc(ui_rate_id, proposed_amount_cents=100_000,
               decision_deadline="2026-12-01T00:00:00Z", user_id="uis-1") -> dict:
    payload = create_voluntary_contribution_payload(
        ui_rate_id, proposed_amount_cents=proposed_amount_cents,
        decision_deadline=decision_deadline,
    )
    return get_success_data(
        api_client.create_voluntary_contribution(
            payload, make_ui_specialist_headers(user_id)
        )
    )


def approve_vc(vc_id, user_id="dir-1") -> dict:
    return get_success_data(
        api_client.approve_voluntary_contribution(
            vc_id, make_tax_director_headers(user_id)
        )
    )


def remit_vc(vc_id, user_id="uis-1") -> dict:
    return get_success_data(
        api_client.remit_voluntary_contribution(
            vc_id, make_ui_specialist_headers(user_id)
        )
    )


def apply_vc(vc_id, user_id="uis-1") -> dict:
    return get_success_data(
        api_client.apply_voluntary_contribution(
            vc_id, make_ui_specialist_headers(user_id)
        )
    )


def setup_approved_vc(deadline="2026-12-01T00:00:00Z", **scenario_overrides) -> dict:
    """EFFECTIVE 390bp rate + a PROPOSED-then-APPROVED 100,000-cent VC."""
    out = setup_ui_rate_effective(**scenario_overrides)
    vc = propose_vc(out["ui_rate"]["id"], decision_deadline=deadline)
    vc = approve_vc(vc["id"])
    out["vc"] = vc
    return out


# --------------------------------------------------------------------------
# Tier 4: late-filing cascade composites (MONTHLY OR withholding scenario)
# --------------------------------------------------------------------------

def setup_monthly_or_with_late_deposit(account_number="OR-M-0001"):
    """MONTHLY OR registration with the August deposit driven LATE.

    Employee wage 9,125,000 hired 2026-08-01: the July deposit is 0 cents
    (no attributed days), the August deposit is 38,750 cents
    (round_half_up(9,125,000 * 31 / 365 * 0.05)) due 2026-09-15. At clock
    2026-09-16 BOTH deposits are LATE — per PRD §3.8 "a zero-amount obligation
    goes late without penalty and without a notice", so the zero-amount July
    deposit is LATE too, but only the August deposit cascade-creates a
    PENALTY_ASSESSMENT notice with the provisional 2,500-cent penalty.
    Returns employer/agency/location/employees/nexus_case/registration/notice,
    with `late_obligation` naming the nonzero (August) LATE deposit.
    """
    out = setup_withholding_registration_active(
        state_code="OR", projected=3_000_000, account_number=account_number,
        employee_wages=(9_125_000,),
    )
    set_clock("2026-09-16T00:00:00Z")
    notices = get_success_data(api_client.list_agency_notices(
        PCL, params={"registration_id": out["registration"]["id"]}
    ))
    assert len(notices) == 1, (
        f"Setup expected exactly one cascade notice, got {len(notices)}"
    )
    out["notice"] = notices[0]
    obligations = get_success_data(api_client.list_filing_obligations(
        PCL, params={"registration_id": out["registration"]["id"],
                     "obligation_kind": "WITHHOLDING_DEPOSIT", "status": "LATE"}
    ))
    assert len(obligations) == 2, (
        f"Setup expected two LATE deposits (zero-amount July + 38,750-cent "
        f"August), got {len(obligations)}"
    )
    nonzero = [o for o in obligations if o["amount_due_cents"] == 38_750]
    assert len(nonzero) == 1, (
        "Setup expected exactly one nonzero LATE deposit (August, 38,750 cents)"
    )
    out["late_obligation"] = nonzero[0]
    return out


def get_obligations(registration_id, headers=None, **filters) -> list:
    params = {"registration_id": registration_id}
    params.update(filters)
    return get_success_data(
        api_client.list_filing_obligations(headers or ANALYST, params=params)
    )


def get_notices(headers=None, **filters) -> list:
    return get_success_data(
        api_client.list_agency_notices(headers or PCL, params=filters)
    )


# --------------------------------------------------------------------------
# Tier 5: employee/location composites for elections and location changes
# --------------------------------------------------------------------------

def setup_employee_at_location(work_state="NJ", resident_state="PA",
                               annual_wage_cents=3_000_000,
                               employee_ref="E-EL-001", with_employer=False):
    """Work location + one employee working there. No nexus/registration."""
    out = {}
    if with_employer:
        out["employer"] = create_employer()
    location = create_work_location(work_state)
    employee = create_employee(
        location["id"], employee_ref=employee_ref,
        resident_state_code=resident_state,
        annual_wage_cents=annual_wage_cents,
    )
    out["location"] = location
    out["employee"] = employee
    return out


def setup_employee_or_to_nj(employee_ref="E-LC-001", with_employer=False):
    """OR + NJ work locations and one employee currently in OR."""
    out = {}
    if with_employer:
        out["employer"] = create_employer()
    or_loc = create_work_location("OR")
    nj_loc = create_work_location("NJ")
    employee = create_employee(
        or_loc["id"], employee_ref=employee_ref, resident_state_code="OR",
    )
    out["or_location"] = or_loc
    out["nj_location"] = nj_loc
    out["employee"] = employee
    return out


def submit_location_change(employee, to_work_location_id,
                           effective_date="2026-09-01T00:00:00Z",
                           reason="Relocating") -> dict:
    """Employee submits their own location change (ownership-gated)."""
    payload = create_location_change_payload(
        employee["id"], to_work_location_id,
        effective_date=effective_date, reason=reason,
    )
    return api_client.create_location_change(
        payload, make_employee_headers(employee["id"])
    )


def approve_location_change(change_id, user_id="na-1") -> dict:
    return get_success_data(
        api_client.approve_location_change(
            change_id, make_nexus_analyst_headers(user_id)
        )
    )


def create_pa_nj_active_agreement(certificate_form_code="NJ-165",
                                  effective_from="2020-01-01T00:00:00Z",
                                  **overrides) -> dict:
    """Open-ended PA-NJ reciprocity agreement (ACTIVE at the default clock)."""
    return create_reciprocity_agreement(
        state_a="PA", state_b="NJ", effective_from=effective_from,
        certificate_form_code=certificate_form_code, **overrides,
    )
