"""RBAC corners: role exclusivity, entity-backed capability, tenancy and shared reads."""
from test_helpers import (
    ApiErrorId,
    build_contractor,
    build_determination,
    build_fringe_plan,
    build_rate,
    build_staff,
    build_submission,
    compliant_paid_line,
    get_success_data,
    make_certifier_headers,
    make_preparer_headers,
    read_assignment,
    setup_env,
    setup_finalized_submission,
    validate_error,
    validate_paginated,
)

WEEK = "2026-08-01T00:00:00.000Z"
ONE_RATE = [{"fringe_hourly_rate_cents": 2000}]


def test_a_payroll_preparer_cannot_activate_a_wage_determination(api, portal_admin_headers):
    """Publishing the governing schedule is the admin's exclusive act, and DRAFT is preserved.

    PRD 2.1: "When the headers are well-formed but the named role is not listed as an authorized
    role for the endpoint being called (see the table in §4), the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)." PRD endpoint catalogue: "POST
    `/wage-determinations/{id}/activate` Activates a `DRAFT` determination, optionally superseding
    the locality's current one | PortalAdmin".

    Design: Corner/rbac/a_payroll_preparer_cannot_activate_a_wage_determination
    """
    env = setup_env(api, rates=ONE_RATE)
    determination = build_determination(api, effective_date="2027-01-01T00:00:00.000Z")
    build_rate(api, determination["id"])

    resp = api.activate_wage_determination(determination["id"], env["preparer_headers"], {})
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403)

    unchanged = get_success_data(
        api.get_wage_determination(determination["id"], portal_admin_headers)
    )
    assert unchanged["status"] == "DRAFT"
    assert unchanged["rate_count"] == 1


def test_a_labor_standards_auditor_cannot_sign_the_statement_of_compliance(
    api, cruz_headers, officer_headers
):
    """No agency role may execute the contractor's attestation, not even the enforcement auditor.

    PRD 2.1: "the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)." PRD endpoint
    catalogue: "POST `/payroll-submissions/{id}/certify` Signs the statement of compliance and
    transmits the payroll to the portal | CertifyingOfficial". PRD 3.7: "Signing is a single act
    that both executes the statement of compliance and transmits the payroll, and it is reserved to
    a `CertifyingOfficial`."

    Design: Corner/rbac/a_labor_standards_auditor_cannot_sign_the_statement_of_compliance
    """
    _env, submission, _rows = setup_finalized_submission(
        api, lines=[compliant_paid_line()], week_ending_date=WEEK, rates=ONE_RATE
    )
    resp = api.certify_payroll_submission(submission["id"], cruz_headers, {})
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403)

    unchanged = get_success_data(api.get_payroll_submission(submission["id"], officer_headers))
    assert unchanged["workflow_status"] == "PENDING_CERTIFICATION"
    assert unchanged["statement_signed_at"] is None
    assert unchanged["certified_by_staff_id"] is None


def test_a_portal_admin_cannot_approve_a_fringe_benefit_plan(api, portal_admin_headers):
    """The widest-reaching role is a peer, not a superuser: the plan stays PENDING_APPROVAL.

    PRD 2.1: "the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)." PRD endpoint
    catalogue: "POST `/fringe-plans/{id}/approve` Agency decision approving or rejecting a fringe
    plan | AgencyComplianceOfficer". PRD 3.3: "Only an `APPROVED` plan yields a non-zero credit on
    a payroll line. A plan still sitting in `PENDING_APPROVAL` credits nothing".

    Design: Corner/rbac/a_portal_admin_cannot_approve_a_fringe_benefit_plan
    """
    env = setup_env(api, rates=ONE_RATE)
    plan = build_fringe_plan(
        api, env["contractor"]["id"], env["preparer_headers"], plan_name="Acme Trust A"
    )
    assert plan["approval_status"] == "PENDING_APPROVAL"

    resp = api.approve_fringe_plan(plan["id"], {"decision": "APPROVED"}, portal_admin_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403)

    plans = get_success_data(api.list_fringe_plans(env["contractor"]["id"], portal_admin_headers))
    assert [row["approval_status"] for row in plans if row["id"] == plan["id"]] == [
        "PENDING_APPROVAL"
    ]


def test_a_compliance_officer_cannot_raise_a_finding_of_their_own(api, officer_headers):
    """Review and enforcement stay separable: only the auditor may raise a finding.

    PRD 2.1: "the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)." PRD endpoint
    catalogue: "POST `/findings` Auditor raises a compliance finding against a filed payroll
    submission | LaborStandardsAuditor". PRD 2.1: "An `AgencyComplianceOfficer` is the
    awarding-agency reviewer who picks up submitted payrolls, accepts or returns them, rescinds
    acceptances, approves or rejects fringe benefit plans, adjudicates contractor responses to
    findings, reverses restitution disbursements, and reinstates suspended tiers."

    Design: Corner/rbac/a_compliance_officer_cannot_raise_a_finding_of_their_own
    """
    env, submission, rows = setup_finalized_submission(
        api, lines=[compliant_paid_line()], week_ending_date=WEEK, rates=ONE_RATE
    )
    submission = get_success_data(
        api.certify_payroll_submission(submission["id"], env["certifier_headers"], {})
    )
    assert submission["workflow_status"] == "SUBMITTED"

    resp = api.create_finding(
        {
            "project_id": env["project"]["id"],
            "payroll_submission_id": submission["id"],
            "worker_id": rows[0]["worker_id"],
            "finding_type": "UNDERPAYMENT",
            "severity": "MAJOR",
            "restitution_required_cents": 0,
        },
        officer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403)

    assert get_success_data(
        api.get_project(env["project"]["id"], officer_headers)
    )["open_finding_count"] == 0
    assert get_success_data(
        api.get_contractor(env["contractor"]["id"], officer_headers)
    )["debarment_risk_score"] == 0


def test_certifying_with_a_preparer_only_staff_row_is_refused_before_the_duties_check(
    api, officer_headers
):
    """Capability (rung 6) answers before segregation of duties (rung 11) even when both fail.

    PRD 2.1: "A preparation request from a staff row lacking `PREPARER` or `BOTH`, or a
    certification or finding-response request from a staff row lacking `CERTIFIER` or `BOTH`, is
    rejected with `ERR_STAFF_CAPABILITY_MISSING` (HTTP 403)." PRD 2.8 rung 6: "Staff capability, as
    described in §2.1 — `ERR_STAFF_CAPABILITY_MISSING`." PRD 2.8 rung 11: "Segregation of duties on
    certification — `ERR_SEGREGATION_OF_DUTIES` (HTTP 409), on certification only."

    Design: Corner/rbac/certifying_with_a_preparer_only_staff_row_is_refused_before_the_duties_check
    """
    env, submission, _rows = setup_finalized_submission(
        api, lines=[compliant_paid_line()], week_ending_date=WEEK, rates=ONE_RATE
    )
    assert env["preparer"]["capability"] == "PREPARER"
    assert submission["prepared_by_staff_id"] == env["preparer"]["id"]

    resp = api.certify_payroll_submission(
        submission["id"], make_certifier_headers(env["preparer"]["id"]), {}
    )
    validate_error(resp, ApiErrorId.ERR_STAFF_CAPABILITY_MISSING.value, expected_status=403)

    unchanged = get_success_data(api.get_payroll_submission(submission["id"], officer_headers))
    assert unchanged["workflow_status"] == "PENDING_CERTIFICATION"
    assert unchanged["certified_by_staff_id"] is None


def test_a_preparer_cannot_file_payroll_against_another_contractors_tier(api):
    """Tenancy runs through the acting staff row, and the refused filing leaves the version alone.

    PRD 2.1: "if the staff row resolves but belongs to a contractor other than the one that owns
    the targeted assignment, submission, finding or payment, the request fails with
    `ERR_NOT_OWNER` (HTTP 403)." PRD 2.8 rung 5: "Ownership for the entity-backed roles: the acting
    `ContractorStaff` row's `contractor_id` must equal the contractor of the contract assignment
    that owns the targeted payroll submission, finding response or restitution payment —
    `ERR_NOT_OWNER`."

    Design: Corner/rbac/a_preparer_cannot_file_payroll_against_another_contractors_tier
    """
    env = setup_env(api, rates=ONE_RATE)
    other = build_contractor(api, legal_name="Bay Conduit")
    intruder = build_staff(api, other["id"], full_name="Bea Bay", capability="PREPARER")
    version = read_assignment(api, env["assignment"]["id"])["version"]

    resp = api.create_payroll_submission(
        {
            "contract_assignment_id": env["assignment"]["id"],
            "week_ending_date": WEEK,
            "prepared_by_staff_id": intruder["id"],
            "expected_contract_assignment_version": version,
        },
        make_preparer_headers(intruder["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_OWNER.value, expected_status=403)
    assert read_assignment(api, env["assignment"]["id"])["version"] == version


def test_every_declared_role_can_read_the_payroll_register(
    api, portal_admin_headers, officer_headers, cruz_headers
):
    """All five roles see the same single row: write-side separation must not leak into reads.

    PRD 2.1: "The five roles are `PortalAdmin`, `PayrollPreparer`, `CertifyingOfficial`,
    `AgencyComplianceOfficer` and `LaborStandardsAuditor`." PRD endpoint catalogue: "GET
    `/payroll-submissions` Lists weekly filings | All roles". PRD 2.3: "`total_count` reports the
    number of rows matching the request's filters before the window is applied, and `has_more` is
    true when rows remain beyond the current window."

    Design: Corner/rbac/every_declared_role_can_read_the_payroll_register
    """
    env = setup_env(api, rates=ONE_RATE)
    submission = build_submission(api, env, week_ending_date=WEEK)

    readers = [
        portal_admin_headers,
        env["preparer_headers"],
        env["certifier_headers"],
        officer_headers,
        cruz_headers,
    ]
    for headers in readers:
        resp = api.list_payroll_submissions(headers, params={"project_id": env["project"]["id"]})
        rows, meta = validate_paginated(resp)
        assert len(rows) == 1
        assert rows[0]["id"] == submission["id"]
        assert rows[0]["workflow_status"] == "DRAFT"
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
