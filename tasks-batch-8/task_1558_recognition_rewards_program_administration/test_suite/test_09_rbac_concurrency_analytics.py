"""RBAC denials, optimistic-concurrency guards, the logical clock, and the
participation / inclusion analytics read model."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_accrual_run_payload,
    create_and_activate_program,
    create_budget,
    create_budget_payload,
    create_department,
    create_employee,
    create_program,
    create_redemption_order_payload,
    get_success_data,
    make_employee_headers,
    make_manager_headers,
    setup_catalog,
    setup_employee_with_grant,
    setup_program_with_budget,
    submit_nomination,
    validate_error,
    validate_success,
)

HR = TEST_USERS["hr_admin_headers"]


class TestRoleAuthorization:
    def test_employee_cannot_approve_nomination(self, api, hr_admin_headers):
        """PRD §4 lists POST /api/nominations/{nominationId}/approve as
        authorized for the Manager and HRAdmin roles only.
        PRD §2.1: "Once the caller is identified, the role is checked against
        the endpoint's authorization rules; a role that is not permitted — or
        an entity-backed identity attempting to act on another user's resource
        — is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/employee_cannot_approve_nomination
        """
        ctx = setup_program_with_budget(
            program_overrides={"max_points_per_nomination": 1000},
            allocated_points=10000, num_extra_employees=2,
        )
        e1, e3 = ctx["extras"][0], ctx["extras"][1]
        nomination = submit_nomination(
            ctx["program"]["id"], ctx["employee"]["id"], e1, 100,
            type="PEER", reason_code="TEAMWORK", idempotency_key="rbac-1",
        )
        res = api.approve_nomination(
            nomination["id"], nomination["version"],
            make_employee_headers(e3["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        current = validate_success(
            api.get_nomination(nomination["id"], hr_admin_headers), 200
        )
        assert current["status"] == "PENDING_REVIEW"

    def test_finance_admin_cannot_finalize_tax_year(self, api, finance_admin_headers):
        """PRD §2.1: "The `FinanceAdmin` runs accruals but cannot touch
        payroll compensation or tax-year finalization". PRD §4 lists
        POST /api/programs/{programId}/finalize-tax-year as authorized for the
        PayrollSpecialist role only.

        Design: Corner/rbac/finance_admin_cannot_finalize_tax_year
        """
        program = create_and_activate_program()
        res = api.finalize_tax_year(program["id"], 2026, finance_admin_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_payroll_specialist_cannot_create_accrual_run(
        self, api, payroll_specialist_headers
    ):
        """PRD §2.1: "the `PayrollSpecialist` finalizes tax years but cannot
        create or close accrual runs". PRD §4 lists POST /api/accrual-runs as
        authorized for the FinanceAdmin role only.

        Design: Corner/rbac/payroll_specialist_cannot_create_accrual_run
        """
        program = create_and_activate_program()
        res = api.create_accrual_run(
            create_accrual_run_payload(program["id"], 2026, 8),
            payroll_specialist_headers,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_vendor_ops_cannot_create_budget(self, api, vendor_ops_headers):
        """PRD §4 lists POST /api/budgets as authorized for the FinanceAdmin
        role only, and PRD §2.1 states that "a role that is not permitted —
        or an entity-backed identity attempting to act on another user's
        resource — is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/vendor_ops_cannot_create_budget
        """
        program = create_and_activate_program()
        dept = create_department()
        res = api.create_budget(
            create_budget_payload(program["id"], dept["id"], allocated_points=1000),
            vendor_ops_headers,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_employee_cannot_cancel_others_order(self, api, hr_admin_headers):
        """PRD §2.8 stage 2: "the caller's `X-User-ID` must equal the
        resource's employee or nominator identifier (`ERR_FORBIDDEN_FOR_ROLE`)".
        PRD §3.5: "an `Employee` acting on someone else's order is refused
        with `ERR_FORBIDDEN_FOR_ROLE`."

        Design: Corner/rbac/employee_cannot_cancel_others_order
        """
        ctx = setup_employee_with_grant(1000)
        owner = ctx["employee"]
        other = create_employee(ctx["dept"]["id"], employee_ref="OTHER-1",
                                hire_date="2022-01-01")
        _, item = setup_catalog()
        order = validate_success(api.create_redemption_order(
            create_redemption_order_payload(item["id"], idempotency_key="rbac-own-r1"),
            make_employee_headers(owner["id"]),
        ), 201)
        res = api.cancel_redemption_order(
            order["id"], make_employee_headers(other["id"])
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        current = validate_success(
            api.get_redemption_order(order["id"], hr_admin_headers), 200
        )
        assert current["fulfillment_status"] == "PENDING_SUBMISSION"

    def test_missing_user_headers_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying a malformed
        one, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
        (HTTP 400)."

        Design: Corner/rbac/missing_user_headers_unauthenticated
        """
        res = api.list_employees(headers={})
        validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_get_endpoints_open_to_all_roles(
        self, api, vendor_ops_headers, payroll_specialist_headers
    ):
        """PRD §2.1: "All six roles may call every read endpoint."

        Design: Corner/rbac/get_endpoints_open_to_all_roles
        """
        program = create_program()
        for headers in (vendor_ops_headers, payroll_specialist_headers):
            fetched = validate_success(api.get_program(program["id"], headers), 200)
            assert fetched["name"] == program["name"]


class TestOptimisticConcurrency:
    def test_program_patch_stale_version_rejected_then_fresh_succeeds(
        self, api, hr_admin_headers
    ):
        """PRD §2.7: "Updating a program's configuration through
        `PATCH /api/programs/{programId}` requires `expected_program_version`,
        matching the program's current `version`." and "In all three cases, a
        mismatch between the supplied version and the resource's current
        `version` is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_program_patch_stale_version
        """
        program = create_program()
        stale_version = program["version"]
        bumped = validate_success(api.update_program(
            program["id"],
            {"max_points_per_nomination": 2000,
             "expected_program_version": stale_version},
            hr_admin_headers,
        ), 200)
        assert bumped["version"] == stale_version + 1

        res = api.update_program(
            program["id"],
            {"duplicate_window_days": 45,
             "expected_program_version": stale_version},
            hr_admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)

        fresh = validate_success(api.update_program(
            program["id"],
            {"duplicate_window_days": 45,
             "expected_program_version": bumped["version"]},
            hr_admin_headers,
        ), 200)
        assert fresh["duplicate_window_days"] == 45
        assert fresh["version"] == bumped["version"] + 1

    def test_nomination_approve_stale_after_resubmit_then_fresh_succeeds(
        self, api, hr_admin_headers
    ):
        """PRD §2.7: "Approving a nomination through
        `POST /api/nominations/{nominationId}/approve` requires
        `expected_nomination_version`, matching the nomination's current
        `version`. An approver reviews a nomination as of a particular
        version; if the nominator resubmits with changed content in between —
        a resubmission legitimately succeeds and bumps the nomination's
        `version` — the approval no longer covers the current content and must
        be refused."

        Design: Corner/cross_cutting_layers/occ_nomination_approve_stale_version
        """
        ctx = setup_program_with_budget(
            program_overrides={"max_points_per_nomination": 5000},
            allocated_points=10000, num_extra_employees=1,
        )
        nominator, nominee, manager = (
            ctx["extras"][0], ctx["employee"], ctx["manager"],
        )
        nomination = submit_nomination(
            ctx["program"]["id"], nominee["id"], nominator, 100,
            type="PEER", reason_code="TEAMWORK", idempotency_key="occ-nom-1",
        )
        stale_version = nomination["version"]
        get_success_data(api.return_nomination_for_revision(
            nomination["id"], "more detail", make_manager_headers(manager["id"])
        ))
        resubmitted = validate_success(api.resubmit_nomination(
            nomination["id"], {"points_requested": 150, "message": "v3"},
            make_employee_headers(nominator["id"]),
        ), 200)

        res = api.approve_nomination(nomination["id"], stale_version, hr_admin_headers)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)

        approved = validate_success(api.approve_nomination(
            nomination["id"], resubmitted["version"], hr_admin_headers
        ), 200)
        assert approved["status"] == "APPROVED"


class TestLogicalClock:
    def test_clock_cannot_move_backward(self, api, hr_admin_headers):
        """PRD §2.5: "the clock never moves backward, and a `to_iso8601`
        earlier than the current logical instant is rejected with
        `ERR_INVALID_REQUEST`."

        Design: Corner/cross_cutting_layers/clock_cannot_move_backward
        """
        get_success_data(api.set_clock("2026-08-10T00:00:00Z", hr_admin_headers))
        res = api.set_clock("2026-08-05T00:00:00Z", hr_admin_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)
        current = validate_success(
            api.set_clock("2026-08-10T00:00:00Z", hr_admin_headers), 200
        )
        assert current["current_utc"].startswith("2026-08-10")


class TestParticipationAnalytics:
    def test_participation_rate_floor_and_department_disparity(
        self, api, hr_admin_headers
    ):
        """PRD §3.9: "`participation_rate_bp` is the total participating
        employees times ten thousand, divided by the total eligible employees,
        floored to basis points — and defined as 0 when no one is eligible.
        Per-department rates are computed the same way within each department;
        departments with zero eligible employees are excluded from the
        disparity calculation. `inclusion_disparity_bp` is then the gap
        between the highest and lowest included department rates, and is 0
        when fewer than two departments qualify."
        PRD §3.9: "An eligible employee is any employee whose department holds
        at least one budget in the program, regardless of window or posture; a
        participating employee is any distinct employee with at least one of —
        a nomination submitted in a status other than `CANCELLED`, an award
        granted, or a redemption order created — inside the window."

        Design: Corner/calculations/participation_analytics_floor_and_disparity
        """
        program = create_and_activate_program(max_points_per_nomination=1000)
        program_id = program["id"]
        dept_a = create_department(name="Eng", chargeback_account_code="GL-ENG")
        dept_b = create_department(name="Sales", chargeback_account_code="GL-SALES")
        create_budget(program_id, dept_a["id"], allocated_points=10000)
        create_budget(program_id, dept_b["id"], allocated_points=10000)

        a1 = create_employee(dept_a["id"], employee_ref="A1")
        a2 = create_employee(dept_a["id"], employee_ref="A2")
        a3 = create_employee(dept_a["id"], employee_ref="A3")
        for ref in ("B1", "B2", "B3", "B4"):
            create_employee(dept_b["id"], employee_ref=ref)

        # Three distinct dept-A participants; nobody in dept B participates.
        submit_nomination(program_id, a2["id"], a1, 10, type="PEER",
                          reason_code="TEAMWORK", idempotency_key="calc-pa-1")
        submit_nomination(program_id, a3["id"], a2, 10, type="PEER",
                          reason_code="TEAMWORK", idempotency_key="calc-pa-2")
        submit_nomination(program_id, a1["id"], a3, 10, type="PEER",
                          reason_code="TEAMWORK", idempotency_key="calc-pa-3")

        report = validate_success(
            api.get_participation_analytics(program_id, hr_admin_headers), 200
        )
        assert report["eligible_employees"] == 7
        assert report["participating_employees"] == 3
        # floor(3 x 10000 / 7) = 4285
        assert report["participation_rate_bp"] == 4285
        # dept A rate 10000 bp (3/3), dept B rate 0 bp (0/4) -> gap 10000.
        assert report["inclusion_disparity_bp"] == 10000
        assert report["window_days"] == 90
