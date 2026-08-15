"""Trial payment plan lifecycle: resolution rules, terminal cascades, gates."""
import pytest

from test_helpers import (
    OPS,
    UW,
    ApiErrorId,
    assert_timestamp_instant,
    board_loan,
    create_modification_payload,
    create_payment_payload,
    get_application,
    get_loan,
    get_plan_payments,
    get_success_data,
    get_trial_plan,
    make_borrower,
    make_borrower_headers,
    pay_on_time,
    refer_and_schedule,
    set_clock,
    setup_active_trial,
    setup_completed_trial,
    setup_offered_plan,
    setup_offered_plan_with_scheduled_sale,
    submit_application,
    validate_error,
    validate_success,
)


class TestPaymentResolution:
    def test_late_payment_fails_plan_and_denial_cascade(self, api):
        """PRD §3.7: "When the payment date (the logical clock's current date) is
        after `due_date`, the payment resolves `PAID_LATE` and the plan fails."
        PRD §3.7: "When the plan reaches `FAILED`, suspense is applied to arrears
        identically (partial payments still credit) and `suspense_cents` resets
        to zero; the application transitions from `TRIAL_ACTIVE` to
        `EVALUATED_DENIAL`, a new `DenialNotice` is created in `ISSUED` with
        `reasons` equal to [`TRIAL_PLAN_FAILED`] and `underwriter_user_id` set to
        the literal string `system`; and the loan's `workout_status` returns from
        `TRIAL` to `LOSS_MIT_REVIEW`."

        Design: Corner/calculations/trial_late_payment_fails_plan_and_denial_cascade
        """
        scenario = setup_active_trial(economics="A", eval_at="2026-08-06T00:00:00Z")
        p1 = scenario["payments"][0]  # due 2026-09-05
        set_clock("2026-09-06T00:00:00Z")  # one day past due
        paid = get_success_data(
            api.pay_trial_payment(
                p1["id"],
                create_payment_payload(p1["scheduled_amount_cents"]),
                make_borrower_headers(scenario["borrower"]["id"]),
            )
        )
        assert paid["status"] == "PAID_LATE"

        plan = get_trial_plan(scenario["plan"]["id"])
        assert plan["status"] == "FAILED"
        app = get_application(scenario["application"]["id"])
        assert app["status"] == "EVALUATED_DENIAL"
        notices = get_success_data(
            api.list_application_denial_notices(app["id"], UW)
        )
        assert len(notices) == 1
        assert notices[0]["reasons"] == ["TRIAL_PLAN_FAILED"]
        assert notices[0]["underwriter_user_id"] == "system"
        assert notices[0]["status"] == "ISSUED"
        loan = get_loan(scenario["loan"]["id"])
        assert loan["workout_status"] == "LOSS_MIT_REVIEW"
        # Suspense (178842) still credits arrears: 1200000 - 178842 = 1021158.
        assert loan["arrears_cents"] == 1_021_158
        assert loan["suspense_cents"] == 0

    def test_insufficient_payment_fails_plan(self, api):
        """PRD §3.7: "When the paid amount is less than `scheduled_amount_cents`,
        the payment resolves `PAID_INSUFFICIENT` and the plan fails."

        Design: Corner/calculations/trial_insufficient_payment_fails_plan
        """
        scenario = setup_active_trial(economics="A", eval_at="2026-08-06T00:00:00Z")
        p1 = scenario["payments"][0]  # due 2026-09-05, scheduled 178842
        set_clock("2026-09-05T00:00:00Z")  # on time, but one cent short
        paid = get_success_data(
            api.pay_trial_payment(
                p1["id"],
                create_payment_payload(178_841),
                make_borrower_headers(scenario["borrower"]["id"]),
            )
        )
        assert paid["status"] == "PAID_INSUFFICIENT"
        assert get_trial_plan(scenario["plan"]["id"])["status"] == "FAILED"
        assert (
            get_application(scenario["application"]["id"])["status"]
            == "EVALUATED_DENIAL"
        )

    def test_finalize_marks_past_due_payments_missed(self, api, ops_headers):
        """PRD §3.7: "A `ServicingOps` operator can also finalize a plan
        explicitly: any still-`SCHEDULED` payment whose `due_date` is strictly
        before today is marked `MISSED` (failing the plan); if instead all three
        payments are already `PAID_ON_TIME`, the plan completes."

        Design: Corner/calculations/trial_finalize_marks_missed_past_due
        """
        scenario = setup_active_trial(economics="A", eval_at="2026-08-06T00:00:00Z")
        # Dues: 2026-09-05, 2026-10-05, 2026-11-04. Clock: 2026-09-20.
        set_clock("2026-09-20T00:00:00Z")
        plan = get_success_data(api.finalize_trial_plan(scenario["plan"]["id"], ops_headers))
        assert plan["status"] == "FAILED"
        payments = get_plan_payments(scenario["plan"]["id"])
        assert payments[0]["status"] == "MISSED"      # due 2026-09-05 < today
        assert payments[1]["status"] == "SCHEDULED"   # due 2026-10-05, not past due
        assert payments[2]["status"] == "SCHEDULED"   # due 2026-11-04, not past due

    def test_zero_payment_amount_rejected(self, api):
        """PRD §3.7: "`amount_cents` must be strictly greater than zero;
        otherwise the request is rejected with `ERR_PAYMENT_AMOUNT_INVALID`."

        Design: Corner/validations/payment_amount_zero_rejected
        """
        scenario = setup_active_trial(economics="A")
        p1 = scenario["payments"][0]
        res = api.pay_trial_payment(
            p1["id"],
            create_payment_payload(0),
            make_borrower_headers(scenario["borrower"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_PAYMENT_AMOUNT_INVALID, expected_status=422)
        payment = [p for p in get_plan_payments(scenario["plan"]["id"]) if p["id"] == p1["id"]][0]
        assert payment["status"] == "SCHEDULED"
        assert get_trial_plan(scenario["plan"]["id"])["status"] == "ACTIVE"
        assert get_loan(scenario["loan"]["id"])["suspense_cents"] == 0


class TestTerminalLockdown:
    def test_pay_on_completed_plan_rejected(self, api):
        """PRD §3.7: "Resolution is a cascade of checks, in order:" ... "The plan
        must be `ACTIVE`, else `ERR_TRIAL_PLAN_NOT_ACTIVE`." — the plan check
        precedes "The payment must still be `SCHEDULED`, else
        `ERR_TRIAL_PAYMENT_RESOLVED`", so paying a completed plan's resolved
        payment fails on the plan gate.

        Design: Corner/state_machines/trial_plan_terminal_lockdown_pay_and_finalize
        """
        scenario = setup_completed_trial(economics="A", eval_at="2026-08-06T00:00:00Z")
        p1 = scenario["payments"][0]
        res = api.pay_trial_payment(
            p1["id"],
            create_payment_payload(p1["scheduled_amount_cents"]),
            make_borrower_headers(scenario["borrower"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_TRIAL_PLAN_NOT_ACTIVE, expected_status=409)
        assert get_trial_plan(scenario["plan"]["id"])["status"] == "COMPLETED"

    def test_finalize_on_completed_plan_rejected(self, api, ops_headers):
        """PRD §3.7: "The plan must be `ACTIVE`, else `ERR_TRIAL_PLAN_NOT_ACTIVE`."
        PRD §2.7: "7. **State preconditions** — each entity's state machine guards
        (application completeness, document resolvability, plan/payment/notice/
        appeal/modification/analysis/case state gates)".

        Design: Corner/state_machines/trial_plan_terminal_lockdown_pay_and_finalize
        """
        scenario = setup_completed_trial(economics="A", eval_at="2026-08-06T00:00:00Z")
        res = api.finalize_trial_plan(scenario["plan"]["id"], ops_headers)
        validate_error(res, ApiErrorId.ERR_TRIAL_PLAN_NOT_ACTIVE, expected_status=409)
        assert get_trial_plan(scenario["plan"]["id"])["status"] == "COMPLETED"


class TestTrialCompletionCascade:
    def test_third_on_time_payment_completes_plan(self, api):
        """PRD §3.7: "The plan completes when its third payment resolves
        `PAID_ON_TIME` — a plan with two on-time payments remains `ACTIVE`."
        PRD §3.7: "the amount is added to both the plan's `suspense_total_cents`
        and the loan's `suspense_cents`."

        Design: Difficulty/transitive_cascade/trial_third_payment_completion_cascade
        """
        scenario = setup_active_trial(economics="A", eval_at="2026-08-06T00:00:00Z")
        borrower_id = scenario["borrower"]["id"]
        pay_on_time(scenario["payments"][0], borrower_id)
        pay_on_time(scenario["payments"][1], borrower_id)
        mid_plan = get_trial_plan(scenario["plan"]["id"])
        assert mid_plan["status"] == "ACTIVE", "two on-time payments: still ACTIVE"

        p3 = scenario["payments"][2]
        # Pay the third installment exactly on its due date (2026-11-04).
        set_clock(f"{p3['due_date']}T00:00:00Z")
        paid = get_success_data(
            api.pay_trial_payment(
                p3["id"],
                create_payment_payload(p3["scheduled_amount_cents"]),
                make_borrower_headers(borrower_id),
            )
        )
        assert paid["status"] == "PAID_ON_TIME"
        plan = get_trial_plan(scenario["plan"]["id"])
        assert plan["status"] == "COMPLETED"
        assert plan["suspense_total_cents"] == 536_526  # 3 x 178842

    def test_plan_completion_cascades_to_application_and_loan(self, api):
        """PRD §3.7: "When the plan reaches `COMPLETED`, the loan's suspense is
        applied: `arrears_cents` is reduced by `suspense_total_cents`, clamped at
        zero; any positive overflow (suspense total exceeding arrears) reduces
        `unpaid_principal_balance_cents`; and `suspense_cents` is reset to zero.
        The application transitions from `TRIAL_ACTIVE` to `TRIAL_PASSED`, and
        the loan's `workout_status` moves from `TRIAL` to `MOD_PENDING`."

        Design: Difficulty/transitive_cascade/trial_third_payment_completion_cascade
        """
        scenario = setup_completed_trial(economics="A", eval_at="2026-08-06T00:00:00Z")
        assert scenario["application"]["status"] == "TRIAL_PASSED"
        loan = scenario["loan"]
        assert loan["workout_status"] == "MOD_PENDING"
        # arrears 1200000 - suspense 536526 = 663474; no principal overflow.
        assert loan["arrears_cents"] == 663_474
        assert loan["suspense_cents"] == 0
        assert loan["unpaid_principal_balance_cents"] == 20_000_000


class TestWithdrawalAndSupersessionGates:
    def test_withdraw_from_trial_active_rejected(self, api):
        """PRD §3.2: "Withdrawal is permitted from `SUBMITTED`, `ACKNOWLEDGED`,
        `COMPLETE_PACKAGE`, `EVALUATED_OFFER`, `EVALUATED_DENIAL`, or
        `APPEAL_REVIEW`; withdrawal from `TRIAL_ACTIVE`, `TRIAL_PASSED`, or any
        terminal state is rejected with `ERR_APPLICATION_STATE_INVALID`."

        Design: Corner/state_machines/withdraw_from_trial_active_rejected
        """
        scenario = setup_active_trial(economics="A")
        res = api.withdraw_application(
            scenario["application"]["id"],
            make_borrower_headers(scenario["borrower"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_APPLICATION_STATE_INVALID, expected_status=409)
        assert (
            get_application(scenario["application"]["id"])["status"] == "TRIAL_ACTIVE"
        )

    def test_supersede_blocked_while_prior_application_in_trial(self, api):
        """PRD §3.2: "Supersession is blocked outright when the existing
        non-terminal application is in `TRIAL_ACTIVE` or `TRIAL_PASSED`: in that
        case the create is rejected with `ERR_APPLICATION_STATE_INVALID`."

        Design: Corner/validations/supersede_blocked_while_prior_application_in_trial
        """
        scenario = setup_active_trial(economics="A")
        loan = get_loan(scenario["loan"]["id"])
        res = api.create_application(
            loan["id"],
            {
                "expected_loan_version": loan["version"],
                "hardship_type": "MEDICAL",
                "stated_monthly_income_cents": 500_000,
            },
            make_borrower_headers(scenario["borrower"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_APPLICATION_STATE_INVALID, expected_status=409)
        assert (
            get_application(scenario["application"]["id"])["status"] == "TRIAL_ACTIVE"
        )
        apps = get_success_data(api.list_loan_applications(loan["id"], OPS))
        assert len(apps) == 1, "no new application may be created"


class TestModificationCreationGate:
    def test_modification_rejected_while_plan_active(self, api, ops_headers):
        """PRD §3.10: "Preconditions: the referenced plan must be `COMPLETED`
        (else `ERR_TRIAL_PLAN_NOT_COMPLETED`), the application must be
        `TRIAL_PASSED`, and the loan's `workout_status` must be `MOD_PENDING`."

        Design: Difficulty/cross_entity_state_dependency/modification_create_gated_by_trial_plan_completion
        """
        scenario = setup_active_trial(economics="A", eval_at="2026-08-06T00:00:00Z")
        borrower_id = scenario["borrower"]["id"]
        pay_on_time(scenario["payments"][0], borrower_id)
        pay_on_time(scenario["payments"][1], borrower_id)
        # Plan still ACTIVE with one payment outstanding.
        res = api.create_modification(
            scenario["loan"]["id"],
            create_modification_payload(scenario["plan"]["id"]),
            ops_headers,
        )
        validate_error(res, ApiErrorId.ERR_TRIAL_PLAN_NOT_COMPLETED, expected_status=409)

    def test_modification_accepted_once_plan_completed(self, api, ops_headers):
        """PRD §3.10: "Once a trial plan is `COMPLETED`, a `ServicingOps`
        operator creates a permanent modification against the loan, supplying
        `trial_plan_id`." — "The modification is created in `DRAFT`".

        Design: Difficulty/cross_entity_state_dependency/modification_create_gated_by_trial_plan_completion
        """
        scenario = setup_completed_trial(economics="A", eval_at="2026-08-06T00:00:00Z")
        res = api.create_modification(
            scenario["loan"]["id"],
            create_modification_payload(scenario["plan"]["id"]),
            ops_headers,
        )
        mod = validate_success(res, 201)
        assert mod["status"] == "DRAFT"
        assert mod["trial_plan_id"] == scenario["plan"]["id"]


class TestTrialAcceptanceGates:
    def test_accept_rejected_after_foreclosure_sale_completed(self, api, counsel_headers):
        """PRD §3.7: "Acceptance is rejected with `ERR_TRIAL_PLAN_NOT_OFFERED`
        when the plan is not `OFFERED` (including attempts after
        `offer_deadline`), with `ERR_LOAN_FORECLOSURE_COMPLETED` when the loan's
        `foreclosure_status` is `SALE_COMPLETED`, and only one plan may be
        `OFFERED` or `ACTIVE` for a loan at any time."
        PRD §3.9: "This terminal-locks the loan's workout dimension: any
        subsequent workout-side action (trial-plan acceptance, further state
        transitions) is rejected with `ERR_LOAN_FORECLOSURE_COMPLETED`."

        Design: Difficulty/cross_entity_state_dependency/trial_accept_gated_by_loan_foreclosure_status
        """
        scenario = setup_offered_plan_with_scheduled_sale(sale_date="2026-12-01")
        get_success_data(api.complete_sale(scenario["case"]["id"], counsel_headers))
        res = api.accept_trial_plan(
            scenario["plan"]["id"],
            make_borrower_headers(scenario["borrower"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_LOAN_FORECLOSURE_COMPLETED, expected_status=409)

    def test_plan_remains_offered_after_completed_sale_blocks_accept(self, api, counsel_headers):
        """PRD §3.9: "Marking the sale held requires the case to be in
        `SALE_SCHEDULED` (else `ERR_FORECLOSURE_STATE_INVALID`) and moves it to
        `SALE_COMPLETED`. This terminal-locks the loan's workout dimension: any
        subsequent workout-side action (trial-plan acceptance, further state
        transitions) is rejected with `ERR_LOAN_FORECLOSURE_COMPLETED`."

        Design: Difficulty/cross_entity_state_dependency/trial_accept_gated_by_loan_foreclosure_status
        """
        scenario = setup_offered_plan_with_scheduled_sale(sale_date="2026-12-01")
        get_success_data(api.complete_sale(scenario["case"]["id"], counsel_headers))
        loan = get_loan(scenario["loan"]["id"])
        assert loan["foreclosure_status"] == "SALE_COMPLETED"
        res = api.accept_trial_plan(
            scenario["plan"]["id"],
            make_borrower_headers(scenario["borrower"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_LOAN_FORECLOSURE_COMPLETED, expected_status=409)
        assert get_trial_plan(scenario["plan"]["id"])["status"] == "OFFERED"

    def test_offer_deadline_inclusive_boundary(self, api):
        """PRD §3.7: "The plan's `offer_deadline` is the plan creation instant
        plus thirty days; borrower acceptance is valid only at or before this
        instant."
        PRD §3.7: "Acceptance is rejected with `ERR_TRIAL_PLAN_NOT_OFFERED` when
        the plan is not `OFFERED` (including attempts after `offer_deadline`)"

        Design: Corner/complexity_layers/offer_deadline_inclusive_boundary
        """
        plan_a_scenario = setup_offered_plan(economics="A", eval_at="2026-08-06T00:00:00Z")
        plan_b_scenario = setup_offered_plan(
            economics="A", eval_at="2026-08-06T00:00:00Z",
            # Distinct program identity: code and waterfall_rank are unique.
            program_overrides={"code": "STD_MOD_B", "waterfall_rank": 2},
        )
        plan_a = plan_a_scenario["plan"]
        plan_b = plan_b_scenario["plan"]
        # Both plans were created at 2026-08-06 -> offer_deadline 2026-09-05.
        assert_timestamp_instant(plan_a["offer_deadline"], "2026-09-05T00:00:00Z")
        assert_timestamp_instant(plan_b["offer_deadline"], "2026-09-05T00:00:00Z")

        set_clock("2026-09-05T00:00:00Z")  # exactly at the deadline: allowed
        accepted = validate_success(
            api.accept_trial_plan(
                plan_a["id"],
                make_borrower_headers(plan_a_scenario["borrower"]["id"]),
            ),
            200,
        )
        assert accepted["status"] == "ACTIVE"

        set_clock("2026-09-06T00:00:00Z")  # one day past the deadline: rejected
        res = api.accept_trial_plan(
            plan_b["id"],
            make_borrower_headers(plan_b_scenario["borrower"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_TRIAL_PLAN_NOT_OFFERED, expected_status=409)
        assert get_trial_plan(plan_b["id"])["status"] == "OFFERED"


class TestImmediateConsistency:
    def test_accept_response_carries_mutation(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD §3.7: "The borrower accepts an `OFFERED` plan, which stamps
        `accepted_at`, transitions the plan to `ACTIVE`, the application from
        `EVALUATED_OFFER` to `TRIAL_ACTIVE`, and the loan's `workout_status` from
        `LOSS_MIT_REVIEW` to `TRIAL`."

        Design: Corner/consistency_model/immediate_consistency_mutation_visible_in_same_response
        """
        scenario = setup_offered_plan(economics="A")
        set_clock("2026-08-20T00:00:00Z")
        accepted = validate_success(
            api.accept_trial_plan(
                scenario["plan"]["id"],
                make_borrower_headers(scenario["borrower"]["id"]),
            ),
            200,
        )
        assert accepted["status"] == "ACTIVE"
        assert_timestamp_instant(accepted["accepted_at"], "2026-08-20T00:00:00Z")
        reread = validate_success(api.get_trial_plan(scenario["plan"]["id"], OPS), 200)
        assert reread["status"] == accepted["status"]
        assert reread["accepted_at"] == accepted["accepted_at"]
