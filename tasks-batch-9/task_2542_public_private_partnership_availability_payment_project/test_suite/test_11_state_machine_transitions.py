"""Declared transitions, terminal states and the side effects a single call must apply."""
from test_helpers import api_client, validate_error, validate_success
from test_helpers.factories import (
    approve_milestone_payload,
    certify_service_commencement_payload,
    create_drawdown_milestone_payload,
    create_enforcement_action_payload,
    financial_close_payload,
    pay_service_period_payload,
    reject_milestone_payload,
    reject_performance_report_payload,
    settle_enforcement_action_payload,
    verify_service_period_payload,
)
from test_helpers.fixtures import (
    ALPHA,
    BETA,
    CERTIFIER,
    EPSILON,
    LENDER,
    approve_milestone,
    calculate_compensation,
    list_deduction_events_for_period,
    list_enforcement_rows,
    list_reserve_rows,
    raise_enforcement_action,
    refresh_concession,
    refresh_service_period,
    reject_milestone,
    request_milestone,
    set_clock,
    setup_active_step_in,
    setup_concession_at_financial_close,
    setup_concession_in_operations,
    setup_drafted_concession,
    setup_invoiced_period,
    setup_paid_period,
    setup_pending_service_period,
    setup_self_reported_period,
)


class TestMilestoneCreationInitialState:
    def test_a_requested_milestone_carries_no_split_and_no_certified_cost(self):
        """The equity-first split is written at approval, so creation leaves it null.

        PRD: "A successful request creates the milestone in `REQUESTED` and assigns
        it a `sequence_no` equal to one more than the highest `sequence_no` any
        milestone of this concession already holds; numbers are never reused, and
        this is the only ordering key for replaying the drawdown waterfall."

        Design: Corner/state_machines/a_new_milestone_starts_in_requested_with_no_split_computed
        """
        ctx = setup_concession_at_financial_close()
        closed_version = ctx["concession"]["version"]

        milestone = validate_success(
            api_client.create_drawdown_milestone(
                ctx["concession_id"],
                create_drawdown_milestone_payload(
                    "M1 Design Complete", 120000000, closed_version
                ),
                ctx["cnr_headers"],
            ),
            201,
        )

        assert milestone["status"] == "REQUESTED"
        assert milestone["sequence_no"] == 1
        assert milestone["requested_amount_cents"] == 120000000
        assert milestone["equity_portion_cents"] is None
        assert milestone["debt_portion_cents"] is None
        assert milestone["approved_at"] is None
        assert milestone["disbursed_at"] is None
        assert milestone["rejection_reason"] is None
        concession = refresh_concession(ctx)
        assert concession["equity_drawn_cents"] == 0
        assert concession["senior_debt_drawn_cents"] == 0
        assert concession["cumulative_drawn_pct"] == 0
        assert concession["status"] == "FINANCIAL_CLOSE"
        assert concession["version"] == closed_version + 1


class TestFinancialCloseTransition:
    def test_closing_stamps_the_supplied_date_and_derives_the_monthly_charge(self):
        """One call advances the state, records the close date and prices the month.

        PRD: "The supplied `close_date` is recorded as `financial_close_date`, and
        closing is the sole producer of `monthly_unitary_charge_cents`."

        Design: Corner/state_machines/financial_close_derives_the_unitary_charge_and_advances_the_concession
        """
        ctx = setup_drafted_concession()

        concession = validate_success(
            api_client.financial_close(
                ctx["concession_id"], financial_close_payload("2026-09-15"), ALPHA
            )
        )

        assert concession["status"] == "FINANCIAL_CLOSE"
        assert concession["financial_close_date"] == "2026-09-15"
        assert concession["monthly_unitary_charge_cents"] == 8604167
        assert concession["version"] == 2
        assert concession["actual_service_commencement"] is None
        assert concession["ld_accrued_cents"] == 0
        sponsor = validate_success(
            api_client.get_concessionaire(ctx["concessionaire_id"], ALPHA)
        )
        assert sponsor["concessions_count"] == 1


class TestMilestoneRejectionIsTerminal:
    def test_a_rejected_milestone_stores_its_reason_and_moves_no_drawn_total(self):
        """Refusal is inert: the reason is kept and not one concession figure moves.

        PRD: "On the refusing branch the certifier supplies a `rejection_reason`,
        the milestone advances `REQUESTED → REJECTED`, `approved_at`,
        `disbursed_at`, `equity_portion_cents` and `debt_portion_cents` are all
        left null, and not one concession figure moves: `senior_debt_drawn_cents`,
        `equity_drawn_cents` and `cumulative_drawn_pct` are untouched."

        Design: Corner/state_machines/milestone_rejection_is_terminal_and_moves_no_drawn_total
        """
        ctx = setup_concession_at_financial_close()
        milestone = request_milestone(ctx, "M1 Design Complete", 120000000)

        rejected = validate_success(
            api_client.reject_drawdown_milestone(
                milestone["id"],
                reject_milestone_payload(
                    "certifier could not substantiate 120000000 of cost"
                ),
                CERTIFIER,
            )
        )

        assert rejected["status"] == "REJECTED"
        assert (
            rejected["rejection_reason"]
            == "certifier could not substantiate 120000000 of cost"
        )
        assert rejected["approved_at"] is None
        assert rejected["disbursed_at"] is None
        concession = refresh_concession(ctx)
        assert concession["equity_drawn_cents"] == 0
        assert concession["senior_debt_drawn_cents"] == 0
        assert concession["cumulative_drawn_pct"] == 0
        assert concession["status"] == "FINANCIAL_CLOSE"
        _, reserve_meta = list_reserve_rows(ctx["concession_id"])
        assert reserve_meta["total_count"] == 0


class TestDisburseFromRequestedIsRefused:
    def test_disbursement_requires_the_milestone_to_have_been_approved_first(self):
        """The lender is the right role, so nothing masks the state check.

        PRD: "It requires the milestone to be in `APPROVED` and the concession to
        be in `FINANCIAL_CLOSE` or `CONSTRUCTION`, and it is frozen by a live
        enforcement action exactly as milestone creation is, with the same
        `ERR_CONCESSION_UNDER_ENFORCEMENT` (HTTP 409)."

        Design: Corner/state_machines/disbursing_a_requested_milestone_is_an_invalid_state_transition
        """
        ctx = setup_concession_at_financial_close()
        milestone = request_milestone(ctx, "M1 Design Complete", 120000000)

        response = api_client.disburse_drawdown_milestone(milestone["id"], LENDER)

        validate_error(response, "ERR_INVALID_STATE_TRANSITION", 409)
        unchanged = validate_success(
            api_client.get_drawdown_milestone(milestone["id"], ALPHA)
        )
        assert unchanged["status"] == "REQUESTED"
        assert unchanged["disbursed_at"] is None
        concession = refresh_concession(ctx)
        assert concession["equity_drawn_cents"] == 0
        assert concession["senior_debt_drawn_cents"] == 0
        assert concession["status"] == "FINANCIAL_CLOSE"


class TestVerifyWithoutASelfReportIsRefused:
    def test_the_authority_cannot_verify_counts_nobody_reported(self):
        """A PENDING period has no incumbent return, so verification is refused.

        PRD: "The period's reporting axis must be in `SELF_REPORTED`, the
        concession must be in `OPERATIONS`, and exactly one report of the period
        must hold `SUBMITTED` — zero such reports, or more than one, is
        `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."

        Design: Corner/state_machines/verifying_a_period_that_was_never_self_reported_is_an_invalid_state_transition
        """
        ctx = setup_pending_service_period()

        response = api_client.verify_service_period(
            ctx["service_period_id"], verify_service_period_payload(100, 2, 4), BETA
        )

        validate_error(response, "ERR_INVALID_STATE_TRANSITION", 409)
        period = refresh_service_period(ctx)
        assert period["reporting_status"] == "PENDING"
        assert period["verified_at"] is None
        assert period["unavailable_minutes_verified"] is None
        assert period["availability_ratio"] is None
        assert period["version"] == 1
        # A period with neither deductions nor relief credit is still carrying its
        # frozen gross charge, which the refused write left exactly as it was.
        assert period["net_payment_cents"] == 8604167
        _, event_meta = list_deduction_events_for_period(ctx["service_period_id"])
        assert event_meta["total_count"] == 0


class TestApprovingARejectedMilestoneIsLockedOut:
    def test_a_terminal_rejection_cannot_be_reopened_by_the_right_role(self):
        """The certifier is correct and the cost fundable, but REJECTED is terminal.

        PRD: "Both branches require the milestone to be in `REQUESTED`, and
        approval additionally requires the concession to be in `FINANCIAL_CLOSE` or
        `CONSTRUCTION`."

        Design: Corner/state_machines/approving_an_already_rejected_milestone_is_locked_out
        """
        ctx = setup_concession_at_financial_close()
        milestone = request_milestone(ctx, "M1 Design Complete", 120000000)
        reject_milestone(ctx, milestone["id"], "cost evidence incomplete")

        response = api_client.approve_drawdown_milestone(
            milestone["id"], approve_milestone_payload(120000000), CERTIFIER
        )

        validate_error(response, "ERR_INVALID_STATE_TRANSITION", 409)
        unchanged = validate_success(
            api_client.get_drawdown_milestone(milestone["id"], ALPHA)
        )
        assert unchanged["status"] == "REJECTED"
        assert unchanged["rejection_reason"] == "cost evidence incomplete"
        assert unchanged["approved_at"] is None
        concession = refresh_concession(ctx)
        assert concession["equity_drawn_cents"] == 0
        assert concession["senior_debt_drawn_cents"] == 0


class TestSecondFinancialCloseIsRefused:
    def test_replaying_the_close_with_a_later_date_cannot_restamp_the_charge(self):
        """The frozen charge would otherwise be silently re-derived and rewritten.

        PRD: "It requires the concession to be in `DRAFTED` — any other state is
        `ERR_INVALID_STATE_TRANSITION` (HTTP 409) — and re-affirms that committed
        senior debt plus committed equity is at least the certified total project
        cost, refusing with `ERR_COMMITMENT_EXCEEDED` (HTTP 422) if that is not so."

        Design: Corner/state_machines/a_second_financial_close_on_the_same_concession_is_rejected
        """
        ctx = setup_concession_at_financial_close("2026-09-15")

        response = api_client.financial_close(
            ctx["concession_id"], financial_close_payload("2026-10-01"), ALPHA
        )

        validate_error(response, "ERR_INVALID_STATE_TRANSITION", 409)
        concession = refresh_concession(ctx)
        assert concession["financial_close_date"] == "2026-09-15"
        assert concession["status"] == "FINANCIAL_CLOSE"
        assert concession["monthly_unitary_charge_cents"] == 8604167
        assert concession["version"] == 2


class TestSecondPaymentOnAPaidPeriodIsRefused:
    def test_the_first_payment_reference_survives_a_second_pay_attempt(self):
        """PAID is not a payable state, so the second reference is never written.

        PRD: "Payment likewise requires the concession to be in `OPERATIONS`, and
        the period must be in `INVOICED`."

        Design: Corner/state_machines/a_second_payment_on_an_already_paid_period_is_rejected
        """
        ctx = setup_paid_period(payment_reference="PAY-2027-04-001")

        response = api_client.pay_service_period(
            ctx["service_period_id"], pay_service_period_payload("PAY-2027-04-002"), ALPHA
        )

        validate_error(response, "ERR_INVALID_STATE_TRANSITION", 409)
        period = refresh_service_period(ctx)
        assert period["payment_status"] == "PAID"
        assert period["payment_reference"] == "PAY-2027-04-001"
        assert period["paid_at"].startswith("2027-04-02T00:00:00")
        assert period["net_payment_cents"] == 8604167
        assert period["reporting_status"] == "VERIFIED"


class TestCertifyingCommencementBeforeConstruction:
    def test_an_approved_but_undisbursed_milestone_leaves_the_project_uncertifiable(self):
        """CONSTRUCTION is reached by disbursement alone, so certification is blocked.

        PRD: "The concession must be in `CONSTRUCTION`, and any other state yields
        `ERR_CONCESSION_STATE_FORBIDS_OPERATION` (HTTP 409)."

        Design: Corner/state_machines/certifying_service_commencement_before_construction_is_blocked
        """
        ctx = setup_concession_at_financial_close()
        milestone = request_milestone(ctx, "M1 Design Complete", 120000000)
        approve_milestone(ctx, milestone["id"], 120000000)
        set_clock("2027-01-21T00:00:00Z")

        response = api_client.certify_service_commencement(
            ctx["concession_id"],
            certify_service_commencement_payload("2027-01-21"),
            CERTIFIER,
        )

        validate_error(response, "ERR_CONCESSION_STATE_FORBIDS_OPERATION", 409)
        concession = refresh_concession(ctx)
        assert concession["status"] == "FINANCIAL_CLOSE"
        assert concession["actual_service_commencement"] is None
        assert concession["ld_accrued_cents"] == 0
        assert concession["equity_drawn_cents"] == 0
        assert concession["cumulative_drawn_pct"] == 0
        approved = validate_success(
            api_client.get_drawdown_milestone(milestone["id"], ALPHA)
        )
        assert approved["status"] == "APPROVED"
        assert approved["equity_portion_cents"] == 100000000
        assert approved["debt_portion_cents"] == 20000000


class TestRejectingTheOnlySubmittedReport:
    def test_the_reporting_axis_reverts_to_pending_and_the_period_version_advances(self):
        """Nothing is left in SUBMITTED, so the axis reopens for a fresh return.

        PRD: "What happens to the period afterwards depends on what is left: the
        axis reverts `SELF_REPORTED → PENDING` only when no other report of that
        period is still `SUBMITTED`, and otherwise the axis stays `SELF_REPORTED`."

        Design: Corner/state_machines/rejecting_the_only_submitted_report_reopens_the_reporting_axis
        """
        ctx = setup_self_reported_period()
        report_id = ctx["performance_report"]["id"]

        rejected = validate_success(
            api_client.reject_performance_report(
                report_id,
                reject_performance_report_payload(
                    "outage log does not support 100 unavailable minutes"
                ),
                BETA,
            )
        )

        assert rejected["status"] == "REJECTED"
        assert (
            rejected["rejection_reason"]
            == "outage log does not support 100 unavailable minutes"
        )
        assert rejected["reported_points"] == 320
        assert rejected["variance_pct"] is None
        period = refresh_service_period(ctx)
        assert period["reporting_status"] == "PENDING"
        assert period["version"] == 3
        assert period["payment_status"] == "UNBILLED"
        body = api_client.list_performance_reports(
            ALPHA,
            params={"service_period_id": ctx["service_period_id"], "status": "SUBMITTED"},
        ).json()
        assert body["meta"]["total_count"] == 0


class TestStepInNotificationWritesThreeRows:
    def test_one_notification_advances_the_action_the_concession_and_the_sponsor(self):
        """A step-in does not pause in NOTIFIED: it bites inside the same request.

        PRD: "A step-in requires the concession to be in `OPERATIONS`, and it does
        not pause in `NOTIFIED`: the system auto-advances it to `STEP_IN_ACTIVE`
        before responding, sets its `cure_deadline` to the `effective_date` plus 90
        calendar days, moves the concession `OPERATIONS → STEP_IN`, and moves the
        sponsor vehicle `ACTIVE → STEPPED_IN`."

        Design: Corner/state_machines/notifying_a_step_in_moves_the_concession_and_the_concessionaire_in_one_request
        """
        ctx = setup_concession_in_operations()
        set_clock("2027-04-02T00:00:00Z")

        action = validate_success(
            api_client.create_enforcement_action(
                ctx["concession_id"],
                create_enforcement_action_payload(
                    "STEP_IN", "LENDER_DEFAULT_CURE", "2027-04-02"
                ),
                LENDER,
            ),
            201,
        )

        assert action["status"] == "STEP_IN_ACTIVE"
        assert action["action_type"] == "STEP_IN"
        assert action["trigger_reason"] == "LENDER_DEFAULT_CURE"
        assert action["initiated_by_role"] == "LenderAgent"
        assert action["cure_deadline"] == "2027-07-01"
        assert action["compensation_cents"] is None
        assert action["calculated_by_user_id"] is None
        assert refresh_concession(ctx)["status"] == "STEP_IN"
        sponsor = validate_success(
            api_client.get_concessionaire(ctx["concessionaire_id"], ALPHA)
        )
        assert sponsor["status"] == "STEPPED_IN"


class TestSettlementTerminatesAndWindsUp:
    def test_settling_the_valuation_sweeps_the_concession_the_invoice_and_the_sponsor(self):
        """Three links fire in one call, and the invoiced period is restated not paid.

        PRD: "It then moves `COMPENSATION_CALCULATED → SETTLED` and fires the widest
        cascade in the system, in three links: the concession moves from
        `OPERATIONS` or `STEP_IN` to `TERMINATED`; **every** service period of that
        concession whose payment axis sits at `INVOICED` moves `INVOICED →
        ADJUSTED`, with its `net_payment_cents` frozen at whatever it then held,
        because those invoices will now be dealt with inside the compensation sum
        rather than paid in the ordinary course; and the sponsor vehicle moves to
        `WOUND_UP`."

        Design: Corner/state_machines/settling_the_compensation_terminates_the_concession_and_winds_up_the_concessionaire
        """
        ctx = setup_invoiced_period()
        action = raise_enforcement_action(
            ctx, "TERMINATION", "AUTHORITY_VOLUNTARY", "2027-04-05", ALPHA
        )
        set_clock("2028-01-21T00:00:00Z")
        calculate_compensation(ctx, action["id"], "2028-01-21", 180000000, ALPHA)

        settled = validate_success(
            api_client.settle_enforcement_action(
                action["id"],
                settle_enforcement_action_payload("SETTLE-2028-01-21-A47"),
                EPSILON,
            )
        )

        assert settled["status"] == "SETTLED"
        assert settled["settlement_reference"] == "SETTLE-2028-01-21-A47"
        assert settled["settled_at"].startswith("2028-01-21T00:00:00")
        assert settled["elapsed_operational_months"] == 12
        assert settled["accrued_equity_return_cents"] == 12000000
        assert settled["unpaid_invoiced_cents"] == 8604167
        assert settled["deduction_offset_cents"] == 0
        assert settled["compensation_cents"] == 300604167
        assert refresh_concession(ctx)["status"] == "TERMINATED"
        period = refresh_service_period(ctx)
        assert period["payment_status"] == "ADJUSTED"
        assert period["paid_at"] is None
        assert period["payment_reference"] is None
        assert period["net_payment_cents"] == 8604167
        sponsor = validate_success(
            api_client.get_concessionaire(ctx["concessionaire_id"], ALPHA)
        )
        assert sponsor["status"] == "WOUND_UP"


class TestEscalationLapsesAndMintsATermination:
    def test_the_lapsed_step_in_links_to_a_system_appended_termination_row(self):
        """The second arm of the fork appends a row reachable only through the list.

        PRD: "The lapsed action moves `STEP_IN_ACTIVE → LAPSED`, and the system
        appends a **second, brand-new enforcement action** against the same
        concession: `action_type` `TERMINATION`, `trigger_reason`
        `CONCESSIONAIRE_DEFAULT`, `effective_date` equal to the current logical
        clock, `status` `NOTIFIED` and `initiated_by_role` the literal `SYSTEM`."

        Design: Corner/state_machines/escalating_after_the_cure_window_lapses_the_step_in_and_links_a_termination_action
        """
        ctx = setup_active_step_in(
            trigger_reason="LENDER_DEFAULT_CURE", effective_date="2027-04-02"
        )
        step_in_id = ctx["enforcement_action"]["id"]
        set_clock("2027-07-02T00:00:00Z")

        lapsed = validate_success(
            api_client.escalate_enforcement_action(step_in_id, LENDER)
        )

        assert lapsed["status"] == "LAPSED"
        assert lapsed["cured_at"] is None
        successor_id = lapsed["escalated_to_action_id"]
        assert successor_id is not None
        assert successor_id != step_in_id
        _, all_meta = list_enforcement_rows(ctx["concession_id"])
        assert all_meta["total_count"] == 2
        notified, notified_meta = list_enforcement_rows(
            ctx["concession_id"], status="NOTIFIED"
        )
        assert notified_meta["total_count"] == 1
        successor = notified[0]
        assert successor["id"] == successor_id
        assert successor["action_type"] == "TERMINATION"
        assert successor["trigger_reason"] == "CONCESSIONAIRE_DEFAULT"
        assert successor["initiated_by_role"] == "SYSTEM"
        assert successor["effective_date"] == "2027-07-02"
        assert successor["cure_deadline"] is None
        assert successor["compensation_cents"] is None
        linked, linked_meta = list_enforcement_rows(
            ctx["concession_id"], escalated_to_action_id=successor_id
        )
        assert linked_meta["total_count"] == 1
        assert linked[0]["id"] == step_in_id
        assert refresh_concession(ctx)["status"] == "STEP_IN"
        sponsor = validate_success(
            api_client.get_concessionaire(ctx["concessionaire_id"], ALPHA)
        )
        assert sponsor["status"] == "STEPPED_IN"
