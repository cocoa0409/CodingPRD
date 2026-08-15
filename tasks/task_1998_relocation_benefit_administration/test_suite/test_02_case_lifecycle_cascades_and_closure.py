"""Case lifecycle: invalid transitions, terminal lockdown, closure gates, cascades."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_employee_headers,
    assert_case_ledger,
    create_policy,
    create_employee,
    create_case,
    authorize_case,
    create_case_in_progress,
    setup_case_with_vendor,
    create_assignment_in_state,
    create_housing_booking,
    create_completed_travel_booking,
    confirm_booking,
    complete_booking,
    create_claim,
    create_home_sale,
    create_booking_payload,
    set_clock,
    get_case,
    terminate_employee,
    terminate_case_early,
    setup_repayment_case,
    get_case_repayment_agreement,
    DATES,
)

MC = TEST_USERS["coordinator_headers"]
FIN = TEST_USERS["finance_headers"]


class TestCaseTransitionGuards:
    def test_authorize_in_progress_case_rejected(self):
        """PRD §3.2: "Authorization by a coordinator moves the case `DRAFT` →
        `AUTHORIZED` and stamps `authorized_at` from the logical clock"
        PRD §2.10: "State validity**: the target resource is in a legal source
        state for the requested transition (`ERR_INVALID_STATE`, HTTP 409)"

        Design: Corner/state_machines/authorize_in_progress_case_rejected
        """
        ctx = create_case_in_progress()
        case_id = ctx["case"]["id"]
        resp = api_client.authorize_case(case_id, MC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_case(case_id)["status"] == "IN_PROGRESS"

    def test_cancel_closed_case_returns_already_terminal(self):
        """PRD §2.10: "a transition attempted from a terminal state is rejected
        distinctly with `ERR_ALREADY_TERMINAL` (HTTP 409). Terminal states are
        `CLOSED`, `CLOSED_EARLY`, and `CANCELLED` for cases"
        PRD §3.8: "any transition attempted on an already-terminal case,
        assignment, booking, claim, home sale, agreement, or decided exception
        request is rejected with `ERR_ALREADY_TERMINAL`."

        Design: Corner/state_machines/cancel_closed_case_returns_already_terminal
        """
        ctx = create_case_in_progress()
        case_id = ctx["case"]["id"]
        closed = get_success_data(api_client.close_case(case_id, MC))
        assert closed["status"] == "CLOSED"
        resp = api_client.cancel_case(case_id, MC)
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)
        assert get_case(case_id)["status"] == "CLOSED"

    def test_create_booking_on_draft_case_rejected(self):
        """PRD §3.2: "Only an `IN_PROGRESS` case accepts child work — vendor
        assignments, bookings, claims, the home-sale program, and exception
        requests are all created against open cases, and child actions generally
        require the case to remain `IN_PROGRESS`; violations surface as
        `ERR_CASE_NOT_OPEN`."

        Design: Corner/validations/create_booking_on_draft_case_rejected
        """
        create_policy()
        employee = create_employee(full_name="Draft Drew")
        case = create_case(employee["id"])  # stays DRAFT
        resp = api_client.create_service_booking(
            create_booking_payload(case["id"], kind="TRAVEL", amount_cents=30000),
            make_employee_headers(employee["id"]))
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_OPEN)

    def test_case_close_with_open_booking_rejected(self):
        """PRD §3.8: "Closing directly from `IN_PROGRESS` requires that no
        assignment of the case remains in a non-terminal state, that no booking
        is `HELD` or `CONFIRMED`, that no claim is `SUBMITTED` or `APPROVED`,
        that no home-sale transaction is `LISTED` or `SOLD`, and that no
        repayment agreement exists in any state other than `SETTLED`."

        Design: Corner/state_machines/case_close_with_open_booking_rejected
        """
        ctx = create_case_in_progress()
        case_id = ctx["case"]["id"]
        emp_id = ctx["employee"]["id"]
        booking = create_housing_booking(case_id, emp_id,
                                         start_date="2026-10-01T00:00:00Z",
                                         end_date="2026-10-04T00:00:00Z",
                                         nightly_cents=10000)
        confirm_booking(booking["id"])

        resp = api_client.close_case(case_id, MC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        complete_booking(booking["id"])
        closed = get_success_data(api_client.close_case(case_id, MC))
        assert closed["status"] == "CLOSED"


class TestTerminateEarlyGate:
    def test_terminate_early_requires_terminated_employee(self):
        """PRD §3.8: "Once the employee's record shows `TERMINATED` — attempting
        the transition while the employee is still `ACTIVE` is rejected with
        `ERR_EMPLOYEE_NOT_TERMINATED` — a coordinator moves the case
        `IN_PROGRESS` → `CLOSED_EARLY`."

        Design: Difficulty/cross_entity_state_dependency/terminate_early_requires_terminated_employee
        """
        ctx = create_case_in_progress()
        case_id = ctx["case"]["id"]
        emp_id = ctx["employee"]["id"]

        resp = api_client.terminate_early_case(case_id, MC)
        validate_error(resp, ApiErrorId.ERR_EMPLOYEE_NOT_TERMINATED)
        assert get_case(case_id)["status"] == "IN_PROGRESS"

        terminate_employee(emp_id)
        closed_early = get_success_data(api_client.terminate_early_case(case_id, MC))
        assert closed_early["status"] == "CLOSED_EARLY"

    def test_authorize_rejected_once_employee_terminated(self):
        """PRD §3.2: "Only an `ACTIVE` employee may be put into motion: case
        creation, and later the authorization step, are both rejected with
        `ERR_EMPLOYEE_NOT_ACTIVE` when the employee has already been terminated."

        Design: Difficulty/cross_entity_state_dependency/terminate_early_requires_terminated_employee
        """
        create_policy()
        employee = create_employee(full_name="Gate Gail")
        case = create_case(employee["id"])  # DRAFT
        terminate_employee(employee["id"])

        resp = api_client.authorize_case(case["id"], MC)
        validate_error(resp, ApiErrorId.ERR_EMPLOYEE_NOT_ACTIVE)
        assert get_case(case["id"])["status"] == "DRAFT"


class TestClosureGatedOnRepayment:
    def test_close_blocked_until_repayment_settled(self):
        """PRD §3.8: "Closing from `CLOSED_EARLY` is gated purely on the
        repayment obligation: an agreement in `DRAFT`, `ACTIVE`, or `DEFAULTED`
        blocks closure."
        PRD §3.8: "When a payment brings the balance to zero the agreement
        settles itself"

        Design: Difficulty/cross_entity_state_dependency/close_blocked_until_repayment_settled
        """
        ctx = setup_repayment_case(paid_amount=61000, sign=True)
        case_id = ctx["case"]["id"]
        agreement = ctx["agreement"]
        assert agreement["status"] == "ACTIVE"

        resp = api_client.close_case(case_id, MC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        paid = get_success_data(api_client.record_payment(
            agreement["id"], {"amount_cents": 45750}, FIN))
        assert paid["status"] == "SETTLED"
        assert paid["balance_cents"] == 0

        closed = get_success_data(api_client.close_case(case_id, MC))
        assert closed["status"] == "CLOSED"

    def test_close_blocked_while_agreement_is_draft(self):
        """PRD §3.8: "Closing from `CLOSED_EARLY` is gated purely on the
        repayment obligation: an agreement in `DRAFT`, `ACTIVE`, or `DEFAULTED`
        blocks closure."

        Design: Difficulty/cross_entity_state_dependency/close_blocked_until_repayment_settled
        """
        ctx = setup_repayment_case(paid_amount=61000, sign=False)
        case_id = ctx["case"]["id"]
        agreement = ctx["agreement"]
        assert agreement["status"] == "DRAFT"

        resp = api_client.close_case(case_id, MC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        set_clock(DATES["SIGN_AT"])
        signed = get_success_data(api_client.sign_agreement(
            agreement["id"], make_employee_headers(ctx["employee"]["id"])))
        assert signed["status"] == "ACTIVE"
        get_success_data(api_client.record_payment(
            agreement["id"], {"amount_cents": 45750}, FIN))
        closed = get_success_data(api_client.close_case(case_id, MC))
        assert closed["status"] == "CLOSED"


class TestCancelCascade:
    def test_cancel_case_release_depth2_cascade(self):
        """PRD §3.8: "Cancelling an `IN_PROGRESS` case is heavier and cascades.
        Every non-terminal assignment — any in `REQUESTED`, `SURVEY_SCHEDULED`,
        `ESTIMATE_SUBMITTED`, `ESTIMATE_APPROVED`, `DELIVERED`, or `INVOICED` —
        becomes `CANCELLED`, and every booking in `HELD` or `CONFIRMED` becomes
        `CANCELLED`."
        PRD §3.8: "Each cancelled assignment that held an approved estimate —
        those in `ESTIMATE_APPROVED`, `DELIVERED`, or `INVOICED` — and each
        cancelled `CONFIRMED` booking releases its held commitment:
        `total_committed_cents` falls and `total_released_cents` rises by the
        held amount"

        Design: Difficulty/transitive_cascade/cancel_case_release_depth2_cascade
        """
        ctx = setup_case_with_vendor()
        case_id = ctx["case"]["id"]
        vendor_id = ctx["vendor"]["id"]
        ma = create_assignment_in_state(case_id, vendor_id, "ESTIMATE_APPROVED",
                                        estimated_cents=80000)
        assert get_case(case_id)["total_committed_cents"] == 80000

        cancelled = get_success_data(api_client.cancel_case(case_id, MC))
        assert cancelled["status"] == "CANCELLED"

        ma_after = validate_success(api_client.get_move_assignment(ma["id"], MC))
        assert ma_after["status"] == "CANCELLED"
        case_after = get_case(case_id)
        assert_case_ledger(case_after, committed=0, paid=0, released=80000)

    def test_cancel_authorized_case_touches_nothing(self):
        """PRD §3.2: "A case still in `AUTHORIZED` may also be cancelled
        outright, and because no children can exist before work starts, that
        cancellation touches nothing beyond the case itself."

        Design: Difficulty/transitive_cascade/cancel_case_release_depth2_cascade
        """
        create_policy()
        employee = create_employee(full_name="Cancel Cass")
        case = create_case(employee["id"])
        authorize_case(case["id"])

        cancelled = get_success_data(api_client.cancel_case(case["id"], MC))
        assert cancelled["status"] == "CANCELLED"
        assert_case_ledger(cancelled, committed=0, paid=0, released=0)
        assert cancelled["cumulative_taxable_paid_cents"] == 0


class TestEarlyDepartureDepth3Cascade:
    def test_early_departure_depth3_cascade(self):
        """PRD §3.8: "The same child-cancellation and fund-release cascade
        fires, the paid column stands final, and the system assesses a repayment
        obligation."
        PRD §3.8: "the system creates a `RepaymentAgreement` in `DRAFT` — one
        per case at most — stamped with the case's `id` as its `case_id` and a
        `total_owed_cents` equal to the case's `total_paid_cents` at closure
        multiplied by the months remaining and divided by
        `repayment_window_months`, rounded half up to a whole cent."

        Design: Difficulty/transitive_cascade/early_departure_depth3_cascade
        """
        ctx = create_case_in_progress()
        case_id = ctx["case"]["id"]
        emp_id = ctx["employee"]["id"]

        housing = create_housing_booking(case_id, emp_id,
                                         start_date="2026-09-01T00:00:00Z",
                                         end_date="2026-09-10T00:00:00Z",
                                         nightly_cents=15000)
        confirm_booking(housing["id"])  # 9 nights x 15000 = 135000 committed
        create_completed_travel_booking(case_id, emp_id, 61000)  # 61000 paid

        set_clock(DATES["TERMINATE_AT"])
        terminate_employee(emp_id)
        closed_early = terminate_case_early(case_id)
        assert closed_early["status"] == "CLOSED_EARLY"

        booking_after = validate_success(
            api_client.get_service_booking(housing["id"], MC))
        assert booking_after["status"] == "CANCELLED"

        case_after = get_case(case_id)
        assert_case_ledger(case_after, committed=0, paid=61000, released=135000)

        agreement = get_case_repayment_agreement(case_id)
        assert agreement["status"] == "DRAFT"
        # authorized 2026-08-01 + 24 months = 2028-08-01; terminated 2027-02-01
        # -> 18 whole months remaining; owed = round_half_up(61000 x 18/24).
        assert agreement["total_owed_cents"] == 45750
        assert agreement["installments_count"] == 24

    def test_early_departure_cascade_leaves_claims_and_home_sales_untouched(self):
        """PRD §3.8: "Expense claims and home-sale transactions are deliberately
        left untouched by the cascade."
        PRD §3.8: "The same child-cancellation and fund-release cascade fires,
        the paid column stands final, and the system assesses a repayment
        obligation."

        Design: Difficulty/transitive_cascade/early_departure_depth3_cascade
        """
        ctx = create_case_in_progress(
            policy_overrides={"job_level": "EXECUTIVE",
                              "home_ownership": "HOMEOWNER",
                              "home_sale_eligible": True,
                              "loss_on_sale_cap_cents": 4000000},
            employee_overrides={"job_level": "EXECUTIVE",
                                "home_ownership": "HOMEOWNER"})
        case_id = ctx["case"]["id"]
        emp_id = ctx["employee"]["id"]

        housing = create_housing_booking(case_id, emp_id,
                                         start_date="2026-09-01T00:00:00Z",
                                         end_date="2026-09-10T00:00:00Z",
                                         nightly_cents=15000)
        confirm_booking(housing["id"])
        create_completed_travel_booking(case_id, emp_id, 61000)
        claim = create_claim(case_id, emp_id, amount_cents=10000, category="MISC")
        home_sale = create_home_sale(case_id)

        set_clock(DATES["TERMINATE_AT"])
        terminate_employee(emp_id)
        closed_early = terminate_case_early(case_id)
        assert closed_early["status"] == "CLOSED_EARLY"

        booking_after = validate_success(
            api_client.get_service_booking(housing["id"], MC))
        assert booking_after["status"] == "CANCELLED"

        claim_after = validate_success(api_client.get_expense_claim(claim["id"], MC))
        assert claim_after["status"] == "SUBMITTED", "claims are untouched by the cascade"

        home_sale_after = validate_success(api_client.get_home_sale(home_sale["id"], MC))
        assert home_sale_after["status"] == "LISTED", "home sales are untouched by the cascade"

        case_after = get_case(case_id)
        assert_case_ledger(case_after, committed=0, paid=61000, released=135000)

        agreement = get_case_repayment_agreement(case_id)
        assert agreement["total_owed_cents"] == 45750
        assert agreement["status"] == "DRAFT"
