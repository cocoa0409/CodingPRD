"""Guard rules at their boundaries, and the ladder order when two of them fire at once."""
from test_helpers import (
    NON_EXISTENT_UUID,
    api_client,
    make_concessionaire_headers,
    validate_error,
    validate_success,
)
from test_helpers.factories import (
    approve_milestone_payload,
    create_deduction_event_payload,
    create_reserve_transaction_payload,
    create_service_period_payload,
    determine_relief_claim_payload,
)
from test_helpers.fixtures import (
    ALPHA,
    CERTIFIER,
    GAMMA,
    LENDER,
    add_relief_claim,
    add_reserve_transaction,
    add_service_period,
    approve_milestone,
    create_concessionaire,
    determine_relief_claim,
    disburse_milestone,
    list_deduction_events_for_period,
    list_enforcement_rows,
    list_reserve_rows,
    refresh_concession,
    refresh_service_period,
    request_milestone,
    run_handback_survey,
    set_clock,
    setup_active_step_in,
    setup_concession_at_financial_close,
    setup_concession_in_construction,
    setup_concession_in_operations,
    setup_pending_service_period,
    setup_verified_period,
    submit_performance_report,
    verify_period,
)


class TestReserveFloorIsCheckedOnTheProjectedBalance:
    def test_one_cent_past_the_seeded_balance_appends_no_ledger_row(self):
        """A withdrawal of 8000001 against a balance of 8000000 is refused outright.

        PRD: "A `WITHDRAWAL` may not drive `lifecycle_reserve_balance_cents` below
        zero, and no `WITHDRAWAL` at all is permitted once the concession's
        `handback_status` has left `NOT_SURVEYED` — that is, once the handback
        survey has been recorded, whether it certified or failed."

        Design: Corner/validations/a_withdrawal_one_cent_past_the_balance_is_forbidden
        """
        ctx = setup_concession_in_construction()

        response = api_client.create_reserve_transaction(
            ctx["concession_id"],
            create_reserve_transaction_payload(
                "WITHDRAWAL", 8000001, "bearing replacement programme"
            ),
            ctx["cnr_headers"],
        )

        validate_error(response, "ERR_RESERVE_WITHDRAWAL_FORBIDDEN", 409)
        concession = refresh_concession(ctx)
        assert concession["lifecycle_reserve_balance_cents"] == 8000000
        assert concession["handback_status"] == "NOT_SURVEYED"
        rows, meta = list_reserve_rows(ctx["concession_id"])
        assert meta["total_count"] == 1
        assert rows[0]["txn_type"] == "CONTRIBUTION"
        assert rows[0]["sequence_no"] == 1
        assert rows[0]["signed_amount_cents"] == 8000000
        assert rows[0]["resulting_balance_cents"] == 8000000


class TestReserveFloorAdmitsAnExactlyEmptyingWithdrawal:
    def test_a_withdrawal_down_to_zero_is_appended_with_a_negative_signed_amount(self):
        """The floor is zero and the projected balance may land exactly on it.

        PRD: "From the type and the magnitude comes the entry's
        `signed_amount_cents`: positive for a `CONTRIBUTION` and for a
        `HANDBACK_TOPUP`, negative for a `WITHDRAWAL`, and for a `REVERSAL` the
        exact arithmetic negation of the signed amount of the entry it reverses."

        Design: Corner/validations/a_withdrawal_that_exactly_empties_the_reserve_is_allowed
        """
        ctx = setup_concession_in_construction()

        row = validate_success(
            api_client.create_reserve_transaction(
                ctx["concession_id"],
                create_reserve_transaction_payload(
                    "WITHDRAWAL", 8000000, "bearing replacement programme"
                ),
                ctx["cnr_headers"],
            ),
            201,
        )

        assert row["txn_type"] == "WITHDRAWAL"
        assert row["amount_cents"] == 8000000
        assert row["signed_amount_cents"] == -8000000
        assert row["resulting_balance_cents"] == 0
        assert row["sequence_no"] == 2
        assert row["created_by_role"] == "Concessionaire"
        assert row["reverses_txn_id"] is None
        concession = refresh_concession(ctx)
        assert concession["lifecycle_reserve_balance_cents"] == 0
        assert concession["lifecycle_reserve_target_cents"] == 20000000


class TestGrantMayNotExceedTheClaim:
    def test_five_granted_days_against_a_four_day_claim_writes_nothing(self):
        """The ceiling is tested figure by figure, so the lawful cost grant cannot save it.

        PRD: "The ceiling is that a determination may never grant more than was
        claimed: `granted_relief_days` may not exceed `claimed_relief_days` and
        `granted_cost_cents` may not exceed `claimed_cost_cents`, and a breach of
        either is `ERR_GRANT_EXCEEDS_CLAIM` (HTTP 422)."

        Design: Corner/validations/a_determination_may_not_grant_more_days_than_were_claimed
        """
        ctx = setup_concession_at_financial_close()
        set_clock("2026-10-01T00:00:00Z")
        claim = add_relief_claim(
            ctx, "COMPENSATION_EVENT", "2026-10-01", "2026-10-04", 4, 0
        )

        response = api_client.determine_relief_claim(
            claim["id"],
            determine_relief_claim_payload(
                "GRANT",
                granted_relief_days=5,
                granted_cost_cents=0,
                determination_note="rounded up to a full working week",
            ),
            ALPHA,
        )

        validate_error(response, "ERR_GRANT_EXCEEDS_CLAIM", 422)
        unchanged = validate_success(api_client.get_relief_claim(claim["id"], ALPHA))
        assert unchanged["status"] == "NOTIFIED"
        assert unchanged["granted_relief_days"] == 0
        assert unchanged["granted_cost_cents"] == 0
        assert unchanged["determined_at"] is None
        assert unchanged["determination_note"] is None
        assert unchanged["claimed_relief_days"] == 4


class TestReliefDayAnnualBudget:
    def test_the_sixty_first_day_of_the_year_is_refused_across_claim_types(self):
        """A 60-day relief grant consumes the budget a one-day compensation grant needs.

        PRD: "The budget is the sum of `granted_relief_days` over this concession's
        claims already in `GRANTED` or `PARTIALLY_GRANTED`, plus the days being
        granted now, and it may not exceed sixty days in the year; exceeding it is
        `ERR_RELIEF_DAYS_CAP_EXCEEDED` (HTTP 422)."

        Design: Corner/validations/the_sixty_first_relief_day_of_the_year_is_refused
        """
        ctx = setup_concession_at_financial_close()
        set_clock("2026-09-01T00:00:00Z")
        big = add_relief_claim(ctx, "RELIEF_EVENT", "2026-09-01", "2026-10-30", 60, 0)
        big_granted = determine_relief_claim(
            ctx, big["id"], "GRANT", ALPHA, granted_relief_days=60, granted_cost_cents=0
        )
        set_clock("2026-11-05T00:00:00Z")
        single = add_relief_claim(
            ctx, "COMPENSATION_EVENT", "2026-11-05", "2026-11-05", 1, 0
        )

        response = api_client.determine_relief_claim(
            single["id"],
            determine_relief_claim_payload(
                "GRANT",
                granted_relief_days=1,
                granted_cost_cents=0,
                determination_note="single-day authority instruction",
            ),
            ALPHA,
        )

        validate_error(response, "ERR_RELIEF_DAYS_CAP_EXCEEDED", 422)
        assert big_granted["status"] == "GRANTED"
        assert big_granted["granted_relief_days"] == 60
        refused = validate_success(api_client.get_relief_claim(single["id"], ALPHA))
        assert refused["status"] == "NOTIFIED"
        assert refused["granted_relief_days"] == 0
        untouched = validate_success(api_client.get_relief_claim(big["id"], ALPHA))
        assert untouched["granted_relief_days"] == 60
        body = api_client.list_relief_claims(
            ALPHA, params={"concession_id": ctx["concession_id"], "status": "GRANTED"}
        ).json()
        assert body["meta"]["total_count"] == 1


class TestTheHandbackSurveyLocksTheReserve:
    def test_a_certifying_survey_still_closes_the_withdrawal_door(self):
        """Withdrawals worked before the survey and are refused after it, certified or not.

        PRD: "A `WITHDRAWAL` may not drive `lifecycle_reserve_balance_cents` below
        zero, and no `WITHDRAWAL` at all is permitted once the concession's
        `handback_status` has left `NOT_SURVEYED` — that is, once the handback
        survey has been recorded, whether it certified or failed."

        Design: Corner/validations/the_reserve_locks_once_the_handback_survey_certifies
        """
        ctx = setup_concession_in_operations()
        set_clock("2027-04-02T00:00:00Z")
        before = add_reserve_transaction(
            ctx, "WITHDRAWAL", 1000000, "planned lift refurbishment"
        )
        add_reserve_transaction(ctx, "CONTRIBUTION", 1000000, "quarterly sinking payment")
        surveyed = run_handback_survey(ctx, "2027-04-02", 8000000, CERTIFIER)

        response = api_client.create_reserve_transaction(
            ctx["concession_id"],
            create_reserve_transaction_payload(
                "WITHDRAWAL", 1000000, "planned lift refurbishment second stage"
            ),
            ctx["cnr_headers"],
        )

        validate_error(response, "ERR_RESERVE_WITHDRAWAL_FORBIDDEN", 409)
        assert before["resulting_balance_cents"] == 7000000
        assert surveyed["handback_status"] == "CERTIFIED"
        assert surveyed["handback_required_reserve_cents"] == 8000000
        assert surveyed["handback_shortfall_cents"] == 0
        assert surveyed["handback_rectification_cost_cents"] == 8000000
        assert surveyed["lifecycle_reserve_balance_cents"] == 8000000
        rows, meta = list_reserve_rows(ctx["concession_id"])
        assert meta["total_count"] == 3
        assert [row["sequence_no"] for row in rows] == [1, 2, 3]
        assert rows[-1]["resulting_balance_cents"] == 8000000
        shortfall = api_client.list_deduction_events(
            ALPHA, params={"deduction_type": "HANDBACK_SHORTFALL"}
        ).json()
        assert shortfall["meta"]["total_count"] == 0


class TestRoleGateOutranksStateGate:
    def test_an_officer_disbursing_a_requested_milestone_is_a_role_refusal(self):
        """Disbursement is a lender lever and the milestone is not APPROVED either.

        PRD: "Where several rules could refuse the same request, they are evaluated
        in a fixed order and the first violation found is the one reported."

        PRD: "The authorized-role column is exhaustive: a caller presenting any
        other role in `X-User-Role` receives `ERR_ROLE_NOT_PERMITTED` (HTTP 403),
        and where the role is `Concessionaire` the ownership check of §2.1 applies
        on top of it."

        Design: Corner/validations/the_role_gate_answers_before_the_state_gate_on_disburse
        """
        ctx = setup_concession_at_financial_close()
        milestone = request_milestone(ctx, "M-A Earthworks", 40000000)

        response = api_client.disburse_drawdown_milestone(milestone["id"], ALPHA)

        validate_error(response, "ERR_ROLE_NOT_PERMITTED", 403)
        unchanged = validate_success(
            api_client.get_drawdown_milestone(milestone["id"], ALPHA)
        )
        assert unchanged["status"] == "REQUESTED"
        assert unchanged["disbursed_at"] is None
        assert refresh_concession(ctx)["senior_debt_drawn_cents"] == 0


class TestUnknownPathIdOutranksBodySchema:
    def test_an_inverted_interval_on_a_missing_concession_reports_the_missing_row(self):
        """The path id resolves to nothing, so the reversed dates are never examined.

        PRD: "Path existence is validated left to right, and each resource type has
        its own error: a missing concessionaire yields `ERR_CONCESSIONAIRE_NOT_FOUND`,
        a missing concession `ERR_CONCESSION_NOT_FOUND`, a missing service period
        `ERR_SERVICE_PERIOD_NOT_FOUND`, a missing drawdown milestone
        `ERR_DRAWDOWN_MILESTONE_NOT_FOUND`, a missing performance report
        `ERR_PERFORMANCE_REPORT_NOT_FOUND`, a missing deduction event
        `ERR_DEDUCTION_EVENT_NOT_FOUND`, a missing dispute
        `ERR_DEDUCTION_DISPUTE_NOT_FOUND`, a missing relief claim
        `ERR_RELIEF_CLAIM_NOT_FOUND`, a missing reserve transaction
        `ERR_RESERVE_TRANSACTION_NOT_FOUND`, a missing refinancing event
        `ERR_REFINANCING_EVENT_NOT_FOUND` and a missing enforcement action
        `ERR_ENFORCEMENT_ACTION_NOT_FOUND` — all HTTP 404."

        Design: Corner/validations/an_unknown_concession_answers_before_the_body_is_ever_parsed
        """
        response = api_client.create_service_period(
            NON_EXISTENT_UUID,
            create_service_period_payload(1, "2027-04-01", "2027-03-01"),
            ALPHA,
        )

        validate_error(response, "ERR_CONCESSION_NOT_FOUND", 404)
        body = api_client.list_service_periods(ALPHA).json()
        assert body["meta"]["total_count"] == 0


class TestOwnershipGateOutranksPeriodState:
    def test_a_stranger_sponsor_invoicing_an_unbilled_period_is_an_ownership_refusal(self):
        """The period is not verified either, but ownership is the earlier rung.

        PRD: "A `Concessionaire` acting on a resource whose owning concession names a
        different `concessionaire_id` is rejected with `ERR_NOT_CONCESSION_PARTY`
        (HTTP 403)."

        Design: Corner/validations/a_stranger_concessionaire_is_refused_before_the_period_state_is_consulted
        """
        ctx = setup_pending_service_period()
        stranger = create_concessionaire(legal_name="Northbank Rival Holdings SPV")
        stranger_headers = make_concessionaire_headers(stranger["id"])

        response = api_client.invoice_service_period(
            ctx["service_period_id"], stranger_headers
        )

        validate_error(response, "ERR_NOT_CONCESSION_PARTY", 403)
        period = refresh_service_period(ctx)
        assert period["payment_status"] == "UNBILLED"
        assert period["reporting_status"] == "PENDING"
        assert period["invoiced_at"] is None
        other = validate_success(api_client.get_concessionaire(stranger["id"], ALPHA))
        assert other["concessions_count"] == 0


class TestEscalationOnTheDeadlineInstant:
    def test_the_deadline_instant_itself_still_belongs_to_the_cure(self):
        """A step-in effective 2027-04-02 may not be escalated at 2027-07-01 exactly.

        PRD: "The two predicates partition the timeline with neither gap nor
        overlap: at the exact deadline instant the cure is permitted and the
        escalation is not, and one second later the reverse holds."

        Design: Corner/validations/escalation_exactly_on_the_cure_deadline_is_still_premature
        """
        ctx = setup_active_step_in(
            trigger_reason="LENDER_DEFAULT_CURE", effective_date="2027-04-02"
        )
        action_id = ctx["enforcement_action"]["id"]
        assert ctx["enforcement_action"]["cure_deadline"] == "2027-07-01"
        set_clock("2027-07-01T00:00:00Z")

        response = api_client.escalate_enforcement_action(action_id, LENDER)

        validate_error(response, "ERR_CURE_WINDOW_VIOLATION", 409)
        action = validate_success(api_client.get_enforcement_action(action_id, ALPHA))
        assert action["status"] == "STEP_IN_ACTIVE"
        assert action["escalated_to_action_id"] is None
        assert refresh_concession(ctx)["status"] == "STEP_IN"
        _, meta = list_enforcement_rows(ctx["concession_id"])
        assert meta["total_count"] == 1


class TestFundingCeilingIsTestedOnTheProjectedTotals:
    def test_a_one_cent_second_milestone_breaches_a_fully_drawn_facility(self):
        """Both milestones are lawful in isolation; the second exhausts the debt facility.

        PRD: "Approval also tests the debt side against what is left of the senior
        facility: if the computed debt leg exceeds committed senior debt less senior
        debt already drawn — or if the split would push either drawn total past its
        commitment — the approval is refused with `ERR_COMMITMENT_EXCEEDED` (HTTP
        422)."

        Design: Corner/validations/individually_lawful_milestones_collectively_breach_the_debt_commitment
        """
        ctx = setup_concession_at_financial_close()
        first = request_milestone(ctx, "M-A Whole Works", 400000000)
        approved = approve_milestone(ctx, first["id"], 400000000)
        disburse_milestone(ctx, first["id"])
        drawn = refresh_concession(ctx)
        second = request_milestone(ctx, "M-B Snagging", 1)
        version_before = refresh_concession(ctx)["version"]

        response = api_client.approve_drawdown_milestone(
            second["id"], approve_milestone_payload(1), CERTIFIER
        )

        validate_error(response, "ERR_COMMITMENT_EXCEEDED", 422)
        assert approved["equity_portion_cents"] == 100000000
        assert approved["debt_portion_cents"] == 300000000
        assert drawn["equity_drawn_cents"] == 100000000
        assert drawn["senior_debt_drawn_cents"] == 300000000
        assert drawn["cumulative_drawn_pct"] == 1.0
        assert drawn["status"] == "CONSTRUCTION"
        assert drawn["lifecycle_reserve_balance_cents"] == 8000000
        unchanged = validate_success(
            api_client.get_drawdown_milestone(second["id"], ALPHA)
        )
        assert unchanged["status"] == "REQUESTED"
        assert unchanged["equity_portion_cents"] is None
        assert unchanged["debt_portion_cents"] is None
        assert unchanged["approved_at"] is None
        after = refresh_concession(ctx)
        assert after["version"] == version_before
        assert after["senior_debt_drawn_cents"] == 300000000


class TestDeductionEvidenceMustBelongToTheSamePeriod:
    def test_a_report_from_the_previous_period_cannot_evidence_this_one(self):
        """The cited report resolves, but to the wrong period, so nothing is charged.

        PRD: "If a `performance_report_id` is supplied it must resolve to a real
        report — otherwise `ERR_REFERENCED_ENTITY_NOT_FOUND` (HTTP 404) — and that
        report must belong to the very period the deduction is being attached to,
        failing which the response is `ERR_CROSS_ENTITY_MISMATCH` (HTTP 409)."

        Design: Corner/validations/a_deduction_event_cannot_cite_another_periods_report
        """
        ctx = setup_concession_in_operations()
        first = add_service_period(ctx, 1, "2027-03-01", "2027-04-01")
        second = add_service_period(ctx, 2, "2027-04-01", "2027-05-01")
        set_clock("2027-05-02T00:00:00Z")
        reports = {}
        for period in (first, second):
            reports[period["id"]] = submit_performance_report(
                ctx, 0, 0, 0, service_period_id=period["id"]
            )
            verify_period(ctx, 0, 0, 0, service_period_id=period["id"])

        response = api_client.create_deduction_event(
            second["id"],
            create_deduction_event_payload(
                "PERFORMANCE_FAILURE",
                80,
                performance_report_id=reports[first["id"]]["id"],
            ),
            GAMMA,
        )

        validate_error(response, "ERR_CROSS_ENTITY_MISMATCH", 409)
        for period in (first, second):
            fresh = validate_success(api_client.get_service_period(period["id"], ALPHA))
            assert fresh["total_deduction_cents"] == 0
            assert fresh["net_payment_cents"] == 8604167
            assert fresh["deduction_points_total"] == 0
            _, meta = list_deduction_events_for_period(period["id"])
            assert meta["total_count"] == 0
        for report in reports.values():
            fresh_report = validate_success(
                api_client.get_performance_report(report["id"], ALPHA)
            )
            assert fresh_report["status"] == "VERIFIED"
        concession = refresh_concession(ctx)
        assert concession["deduction_points_ytd"] == 0
        assert concession["availability_deduction_ytd_cents"] == 0


class TestBodyIdExistenceOutranksOwnershipComparison:
    def test_an_unresolvable_report_id_is_a_referenced_entity_failure(self):
        """There is no row to compare periods against, so the 404 rung answers first.

        PRD: "Identifiers supplied in a request *body* rather than in the path are a
        separate rung: the `concessionaire_id` named when drafting a concession, the
        optional `performance_report_id` named when issuing a deduction event, and
        the reversal target named when reversing a ledger entry all yield
        `ERR_REFERENCED_ENTITY_NOT_FOUND` (HTTP 404) when they resolve to no row."

        Design: Corner/validations/an_unresolvable_report_id_is_answered_before_the_ownership_comparison
        """
        ctx = setup_verified_period()

        response = api_client.create_deduction_event(
            ctx["service_period_id"],
            create_deduction_event_payload(
                "UNAVAILABILITY", 40, performance_report_id=NON_EXISTENT_UUID
            ),
            GAMMA,
        )

        validate_error(response, "ERR_REFERENCED_ENTITY_NOT_FOUND", 404)
        period = refresh_service_period(ctx)
        assert period["total_deduction_cents"] == 0
        assert period["net_payment_cents"] == 8604167
        _, meta = list_deduction_events_for_period(ctx["service_period_id"])
        assert meta["total_count"] == 0
