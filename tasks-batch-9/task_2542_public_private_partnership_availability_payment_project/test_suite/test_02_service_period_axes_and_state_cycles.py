"""State machines that are not lines: two independent axes, a bounded referral
cycle and a step-in that can be re-entered after a cure."""
from test_helpers import api_client, validate_error, validate_success
from test_helpers.assertions import assert_net_payment_identity, assert_service_period
from test_helpers.factories import (
    adjudicate_dispute_payload,
    create_enforcement_action_payload,
    cure_enforcement_action_payload,
    pay_service_period_payload,
    refer_back_dispute_payload,
    reject_performance_report_payload,
    resubmit_dispute_payload,
    verify_service_period_payload,
)
from test_helpers.fixtures import (
    ALPHA,
    BETA,
    LENDER,
    list_enforcement_rows,
    raise_enforcement_action,
    refresh_concession,
    refresh_service_period,
    setup_disputed_deduction,
    setup_pending_service_period,
    setup_period_with_breaching_deduction,
    setup_self_reported_period,
    submit_performance_report,
)


class TestServicePeriodTwoAxes:
    def test_invoicing_before_verification_is_the_one_cross_axis_gate(self):
        """A PENDING period cannot be invoiced, and the payment axis does not move.

        PRD: "This is the one place where the two axes touch: invoicing requires
        the period's reporting axis to have reached `VERIFIED`, and attempting it on
        a period still in `PENDING` or `SELF_REPORTED` is refused with
        `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/service_period_two_axes_advance_independently_with_one_cross_axis_gate
        """
        ctx = setup_pending_service_period()

        response = api_client.invoice_service_period(
            ctx["service_period_id"], ctx["cnr_headers"]
        )

        validate_error(response, "ERR_INVALID_STATE_TRANSITION", 409)
        period = refresh_service_period(ctx)
        assert period["reporting_status"] == "PENDING"
        assert period["payment_status"] == "UNBILLED"

    def test_the_reporting_axis_reverts_to_pending_without_touching_the_payment_axis(self):
        """A report then its rejection walk the reporting axis out and back again.

        PRD: "The performance-monitoring axis runs `PENDING → SELF_REPORTED →
        VERIFIED`, with a revert edge back to `PENDING`, and it moves only under the
        reporting and verification operations."

        Design: Difficulty/non_linear_state_machine/service_period_two_axes_advance_independently_with_one_cross_axis_gate
        """
        ctx = setup_pending_service_period()

        first = submit_performance_report(
            ctx, 100, 2, 4, expected_service_period_version=ctx["service_period"]["version"]
        )
        period = refresh_service_period(ctx)
        assert period["reporting_status"] == "SELF_REPORTED"
        assert period["payment_status"] == "UNBILLED"
        assert period["version"] == 2

        response = api_client.reject_performance_report(
            first["id"], reject_performance_report_payload("minute log unsigned"), BETA
        )

        report = validate_success(response)
        assert report["status"] == "REJECTED"
        period = refresh_service_period(ctx)
        assert period["reporting_status"] == "PENDING"
        assert period["payment_status"] == "UNBILLED"

    def test_a_verified_period_stays_unbilled_until_the_payment_axis_is_driven(self):
        """Verification settles the money; invoicing and payment then move separately.

        PRD: "Otherwise the two are independent — a period may sit at `VERIFIED`
        while still `UNBILLED`, and a transition on one axis never reads or writes
        the other axis's field."

        Design: Difficulty/non_linear_state_machine/service_period_two_axes_advance_independently_with_one_cross_axis_gate
        """
        ctx = setup_self_reported_period()

        response = api_client.verify_service_period(
            ctx["service_period_id"], verify_service_period_payload(100, 2, 4), BETA
        )

        period = validate_success(response)
        assert_service_period(period)
        assert period["reporting_status"] == "VERIFIED"
        assert period["payment_status"] == "UNBILLED"
        assert period["availability_ratio"] == 0.9978
        assert period["net_payment_cents"] == 8604167
        assert_net_payment_identity(period)

        invoiced = validate_success(
            api_client.invoice_service_period(ctx["service_period_id"], ctx["cnr_headers"])
        )
        assert invoiced["payment_status"] == "INVOICED"
        assert invoiced["reporting_status"] == "VERIFIED"

        paid = validate_success(
            api_client.pay_service_period(
                ctx["service_period_id"],
                pay_service_period_payload("BACS-2027-04-0001"),
                BETA,
            )
        )
        assert paid["payment_status"] == "PAID"
        assert paid["reporting_status"] == "VERIFIED"


class TestDisputeReferralCycleIsBounded:
    def test_the_referral_loop_admits_exactly_three_submissions(self):
        """Two referral-and-resubmission exchanges exhaust the round budget.

        PRD: "The cycle `REFERRED_BACK → RESUBMITTED → REFERRED_BACK` may
        therefore repeat, but it is budgeted: neither a referral nor a resubmission
        may act on a dispute whose `round_no` has already reached three, so the
        referral loop admits exactly three submissions in total and must then be
        closed by adjudication."

        Design: Difficulty/non_linear_state_machine/dispute_referral_cycle_is_bounded_at_three_submissions
        """
        ctx = setup_disputed_deduction()
        dispute_id = ctx["dispute"]["id"]
        assert ctx["dispute"]["round_no"] == 1

        first_referral = validate_success(
            api_client.refer_back_deduction_dispute(
                dispute_id, refer_back_dispute_payload("supply the raw BMS extract"), BETA
            )
        )
        assert first_referral["status"] == "REFERRED_BACK"
        assert first_referral["round_no"] == 1

        second_round = validate_success(
            api_client.resubmit_deduction_dispute(
                dispute_id,
                resubmit_dispute_payload("BMS extract attached; minutes double counted"),
                ctx["cnr_headers"],
            )
        )
        assert second_round["status"] == "RESUBMITTED"
        assert second_round["round_no"] == 2

        validate_success(
            api_client.refer_back_deduction_dispute(
                dispute_id,
                refer_back_dispute_payload("extract unsigned by the certifier"),
                BETA,
            )
        )
        third_round = validate_success(
            api_client.resubmit_deduction_dispute(
                dispute_id,
                resubmit_dispute_payload("certifier-signed extract attached"),
                ctx["cnr_headers"],
            )
        )
        assert third_round["round_no"] == 3

        response = api_client.refer_back_deduction_dispute(
            dispute_id, refer_back_dispute_payload("third bite at the cherry"), BETA
        )

        validate_error(response, "ERR_DISPUTE_ROUNDS_EXHAUSTED", 409)
        unchanged = validate_success(api_client.get_deduction_dispute(dispute_id, ALPHA))
        assert unchanged["status"] == "RESUBMITTED"
        assert unchanged["round_no"] == 3

    def test_the_exhausted_cycle_is_closed_by_adjudication_and_the_money_never_moved(self):
        """Rejecting the dispute returns the event to ISSUED with its allocation intact.

        PRD: "Rejecting the dispute is deliberately inert by comparison. The
        dispute lands in `REJECTED` and the deduction event returns `DISPUTED →
        ISSUED`."

        Design: Difficulty/non_linear_state_machine/dispute_referral_cycle_is_bounded_at_three_submissions
        """
        ctx = setup_disputed_deduction()
        dispute_id = ctx["dispute"]["id"]
        event_id = ctx["deduction_events"][0]["id"]
        period_before = refresh_service_period(ctx)
        assert period_before["total_deduction_cents"] == 500000
        assert period_before["net_payment_cents"] == 8104167

        response = api_client.adjudicate_deduction_dispute(
            dispute_id,
            adjudicate_dispute_payload("REJECT", "deduction stands on the signed extract"),
            BETA,
        )

        dispute = validate_success(response)
        assert dispute["status"] == "REJECTED"
        event = validate_success(api_client.get_deduction_event(event_id, ALPHA))
        assert event["status"] == "ISSUED"
        assert event["allowed_amount_cents"] == 500000
        period_after = refresh_service_period(ctx)
        assert period_after["total_deduction_cents"] == 500000
        assert period_after["net_payment_cents"] == 8104167


class TestStepInCycleIsReEnterable:
    def test_a_notified_step_in_moves_three_rows_in_one_request(self):
        """The step-in arm never pauses in NOTIFIED and drags concession and sponsor.

        PRD: "A step-in requires the concession to be in `OPERATIONS`, and it does
        not pause in `NOTIFIED`: the system auto-advances it to `STEP_IN_ACTIVE`
        before responding, sets its `cure_deadline` to the `effective_date` plus 90
        calendar days, moves the concession `OPERATIONS → STEP_IN`, and moves the
        sponsor vehicle `ACTIVE → STEPPED_IN`."

        Design: Difficulty/non_linear_state_machine/concession_step_in_cycle_returns_to_operations_and_can_be_re_entered
        """
        ctx = setup_period_with_breaching_deduction()
        assert ctx["concession"]["persistent_breach_flag"] is True

        response = api_client.create_enforcement_action(
            ctx["concession_id"],
            create_enforcement_action_payload("STEP_IN", "PERSISTENT_BREACH", "2027-04-02"),
            LENDER,
        )

        action = validate_success(response, 201)
        assert action["status"] == "STEP_IN_ACTIVE"
        assert action["cure_deadline"] == "2027-07-01"
        assert refresh_concession(ctx)["status"] == "STEP_IN"
        sponsor = validate_success(
            api_client.get_concessionaire(ctx["concessionaire_id"], ALPHA)
        )
        assert sponsor["status"] == "STEPPED_IN"

    def test_a_cured_step_in_can_be_re_entered_by_a_second_notification(self):
        """Cure returns the cycle to OPERATIONS, and the same ground may fire again.

        PRD: "The freeze lifts the moment the action reaches one of its terminal
        states, so a cured step-in restores normal commercial operation completely."

        Design: Difficulty/non_linear_state_machine/concession_step_in_cycle_returns_to_operations_and_can_be_re_entered
        """
        ctx = setup_period_with_breaching_deduction()
        first = raise_enforcement_action(
            ctx, "STEP_IN", "PERSISTENT_BREACH", "2027-04-02", LENDER
        )

        cured = validate_success(
            api_client.cure_enforcement_action(
                first["id"],
                cure_enforcement_action_payload("replacement O&M contractor mobilised"),
                LENDER,
            )
        )
        assert cured["status"] == "CURED"
        assert refresh_concession(ctx)["status"] == "OPERATIONS"
        assert (
            validate_success(
                api_client.get_concessionaire(ctx["concessionaire_id"], ALPHA)
            )["status"]
            == "ACTIVE"
        )

        second = validate_success(
            api_client.create_enforcement_action(
                ctx["concession_id"],
                create_enforcement_action_payload(
                    "STEP_IN", "PERSISTENT_BREACH", "2027-04-02"
                ),
                LENDER,
            ),
            201,
        )
        assert second["status"] == "STEP_IN_ACTIVE"
        assert refresh_concession(ctx)["status"] == "STEP_IN"

        rows, meta = list_enforcement_rows(ctx["concession_id"])
        assert meta["total_count"] == 2
        assert rows[0]["status"] == "CURED"
        assert rows[1]["status"] == "STEP_IN_ACTIVE"
        period = refresh_service_period(ctx)
        assert period["total_deduction_cents"] == 750000
        assert period["net_payment_cents"] == 7854167
