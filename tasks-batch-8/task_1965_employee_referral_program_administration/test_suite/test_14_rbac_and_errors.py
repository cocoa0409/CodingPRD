"""RBAC and error-catalog corner tests (PRD §2.1, §3.6, §3.3)."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    NON_EXISTENT_UUID,
    make_employee_headers,
    make_recruiter_headers,
    create_employee,
    create_open_requisition,
    create_active_policy,
    submit_referral,
    setup_program,
    advance_referral_to_offer,
    hire_referral,
    get_milestone,
    get_hire_milestone,
    create_open_batch,
    create_referral_payload,
    build_user_headers,
    api_client,
)


class TestNotFoundSweep:
    def test_not_found_sweep_all_resources(self, api):
        """PRD §2.9: "the server validates the existence of each identifier in path
        order and rejects the request immediately with `ERR_NOT_FOUND` (HTTP 404) at the
        *first* identifier that does not correspond to an existing resource".

        Every path-templated GET returns 404 for a well-formed but absent UUID.

        Design: Corner/errors/not_found_sweep_all_resources
        """
        ta = TEST_USERS["talent_admin_headers"]
        pp = TEST_USERS["payroll_processor_headers"]
        co = TEST_USERS["compliance_officer_headers"]

        checks = [
            api.get_candidate(NON_EXISTENT_UUID, ta),
            api.get_requisition(NON_EXISTENT_UUID, ta),
            api.get_policy_version(NON_EXISTENT_UUID, ta),
            api.get_campaign(NON_EXISTENT_UUID, ta),
            api.get_referral(NON_EXISTENT_UUID, ta),
            api.get_milestone(NON_EXISTENT_UUID, pp),
            api.get_payroll_batch(NON_EXISTENT_UUID, pp),
            api.get_abuse_case(NON_EXISTENT_UUID, co),
        ]
        for resp in checks:
            validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestPayrollSegregationOfDuties:
    def test_payroll_processor_cannot_confirm_paid_returns_forbidden(self, api):
        """PRD §3.6: "Payment is then *confirmed* by a `TalentAdmin` — a deliberate
        segregation of duties, since the processor who prepared and approved the batch
        may not confirm it — moving the batch to `CONFIRMED_PAID`".
        PRD §2.1: "A request whose role is recognized but not listed among the roles
        authorized for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        PayrollProcessor confirm: 403; TalentAdmin confirm: CONFIRMED_PAID.

        Design: Corner/rbac/payroll_processor_cannot_confirm_paid_returns_forbidden
        """
        pp = TEST_USERS["payroll_processor_headers"]
        ta = TEST_USERS["talent_admin_headers"]
        batch = create_open_batch()
        get_success_data(api.seal_payroll_batch(batch["id"], pp))
        get_success_data(api.export_payroll_batch(batch["id"], pp))

        resp = api.confirm_paid_payroll_batch(batch["id"], pp)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        data = get_success_data(api.confirm_paid_payroll_batch(batch["id"], ta))
        assert data["status"] == "CONFIRMED_PAID"


class TestRecruiterCannotApprove:
    def test_recruiter_cannot_approve_milestone_returns_forbidden(self, api):
        """PRD §3.6: "An earned milestone becomes spendable only after a
        `PayrollProcessor` approves it, moving it from `EARNED` to `APPROVED`."
        PRD §2.1: "A request whose role is recognized but not listed among the roles
        authorized for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        A Recruiter attempt is 403 and the milestone remains EARNED.

        Design: Corner/rbac/recruiter_cannot_approve_milestone_returns_forbidden
        """
        program = setup_program()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        ref = submit_referral(emp["id"], program["req"]["id"], candidate_email="c1@x.com",
                              candidate_full_name="C One")
        advance_referral_to_offer(ref["id"], program["rec"]["id"], program["hm"]["id"])
        hire_referral(ref["id"], program["hm"]["id"])
        ms = get_hire_milestone(ref["id"])

        rec_h = make_recruiter_headers(program["rec"]["id"])
        resp = api.approve_milestone(ms["id"], rec_h)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        ms_now = get_milestone(ms["id"])
        assert ms_now["status"] == "EARNED"


class TestEmployeeOwnershipScoping:
    def test_employee_cannot_submit_for_other_referrer_returns_forbidden(self, api):
        """PRD §2.1: "An `Employee`-role caller may only act as or on behalf of itself:
        submitting a referral requires `referrer_id` to equal `X-User-ID`, withdrawing a
        referral is only permitted to its own referrer, updating a tax profile is only
        permitted on the caller's own employee record, and reading referrals through the
        per-employee or per-referral views is scoped to the caller's own records. A
        violation of this scoping is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §3.3: "The actor is either an `Employee` referring on their own behalf (the
        payload's `referrer_id` must equal the caller's `X-User-ID`) or a `Recruiter`
        submitting on behalf of a named referrer."

        Employee submitting with another's referrer_id: 403. Recruiter on behalf of the
        same referrer: 201.

        Design: Corner/rbac/employee_cannot_submit_for_other_referrer_returns_forbidden
        """
        program = setup_program()
        emp_a = create_employee(employee_number="E101", full_name="Ann A", email="anna@corp.com")
        emp_b = create_employee(employee_number="E102", full_name="Bob B", email="bob@corp.com")

        resp = api.create_referral(
            create_referral_payload(
                referrer_id=emp_b["id"], job_requisition_id=program["req"]["id"],
                candidate_email="c1@x.com", candidate_full_name="C One",
            ),
            make_employee_headers(emp_a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        rec_h = make_recruiter_headers(program["rec"]["id"])
        ok = api.create_referral(
            create_referral_payload(
                referrer_id=emp_b["id"], job_requisition_id=program["req"]["id"],
                candidate_email="c1@x.com", candidate_full_name="C One",
            ),
            rec_h,
        )
        data = validate_success(ok, 201)
        assert data["status"] == "SUBMITTED"

    def test_employee_read_scoped_to_own_referrals(self, api):
        """PRD §4: "the `Employee` role's list of referrals is always scoped to its own
        records."
        PRD §2.1: "reading referrals through the per-employee or per-referral views is
        scoped to the caller's own records. A violation of this scoping is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."

        The Employee list returns only the caller's own referral; reading another
        employee's referral by id is 403.

        Design: Corner/rbac/employee_read_scoped_to_own_referrals
        """
        program = setup_program(req_overrides={"openings": 5})
        emp_a = create_employee(employee_number="E101", full_name="Ann A", email="anna@corp.com")
        emp_b = create_employee(employee_number="E102", full_name="Bob B", email="bob@corp.com")
        ref_a = submit_referral(emp_a["id"], program["req"]["id"], candidate_email="c1@x.com",
                                candidate_full_name="C One")
        ref_b = submit_referral(emp_b["id"], program["req"]["id"], candidate_email="c2@x.com",
                                candidate_full_name="C Two")

        rows, meta = validate_paginated(
            api.list_referrals(make_employee_headers(emp_a["id"]), params={"limit": 10, "offset": 0})
        )
        assert len(rows) == 1
        assert rows[0]["id"] == ref_a["id"]
        assert meta["total_count"] == 1

        resp = api.get_referral(ref_b["id"], make_employee_headers(emp_a["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestTerminatedReferrerCannotSubmit:
    def test_terminated_referrer_cannot_submit_returns_referrer_not_active(self, api):
        """PRD §3.3: "The referrer's `employment_status` must be `ACTIVE`; a non-active
        (in practice `TERMINATED`) referrer is rejected with `ERR_REFERRER_NOT_ACTIVE`
        (HTTP 422)."

        Design: Corner/rbac/terminated_referrer_cannot_submit_returns_referrer_not_active
        """
        create_active_policy()
        emp = create_employee(employee_number="E101", email="anna@corp.com")
        pa = TEST_USERS["platform_admin_headers"]
        get_success_data(api.terminate_employee(emp["id"], pa))
        req = create_open_requisition()

        resp = api.create_referral(
            create_referral_payload(
                referrer_id=emp["id"], job_requisition_id=req["id"],
                candidate_email="c1@x.com", candidate_full_name="C One",
            ),
            make_employee_headers(emp["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REFERRER_NOT_ACTIVE)
