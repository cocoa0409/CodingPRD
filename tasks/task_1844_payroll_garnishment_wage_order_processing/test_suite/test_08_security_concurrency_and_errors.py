"""Auth, RBAC, optimistic concurrency, and the referential-before-fiscal
validation ordering."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_statement,
    api_client,
    create_employee_payload,
    create_order_payload,
    employer_version,
    employee_version,
    get_payroll_run,
    make_employer,
    make_employee,
    make_open_run,
    make_state_rule,
    pay_run_payload,
    receive_order,
    set_clock,
    setup_employer_with_employee,
    validate_error,
)
from test_helpers.fixtures import AUDITOR, SPECIALIST


class TestReferentialBeatsFiscalOcc:
    def test_case_pattern_beats_stale_employee_version(self, api):
        """PRD §2.9: "Only then do the business rules engage, and they too are
        ordered: period-window and pay-calendar temporal checks first, then
        intake referential checks (authority, case-number pattern, state rule),
        then duplicate-order safety, then the stale-version rejection of §2.7,
        then fiscal amount checks (empty runs, deduction bounds), then
        terminated-employee ineligibility, then refund limits, then the
        posted-event void guard, then remittance emptiness, and finally
        remittable-event availability."
        PRD §3.3: "The order's `case_number` must match the issuing authority's
        `accepted_case_number_pattern`, else the intake is rejected with
        `ERR_CASE_NUMBER_PATTERN` (HTTP 422)."
        The intake below fails the `^CS-` pattern AND carries a stale
        expected_employee_version; the referential check must fire first.

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_occ
        """
        base = setup_employer_with_employee()
        ee_id = base["employee"]["id"]
        stale_v = base["employee"]["version"]
        # A legitimate order receipt advances the employee's version,
        # so the captured token is now stale.
        receive_order(ee_id, base["authority"]["id"], case_number="CS-OK")
        resp = api_client.create_order(
            ee_id,
            create_order_payload(
                base["authority"]["id"], stale_v, case_number="BAD-1"
            ),
            SPECIALIST,
        )
        validate_error(resp, ApiErrorId.ERR_CASE_NUMBER_PATTERN)
        assert resp.json()["data"]["error_id"] != ApiErrorId.ERR_STALE_VERSION

    def test_stale_version_surfaces_when_pattern_valid(self, api):
        """PRD §2.7: "Receiving a garnishment order against an employee
        requires `expected_employee_version`, carrying the caller's
        last-observed `version` of that employee. Because order intake and
        order termination both mutate the employee record through a cascade, a
        client whose view of the employee's order set is stale would make
        duplicate-priority and duplicate-order decisions on outdated data; a
        mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        Control for the priority pair: with a pattern-conforming case number,
        the same stale token now surfaces ERR_STALE_VERSION, proving the token
        was indeed stale in the paired test.

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_occ
        """
        base = setup_employer_with_employee()
        ee_id = base["employee"]["id"]
        stale_v = base["employee"]["version"]
        receive_order(ee_id, base["authority"]["id"], case_number="CS-OK")
        resp = api_client.create_order(
            ee_id,
            create_order_payload(
                base["authority"]["id"], stale_v, case_number="CS-OK2"
            ),
            SPECIALIST,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestAuthentication:
    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting operator, and `X-User-Role`, declaring the
        operator's capacity. A request missing either header, or carrying a
        malformed value, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
        The request below is dispatched with BOTH auth headers omitted.

        Design: Corner/validations/missing_auth_headers_unauthenticated
        """
        resp = api_client.get_employer(NON_EXISTENT_UUID, headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
        assert resp.status_code == 401


class TestOptimisticConcurrency:
    def test_stale_employer_version_on_run_pay(self, api):
        """PRD §2.7: "Paying a payroll run requires
        `expected_employer_version`. A prior paid run or a configuration change
        to the employer (its remittance timing or fee policy) advances the
        employer's `version`; paying against a stale view risks
        double-withholding across runs or applying a superseded fee policy, so
        the pay request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/validations/occ_stale_version_on_run_pay
        """
        set_clock()
        make_state_rule("CA")
        emp = make_employer()
        ee = make_employee(emp["id"])
        run = make_open_run(emp["id"])
        add_statement(run["id"], ee["id"])
        current_v = employer_version(emp["id"])
        resp = api_client.pay_run(
            run["id"], pay_run_payload(current_v - 1), SPECIALIST
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert resp.status_code == 412
        assert get_payroll_run(run["id"])["status"] == "OPEN"

    def test_stale_employee_version_on_order_create(self, api):
        """PRD §2.7: "Receiving a garnishment order against an employee
        requires `expected_employee_version`, carrying the caller's
        last-observed `version` of that employee. Because order intake and
        order termination both mutate the employee record through a cascade, a
        client whose view of the employee's order set is stale would make
        duplicate-priority and duplicate-order decisions on outdated data; a
        mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        The first order receipt bumps the employee's version; replaying the
        pre-receipt version on a second intake is rejected.

        Design: Corner/cross_cutting_layers/occ_order_create_stale_employee
        """
        base = setup_employer_with_employee()
        ee_id = base["employee"]["id"]
        stale_v = base["employee"]["version"]
        receive_order(ee_id, base["authority"]["id"], case_number="CS-O1")
        assert employee_version(ee_id) != stale_v
        resp = api_client.create_order(
            ee_id,
            create_order_payload(
                base["authority"]["id"], stale_v, case_number="CS-O2"
            ),
            SPECIALIST,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert resp.status_code == 412


class TestRbacDenials:
    def test_auditor_cannot_create_employee(self, api):
        """PRD §2.10: "The `compliance_auditor` holds no write capability at
        all, and employer-level configuration remains the exclusive province of
        the `employer_payroll_admin`."
        PRD §2.1: "Attempting an operation outside one's role is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/auditor_cannot_mutate
        """
        set_clock()
        make_state_rule("CA")
        emp = make_employer()
        resp = api_client.create_employee(
            create_employee_payload(emp["id"], employer_version(emp["id"])),
            AUDITOR,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert resp.status_code == 403


class TestNotFound:
    def test_get_nonexistent_order_returns_not_found(self, api):
        """PRD §2.9: "Requests that target nested resources are validated left
        to right along the path: the system confirms each identifier exists and
        belongs to its declared parent chain before examining the next, and the
        first unknown or out-of-scope identifier rejects the request with
        `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/get_nonexistent_order_returns_not_found
        """
        set_clock()
        resp = api_client.get_order(NON_EXISTENT_UUID, SPECIALIST)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert resp.status_code == 404
