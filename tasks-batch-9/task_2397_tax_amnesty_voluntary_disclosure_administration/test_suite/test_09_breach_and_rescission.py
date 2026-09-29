"""Breach, its five hops, and the exact compensation that rescission performs.

PRD §3.7 makes breach the deepest cascade in the system and specifies
rescission as its precise inverse, so these tests read every row the cascade
touches and then read them again after the compensation.
"""

from test_helpers import (
    ADMIN_HEADERS,
    AUDITOR_ONE_HEADERS,
    CANONICAL_DOWN_PAYMENT_CENTS,
    CANONICAL_GROSS_INTEREST_CENTS,
    CANONICAL_GROSS_PENALTY_CENTS,
    CANONICAL_SCHEDULED_TOTAL_CENTS,
    CANONICAL_TOTAL_DUE_CENTS,
    CANONICAL_WAIVED_AMOUNT_CENTS,
    CANONICAL_WAIVED_INTEREST_CENTS,
    CANONICAL_WAIVED_PENALTY_CENTS,
    CANONICAL_WATERFALL_PAYMENT_CENTS,
    CANONICAL_WATERFALL_TAIL_CENTS,
    ApiErrorId,
    assert_fields,
    assert_list_total,
    assert_waiver_ledger_identity,
    declare_breach,
    default_plan_payload,
    installments_of,
    read_agreement,
    read_plan,
    read_program,
    read_return,
    read_taxpayer,
    remit_payment,
    rescind_breach_payload,
    returns_of,
    rows_by_seq_index,
    set_clock,
    setup_approved_installment_plan,
    setup_executed_agreement,
    validate_error,
    validate_success,
)

BREACH_TAXPAYER = {"legal_name": "Quarry Bend Materials LLC", "tin_last4": "8802"}
RESCIND_TAXPAYER = {"legal_name": "Cinder Row Foundry Inc", "tin_last4": "6613"}
REINSTATED_AMOUNT_CENTS = 300000
BREACHED_TOTAL_DUE_CENTS = 1350000
PAID_TOTAL_CENTS = 305000


def _breached_agreement(api, taxpayer_overrides):
    """Filed return, approved schedule, one waterfall payment, then breach."""
    ctx = setup_approved_installment_plan(
        api,
        program_overrides={"installment_max_count": 12},
        taxpayer_overrides=taxpayer_overrides,
    )
    remit_payment(
        api, ctx, CANONICAL_WATERFALL_PAYMENT_CENTS, payment_reference="INST-1-3"
    )
    declare_breach(api, ctx, breach_reason="PROSPECTIVE_FILING_MISSED")
    return ctx


class TestBreachCascade:
    """Declaring breach claws the waived money back and escalates."""

    def test_the_money_hops_move_the_waived_column_back_to_payable(self, api):
        """Hop one reinstates the agreement, hop two rewrites its returns.

        PRD §3.7: "The first hop reinstates the money: `reinstated_amount_cents`
        is set to the sum, over the agreement's returns in `FILED`, `ASSESSED` or
        `SETTLED` status, of `waived_penalty_cents` plus `waived_interest_cents`,
        and `waived_amount_cents` is zeroed."

        PRD §3.7: "The second hop, caused by the first, rewrites each of those
        returns: each advances to `REINSTATED` with `payable_penalty_cents` set
        to its `gross_penalty_cents`, `payable_interest_cents` set to its
        `gross_interest_cents`, `waived_penalty_cents` and `waived_interest_cents`
        both zeroed, and `balance_due_cents` recomputed from the reported tax and
        the now-unwaived components; the agreement's `total_due_cents` is
        recomputed from the new figures."

        Design: Difficulty/transitive_cascade/breach_declaration_cascades_five_hops_to_behavior_score
        """
        ctx = _breached_agreement(api, BREACH_TAXPAYER)

        assert_fields(
            read_agreement(api, ctx["agreement"]["id"]),
            status="BREACHED",
            breach_reason="PROSPECTIVE_FILING_MISSED",
            reinstated_amount_cents=REINSTATED_AMOUNT_CENTS,
            waived_amount_cents=0,
            total_due_cents=BREACHED_TOTAL_DUE_CENTS,
            payment_status="DELINQUENT",
            paid_total_cents=PAID_TOTAL_CENTS,
        )
        assert_fields(
            read_return(api, ctx["disclosure_return"]["id"]),
            status="REINSTATED",
            waived_penalty_cents=0,
            waived_interest_cents=0,
            payable_penalty_cents=CANONICAL_GROSS_PENALTY_CENTS,
            payable_interest_cents=CANONICAL_GROSS_INTEREST_CENTS,
            balance_due_cents=BREACHED_TOTAL_DUE_CENTS,
        )

    def test_the_schedule_hop_voids_the_unpaid_installments_only(self, api):
        """Hop three defaults the plan but preserves what was already paid.

        PRD §3.7: "the plan advances `ACTIVE → DEFAULTED` with `default_reason`
        set to the literal string `BREACH_CASCADE`, each of its installments in
        `SCHEDULED` or `LATE` status advances to `VOIDED` with its `paid_cents`
        preserved untouched, and the agreement's `payment_status` becomes
        `DELINQUENT`."

        Design: Difficulty/transitive_cascade/breach_declaration_cascades_five_hops_to_behavior_score
        """
        ctx = _breached_agreement(api, BREACH_TAXPAYER)
        plan_id = ctx["payment_plan"]["id"]

        assert_fields(
            read_plan(api, plan_id),
            status="DEFAULTED",
            default_reason="BREACH_CASCADE",
            scheduled_total_cents=CANONICAL_SCHEDULED_TOTAL_CENTS,
        )
        voided = assert_list_total(
            api.list_plan_installments(
                plan_id, ADMIN_HEADERS, {"status": "VOIDED", "limit": 100}
            ),
            9,
        )
        assert (
            rows_by_seq_index(voided)[3]["paid_cents"] == CANONICAL_WATERFALL_TAIL_CENTS
        )
        assert_list_total(
            api.list_plan_installments(
                plan_id, ADMIN_HEADERS, {"status": "PAID", "limit": 100}
            ),
            2,
        )

    def test_the_escalation_hops_issue_an_assessment_and_dock_the_score(self, api):
        """Hop four issues the system assessment, hop five re-scores the taxpayer.

        PRD §3.7: "an `EnforcementAction` is created directly in `ISSUED` with
        `origin` set to `BREACH_CASCADE`, `action_type` set to `ASSESSMENT`,
        `base_tax_cents` set to the agreement's `reinstated_amount_cents`,
        `issued_by_user_id` set to the literal string `SYSTEM`, and
        `assessed_penalty_cents` computed by the post-program penalty rules of
        §3.9 from a taxpayer snapshot taken **before** the fifth hop runs."

        PRD §3.7: "The fifth hop, caused by the fourth, recomputes the taxpayer's
        `open_enforcement_action_count` and `compliance_behavior_score`, which now
        absorb the issued-action penalty."

        PRD §3.9: "The tier rate is 0.10 for tier `T0`, 0.20 for tier `T1` and
        0.35 for tier `T2`."

        Design: Difficulty/transitive_cascade/breach_declaration_cascades_five_hops_to_behavior_score
        """
        ctx = _breached_agreement(api, BREACH_TAXPAYER)

        actions = assert_list_total(
            api.list_enforcement_actions(
                ADMIN_HEADERS,
                {
                    "agreement_id": ctx["agreement"]["id"],
                    "origin": "BREACH_CASCADE",
                    "limit": 100,
                },
            ),
            1,
        )
        assert_fields(
            actions[0],
            status="ISSUED",
            origin="BREACH_CASCADE",
            action_type="ASSESSMENT",
            base_tax_cents=REINSTATED_AMOUNT_CENTS,
            escalation_tier_applied="T0",
            multiplier_applied=1.00,
            behavior_adjustment_applied=0.00,
            assessed_penalty_cents=30000,
            issued_by_user_id="SYSTEM",
        )
        assert_fields(
            read_taxpayer(api, ctx["taxpayer"]["id"]),
            open_enforcement_action_count=1,
            compliance_behavior_score=92,
        )
        assert_fields(
            read_program(api, ctx["program"]["id"]),
            reinstated_total_cents=REINSTATED_AMOUNT_CENTS,
            waived_total_cents=0,
        )


class TestNothingToReinstate:
    """Breach needs something to claw back before it is admissible."""

    def test_an_agreement_with_no_returns_cannot_be_breached(self, api):
        """No waived money and no qualifying return means no declaration.

        PRD §3.7: "the declaration is only admissible if there is something to
        claw back: either the agreement's `waived_amount_cents` is greater than
        zero, or at least one of its returns is in `FILED`, `ASSESSED` or
        `SETTLED` status. An agreement with nothing to reinstate is refused with
        `ERR_NOTHING_TO_REINSTATE`."

        Design: Corner/Table 6 Errors/declare_breach_is_rejected_when_nothing_was_ever_waived
        """
        ctx = setup_executed_agreement(
            api,
            taxpayer_overrides={
                "legal_name": "Thornfield Mills LLC",
                "tin_last4": "9902",
            },
        )

        validate_error(
            api.declare_breach(
                ctx["agreement"]["id"],
                {"breach_reason": "missed prospective filing"},
                AUDITOR_ONE_HEADERS,
            ),
            ApiErrorId.NOTHING_TO_REINSTATE,
        )

        assert_fields(
            read_agreement(api, ctx["agreement"]["id"]),
            status="EXECUTED",
            breach_reason=None,
            waived_amount_cents=0,
            reinstated_amount_cents=0,
        )
        assert_list_total(
            api.list_enforcement_actions(
                ADMIN_HEADERS,
                {"agreement_id": ctx["agreement"]["id"], "limit": 100},
            ),
            0,
        )
        assert_fields(
            read_taxpayer(api, ctx["taxpayer"]["id"]), compliance_behavior_score=100
        )


class TestIndependentStateAxes:
    """`payment_status` moves without ever disturbing the agreement's `status`."""

    def test_defaulting_the_plan_moves_only_the_payment_axis(self, api):
        """The agreement stays `EXECUTED` while payment turns `DELINQUENT`.

        PRD §3.6: "An auditor may also default an `ACTIVE` plan directly,
        supplying a `default_reason`: that advances the plan `ACTIVE →
        DEFAULTED`, advances each of its installments in `SCHEDULED` or `LATE` to
        `DEFAULTED`, and sets the agreement's `payment_status` to `DELINQUENT`
        while leaving the agreement's own `status` untouched, advancing both the
        plan's and the agreement's `version` by one."

        PRD §3.6: "otherwise `DELINQUENT` when any plan of the agreement has
        `status` `DEFAULTED`"

        Design: Difficulty/non_linear_state_machine/agreement_status_and_payment_status_move_on_independent_axes
        """
        ctx = setup_approved_installment_plan(
            api,
            program_overrides={"installment_max_count": 12},
            taxpayer_overrides={
                "legal_name": "Beckwith Freight LLC",
                "tin_last4": "1188",
            },
            approve_at="2026-10-01T00:00:00Z",
        )
        plan_id = ctx["payment_plan"]["id"]

        defaulted = validate_success(
            api.default_payment_plan(
                plan_id, default_plan_payload(), AUDITOR_ONE_HEADERS
            )
        )
        assert_fields(
            defaulted,
            status="DEFAULTED",
            default_reason="TAXPAYER_STOPPED_REMITTING",
            scheduled_total_cents=CANONICAL_SCHEDULED_TOTAL_CENTS,
        )

        assert_fields(
            read_agreement(api, ctx["agreement"]["id"]),
            status="EXECUTED",
            payment_status="DELINQUENT",
            paid_total_cents=CANONICAL_DOWN_PAYMENT_CENTS,
            down_payment_applied_cents=CANONICAL_DOWN_PAYMENT_CENTS,
            unapplied_credit_cents=0,
            total_due_cents=CANONICAL_TOTAL_DUE_CENTS,
        )
        assert_list_total(
            api.list_plan_installments(
                plan_id, ADMIN_HEADERS, {"status": "DEFAULTED", "limit": 100}
            ),
            11,
        )
        assert_fields(
            read_return(api, ctx["disclosure_return"]["id"]), status="FILED"
        )

    def test_paying_the_schedule_out_moves_only_the_payment_axis(self, api):
        """Full payment completes the plan and leaves the agreement `EXECUTED`.

        PRD §3.6: "The agreement's `payment_status` — a second, independent state
        dimension that never touches the agreement's own `status` — is then
        derived by testing four conditions in this order: `PAID_IN_FULL` when
        `paid_total_cents` is at least `total_due_cents`; otherwise `DELINQUENT`
        when any plan of the agreement has `status` `DEFAULTED`; otherwise
        `PARTIAL` when `paid_total_cents` is greater than 0; otherwise `UNPAID`."

        PRD §3.6: "and a plan every one of whose installments has reached `PAID`
        advances `ACTIVE → COMPLETED`."

        Design: Difficulty/non_linear_state_machine/agreement_status_and_payment_status_move_on_independent_axes
        """
        ctx = setup_approved_installment_plan(
            api,
            program_overrides={"installment_max_count": 12},
            taxpayer_overrides={
                "legal_name": "Beckwith Freight LLC",
                "tin_last4": "1188",
            },
        )
        plan_id = ctx["payment_plan"]["id"]

        remit_payment(
            api,
            ctx,
            CANONICAL_SCHEDULED_TOTAL_CENTS,
            payment_reference="SCHEDULE-OUT",
        )

        assert_fields(
            read_agreement(api, ctx["agreement"]["id"]),
            status="EXECUTED",
            payment_status="PAID_IN_FULL",
            paid_total_cents=CANONICAL_TOTAL_DUE_CENTS,
        )
        assert_fields(read_plan(api, plan_id), status="COMPLETED")
        assert_list_total(
            api.list_plan_installments(
                plan_id, ADMIN_HEADERS, {"status": "PAID", "limit": 100}
            ),
            11,
        )
        assert_fields(
            read_return(api, ctx["disclosure_return"]["id"]), status="FILED"
        )


class TestRescission:
    """Rescission compensates every hop breach fired, and only those."""

    def test_the_waiver_ledger_identity_holds_again_after_rescission(self, api):
        """Waived money returns to the waived column, cent for cent.

        PRD §3.7: "The first restores every return in `REINSTATED` status: its
        `waived_penalty_cents` and `waived_interest_cents` are recomputed by the
        waiver rollup of §3.5, its `payable_penalty_cents`,
        `payable_interest_cents` and `balance_due_cents` are recomputed from
        those, and its `status` becomes `SETTLED` when the agreement's
        `paid_total_cents` is at least its `total_due_cents` and `FILED`
        otherwise."

        PRD §3.7: "The second sets `reinstated_amount_cents` back to 0 and
        recomputes `waived_amount_cents` and `total_due_cents`."

        PRD §2.9: "A design invariant governs the waiver ledger and must hold at
        every instant at which the agreement's `status` is not `BREACHED`: summed
        across the agreement's qualifying returns, gross penalty plus gross
        interest equals the agreement's `waived_amount_cents` plus the summed
        payable penalty and payable interest."

        Design: Difficulty/compensating_invariant/breach_rescission_restores_the_waiver_ledger_exactly
        """
        ctx = _breached_agreement(api, RESCIND_TAXPAYER)

        rescinded = validate_success(
            api.rescind_breach(
                ctx["agreement"]["id"], rescind_breach_payload(), AUDITOR_ONE_HEADERS
            )
        )
        assert_fields(
            rescinded,
            status="EXECUTED",
            breach_reason=None,
            reinstated_amount_cents=0,
            waived_amount_cents=CANONICAL_WAIVED_AMOUNT_CENTS,
            total_due_cents=CANONICAL_TOTAL_DUE_CENTS,
            paid_total_cents=PAID_TOTAL_CENTS,
            payment_status="PARTIAL",
        )
        assert_fields(
            read_return(api, ctx["disclosure_return"]["id"]),
            status="FILED",
            waived_penalty_cents=CANONICAL_WAIVED_PENALTY_CENTS,
            waived_interest_cents=CANONICAL_WAIVED_INTEREST_CENTS,
            payable_penalty_cents=0,
            payable_interest_cents=CANONICAL_WAIVED_INTEREST_CENTS,
            balance_due_cents=CANONICAL_TOTAL_DUE_CENTS,
        )
        assert_waiver_ledger_identity(
            read_agreement(api, ctx["agreement"]["id"]),
            returns_of(api, ctx["agreement"]["id"]),
        )

    def test_the_schedule_and_the_escalation_are_compensated_too(self, api):
        """The plan comes back, the voided rows come back, the action abates.

        PRD §3.7: "The third restores the schedule: every plan of the agreement
        whose `status` is `DEFAULTED` **and** whose `default_reason` is exactly
        `BREACH_CASCADE` returns `DEFAULTED → ACTIVE` with `default_reason`
        nulled, each of its `VOIDED` installments returns to `SCHEDULED` with its
        `paid_cents` preserved, and the agreement's `payment_status` is
        recomputed."

        PRD §3.7: "The fourth abates the escalation: every enforcement action of
        this agreement whose `origin` is `BREACH_CASCADE` and whose `status` is
        `ISSUED` advances `ISSUED → ABATED` with `abatement_reason` set to the
        literal string `BREACH_RESCINDED`, and the taxpayer's
        `open_enforcement_action_count` and `compliance_behavior_score` are
        recomputed."

        Design: Difficulty/compensating_invariant/breach_rescission_restores_the_waiver_ledger_exactly
        """
        ctx = _breached_agreement(api, RESCIND_TAXPAYER)
        plan_id = ctx["payment_plan"]["id"]

        validate_success(
            api.rescind_breach(
                ctx["agreement"]["id"], rescind_breach_payload(), AUDITOR_ONE_HEADERS
            )
        )

        assert_fields(
            read_plan(api, plan_id),
            status="ACTIVE",
            default_reason=None,
            scheduled_total_cents=CANONICAL_SCHEDULED_TOTAL_CENTS,
        )
        restored = assert_list_total(
            api.list_plan_installments(
                plan_id, ADMIN_HEADERS, {"status": "SCHEDULED", "limit": 100}
            ),
            9,
        )
        assert (
            rows_by_seq_index(restored)[3]["paid_cents"]
            == CANONICAL_WATERFALL_TAIL_CENTS
        )
        assert_list_total(
            api.list_plan_installments(
                plan_id, ADMIN_HEADERS, {"status": "VOIDED", "limit": 100}
            ),
            0,
        )

        actions = assert_list_total(
            api.list_enforcement_actions(
                ADMIN_HEADERS,
                {
                    "agreement_id": ctx["agreement"]["id"],
                    "origin": "BREACH_CASCADE",
                    "limit": 100,
                },
            ),
            1,
        )
        assert_fields(
            actions[0], status="ABATED", abatement_reason="BREACH_RESCINDED"
        )
        assert_fields(
            read_taxpayer(api, ctx["taxpayer"]["id"]),
            open_enforcement_action_count=0,
            compliance_behavior_score=100,
        )
        assert_fields(
            read_program(api, ctx["program"]["id"]),
            reinstated_total_cents=0,
            waived_total_cents=CANONICAL_WAIVED_AMOUNT_CENTS,
        )


class TestInstallmentSweep:
    """The sweep ages the schedule in three steps on the administrator's motion."""

    def test_the_sweep_marks_the_overdue_then_defaults_the_whole_plan(self, api):
        """One installment is past grace, so the entire schedule defaults.

        PRD §3.6: "Step one advances every `SCHEDULED` installment whose
        `due_date` falls strictly before the current calendar date to `LATE`. Step
        two takes every `LATE` installment whose `due_date` plus a 30-day grace
        period still falls strictly before the current calendar date, advances it
        `LATE → DEFAULTED`, and advances its owning `ACTIVE` plan `ACTIVE →
        DEFAULTED` with `default_reason` set to the literal string
        `SWEEP_GRACE_EXPIRED`. Step three advances the remaining installments of a
        plan defaulted in step two — those still in `SCHEDULED` or `LATE` — to
        `DEFAULTED`."

        PRD §3.6: "Schedules age on the administrator's motion through a
        program-scoped sweep, which reports how much it moved as
        `marked_late_count`, `defaulted_installment_count` and
        `defaulted_plan_count`."

        PRD §3.6: "Agreements whose plan defaulted have `payment_status` set to
        `DELINQUENT`, and every touched installment, plan and agreement has its
        `version` advanced by one."

        Design: Corner/Table 2 State Machines/installment_sweep_ages_the_schedule_then_defaults_the_whole_plan
        """
        ctx = setup_approved_installment_plan(
            api,
            program_overrides={"installment_max_count": 12},
            taxpayer_overrides={
                "legal_name": "Mossbank Timber LLC",
                "tin_last4": "5507",
            },
        )
        plan_id = ctx["payment_plan"]["id"]
        schedule = rows_by_seq_index(installments_of(api, plan_id))
        assert_fields(schedule[1], due_date="2026-10-15", status="SCHEDULED")
        assert_fields(schedule[2], due_date="2026-11-14", status="SCHEDULED")

        set_clock(api, "2026-11-20T00:00:00Z")
        report = validate_success(
            api.run_installment_sweep(ctx["program"]["id"], ADMIN_HEADERS)
        )
        assert_fields(
            report,
            marked_late_count=2,
            defaulted_installment_count=11,
            defaulted_plan_count=1,
        )

        assert_fields(
            read_plan(api, plan_id),
            status="DEFAULTED",
            default_reason="SWEEP_GRACE_EXPIRED",
        )
        assert_list_total(
            api.list_plan_installments(
                plan_id, ADMIN_HEADERS, {"status": "DEFAULTED", "limit": 100}
            ),
            11,
        )
        assert_list_total(
            api.list_plan_installments(
                plan_id, ADMIN_HEADERS, {"status": "LATE", "limit": 100}
            ),
            0,
        )
        assert_list_total(
            api.list_plan_installments(
                plan_id, ADMIN_HEADERS, {"status": "SCHEDULED", "limit": 100}
            ),
            0,
        )
        assert_fields(
            read_agreement(api, ctx["agreement"]["id"]),
            status="EXECUTED",
            payment_status="DELINQUENT",
        )

        repeat = validate_success(
            api.run_installment_sweep(ctx["program"]["id"], ADMIN_HEADERS)
        )
        assert_fields(
            repeat,
            marked_late_count=0,
            defaulted_installment_count=0,
            defaulted_plan_count=0,
        )
