"""Authentication, role authorization, segregation of duties, pagination validation,
and optimistic-concurrency stale-version rejection.

Covers Corner/rbac, Corner/validations (pagination), and Corner/errors (stale version).
"""
from test_helpers import (
    get_success_data, validate_error, ApiErrorId,
    create_employee, setup_eligible_employee,
    create_offering, create_tier, create_draft_enrollment,
    setup_pending_dependent,
    api_client as api,
    build_user_headers, TEST_USERS, anonymous_headers,
)

_ADMIN = TEST_USERS["benefits_admin_headers"]
_PAYROLL = TEST_USERS["payroll_officer_headers"]
_COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def test_payroll_officer_cannot_create_employee():
    """PRD §2.1: "Each operation permits only a specific subset of these roles; a
    syntactically valid request made under a role that is not authorized for the requested
    operation is rejected with ERR_FORBIDDEN_ROLE."

    Design: Corner/rbac/payroll_officer_cannot_create_employee
    """
    resp = api.create_employee({
        "full_name": "Kl Deny", "hire_date": "2026-01-01", "employment_type": "FULL_TIME",
        "payroll_schedule": "SEMI_MONTHLY", "monthly_household_income_cents": 500000,
    }, _PAYROLL)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_benefits_admin_cannot_decide_eoi():
    """PRD §2.1: "a syntactically valid request made under a role that is not authorized
    for the requested operation is rejected with ERR_FORBIDDEN_ROLE."
    (POST /eoi-requests/{id}/decide is authorized for ComplianceOfficer only, per §4.)

    Design: Corner/rbac/benefits_admin_cannot_decide_eoi
    """
    emp = create_employee()
    off = create_offering(benefit_type="VOLUNTARY_LIFE", name="Voluntary Life",
                          requires_eoi=True, guaranteed_issue_amount_cents=15000000)
    tier = create_tier(off["id"], coverage_level="EMPLOYEE_ONLY",
                       monthly_premium_cents=1, employer_contribution_pct=0.0,
                       rate_per_1000_monthly_cents=25)
    enr = create_draft_enrollment(emp["id"], tier["id"], coverage_start_date="2026-02-01",
                                  coverage_amount_cents=30000000)
    get_success_data(api.submit_eoi_enrollment(enr["id"], _ADMIN))
    eoi_list = get_success_data(api.list_eoi_requests(_COMPLIANCE, params={"enrollment_id": enr["id"]}))
    eoi_id = eoi_list[0]["id"]
    resp = api.decide_eoi_request(eoi_id, {"decision": "APPROVED"}, _ADMIN)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_missing_auth_headers_unauthenticated():
    """PRD §2.1: "If either header is missing, or if X-User-Role does not name a role the
    system recognizes, the request is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    resp = api.list_employees(anonymous_headers())
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_segregation_verifier_cannot_verify_own_dependent():
    """PRD §2.9: "verifying a dependent requires that the verifying DependentVerifier's
    X-User-ID differ from the id of the employee who owns that dependent (an employee may
    not verify their own dependent). A violation of any of these three checks is rejected
    with ERR_SEGREGATION_OF_DUTIES at HTTP 403."

    Design: Corner/rbac/segregation_verifier_cannot_verify_own_dependent
    """
    ctx = setup_pending_dependent(relationship="SPOUSE")
    emp_id = ctx["employee"]["id"]
    dep_id = ctx["dependent"]["id"]
    # Verifier acts with X-User-ID equal to the owning employee's id.
    verifier = build_user_headers(emp_id, "DependentVerifier")
    resp = api.verify_dependent(dep_id, verifier)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    after = get_success_data(api.get_dependent(dep_id, _ADMIN))
    assert after["verification_status"] == "PENDING", after


def test_segregation_submitter_cannot_approve_own_life_event():
    """PRD §2.9: "approving a life event and rejecting a life event each require that the
    acting X-User-ID differ from the life event's submitted_by_user_id".
    PRD §3.6: "Each requires the life event to be in SUBMITTED and the acting X-User-ID to
    differ from the recorded submitted_by_user_id, failing otherwise with
    ERR_SEGREGATION_OF_DUTIES."

    Design: Corner/rbac/segregation_submitter_cannot_approve_own_life_event
    """
    emp = setup_eligible_employee(clock_after="2026-02-10T00:00:00Z")
    off = create_offering(benefit_type="MEDICAL", name="Gold PPO")
    tier = create_tier(off["id"], coverage_level="EMPLOYEE_PLUS_SPOUSE",
                       monthly_premium_cents=90000, employer_contribution_pct=0.70)
    submitter = build_user_headers("sub_same", "BenefitsAdmin")
    le = get_success_data(api.create_life_event(emp["id"], {
        "event_type": "MARRIAGE", "event_date": "2026-02-05",
        "requested_plan_tier_id": tier["id"], "adjustment_mode": "PROSPECTIVE",
    }, submitter))
    ev = get_success_data(api.get_employee(emp["id"], _ADMIN))["version"]
    # Same operator attempts to approve their own submission.
    resp = api.approve_life_event(le["id"], {"expected_employee_version": ev}, submitter)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    after = get_success_data(api.get_life_event(le["id"], _ADMIN))
    assert after["status"] == "SUBMITTED", after


def test_pagination_limit_out_of_range_rejected():
    """PRD §2.3: "A request whose limit falls outside the inclusive range from 1 to 100, or
    whose offset is negative, is rejected with ERR_VALIDATION_PAGINATION."

    Design: Corner/validations/pagination_limit_out_of_range_rejected
    """
    resp = api.list_employees(_ADMIN, params={"limit": 999})
    validate_error(resp, ApiErrorId.ERR_VALIDATION_PAGINATION.value)


def test_activate_with_stale_employee_version_rejected():
    """PRD §2.8: "Activating a draft enrollment requires the request body to include
    expected_employee_version, carrying the version of the owning Employee that the client
    last observed. If that value does not equal the employee's current version ... the
    activation is rejected with ERR_STALE_EMPLOYEE_VERSION at HTTP 412, before any state
    change is applied."

    Design: Corner/errors/error_stale_employee_version_triggerable
    """
    emp = setup_eligible_employee()
    off = create_offering(benefit_type="DENTAL", name="Dental Basic")
    tier = create_tier(off["id"], coverage_level="EMPLOYEE_ONLY",
                       monthly_premium_cents=12000, employer_contribution_pct=0.50)
    enr = create_draft_enrollment(emp["id"], tier["id"], coverage_start_date="2026-02-01")
    ev_stale = get_success_data(api.get_employee(emp["id"], _ADMIN))["version"]
    # A payroll run bumps Employee.version, making ev_stale one behind.
    get_success_data(api.run_payroll({"employee_id": emp["id"]}, _PAYROLL))
    resp = api.activate_enrollment(enr["id"], {"expected_employee_version": ev_stale}, _ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_EMPLOYEE_VERSION.value)
