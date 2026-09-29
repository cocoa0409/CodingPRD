"""Disputes: the loss cascade, the guarantee waterfall and the fraud feedback loop."""

from __future__ import annotations

from test_helpers import (
    ADMIN,
    ApiClient,
    ApiErrorId,
    AssessmentState,
    CLOCK_EPOCH,
    CaseState,
    ChargebackAction,
    ChargebackReasonCode,
    ChargebackState,
    DeviceReputation,
    DropRiskState,
    GuaranteeDenialReason,
    GuaranteeState,
    LARGE_ORDER_CENTS,
    OutcomeLabel,
    PROB_DECLINE_EXACTLY_AT_DECLINE_FLOOR,
    STANDARD_ORDER_CENTS,
    SMALL_ORDER_CENTS,
    assert_chargeback,
    assert_guarantee_denied,
    assert_guarantee_reimbursed,
    assert_net_approved_ledger,
    assert_score,
    build_approved_assessment,
    build_good_customer,
    build_lost_chargeback,
    build_reviewed_assessment,
    build_scoring_env,
    build_won_chargeback,
    chargeback_transition_payload,
    create_chargeback_payload,
    file_chargeback,
    open_and_score,
    parse_instant,
    read_address,
    read_assessment,
    read_case,
    read_chargeback,
    read_customer,
    read_device,
    set_clock,
    transition_chargeback,
    validate_error,
    validate_paginated,
    validate_success,
)

#: A partial dispute, well under the 15,000-cent orders it is filed against.
PARTIAL_DISPUTE_CENTS = 5000

#: The network reports the dispute a day after the order was decided.
DISPUTE_RECEIVED_AT = "2026-08-02T00:00:00Z"

#: One second before the order was decided, which the strict check refuses.
ONE_SECOND_BEFORE_DECISION = "2026-07-31T23:59:59Z"

#: More than the disputed order was ever worth.
OVER_ORDER_DISPUTE_CENTS = 99000


class TestFilingLeavesEveryCascadeUnfired:
    """Creating a dispute is a filing, not an outcome."""

    def test_a_filed_dispute_starts_in_received_with_nothing_settled(
        self, api: ApiClient
    ) -> None:
        """RECEIVED carries no guarantee figures and moves neither ledger nor label.

        PRD: "The record starts in state `RECEIVED` with `guarantee_state`
        `NOT_APPLICABLE`, `guarantee_denial_reason` null, all three guarantee amounts
        at 0 and `resolved_at` null."
        PRD: "**Only when `reason_code` is `FRAUD_CNP` or `FRAUD_ATO`**, the
        assessment's `outcome_label` is set to `FRAUD`."

        Design: Corner/state_machines/chargeback_initial_state_is_received_with_guarantee_not_applicable
        """
        env = build_scoring_env(api)
        approved = build_approved_assessment(api, env, STANDARD_ORDER_CENTS)
        assert_score(approved["blended_score"], 39.95, "blended_score")
        set_clock(api, DISPUTE_RECEIVED_AT)

        filed = file_chargeback(
            api,
            approved["id"],
            STANDARD_ORDER_CENTS,
            DISPUTE_RECEIVED_AT,
            reason_code=ChargebackReasonCode.FRAUD_CNP,
            liability_shift=False,
        )
        assert_chargeback(filed)
        assert filed["state"] == ChargebackState.RECEIVED
        assert filed["guarantee_state"] == GuaranteeState.NOT_APPLICABLE
        assert filed["guarantee_denial_reason"] is None
        assert filed["guarantee_eligible_cents"] == 0
        assert filed["guarantee_fee_cents"] == 0
        assert filed["guarantee_reimbursed_cents"] == 0
        assert filed["resolved_at"] is None
        assert int(filed["version"]) == 1

        assessment = read_assessment(api, approved["id"])
        assert assessment["state"] == AssessmentState.DECIDED_APPROVE
        assert assessment["outcome_label"] == OutcomeLabel.UNKNOWN, (
            "filing labels nothing; only a loss does"
        )

        customer = read_customer(api, env.customer_id)
        assert customer["lifetime_net_approved_cents"] == STANDARD_ORDER_CENTS
        assert customer["confirmed_fraud_count"] == 0


class TestWonDisputeIsTerminal:
    """WON admits no further action, and the won order stays good."""

    def test_losing_an_already_won_dispute_is_refused_and_changes_nothing(
        self, api: ApiClient
    ) -> None:
        """A LOSE on a WON record is a transition error, so the loss cascade never runs.

        PRD: "`REPRESENTED → WON` via `WIN` stamps `resolved_at`, leaves
        `guarantee_state` at `NOT_APPLICABLE` — the guarantee waterfall runs only on a
        loss — and sets the assessment's `outcome_label` to `LEGIT`. The customer's
        `lifetime_net_approved_cents` is deliberately unchanged: a won dispute confirms
        the order was good."
        PRD: "Any pairing of current state with action other than the four declared
        transitions is `ERR_CHARGEBACK_TRANSITION_INVALID`."

        Design: Corner/state_machines/chargeback_transition_from_won_terminal_state_rejected
        """
        env = build_scoring_env(api)
        approved = build_approved_assessment(api, env, STANDARD_ORDER_CENTS)
        set_clock(api, DISPUTE_RECEIVED_AT)

        won = build_won_chargeback(
            api, approved["id"], STANDARD_ORDER_CENTS, DISPUTE_RECEIVED_AT
        )
        assert won["state"] == ChargebackState.WON
        assert won["resolved_at"] is not None
        assert won["guarantee_state"] == GuaranteeState.NOT_APPLICABLE
        assert read_assessment(api, approved["id"])["outcome_label"] == (
            OutcomeLabel.LEGIT
        )

        response = api.transition_chargeback(
            won["id"], chargeback_transition_payload(ChargebackAction.LOSE), ADMIN
        )
        validate_error(response, ApiErrorId.ERR_CHARGEBACK_TRANSITION_INVALID, 409)

        assert read_chargeback(api, won["id"])["state"] == ChargebackState.WON
        assert read_assessment(api, approved["id"])["outcome_label"] == (
            OutcomeLabel.LEGIT
        ), "the refused LOSE must not relabel the order"

        customer = read_customer(api, env.customer_id)
        assert customer["lifetime_net_approved_cents"] == STANDARD_ORDER_CENTS
        assert customer["confirmed_fraud_count"] == 0


class TestRepresentIsNotReplayable:
    """A retried representment is refused rather than silently absorbed."""

    def test_a_second_represent_is_refused_and_keeps_the_first_evidence_note(
        self, api: ApiClient
    ) -> None:
        """The duplicate note never lands, and the record stays at version 2.

        PRD: "`RECEIVED → REPRESENTED` via `REPRESENT` stores the `evidence_note`
        representment summary and increments `version`."
        PRD: "The cascades are specified, not incidental, and a request either performs
        all of a cascade's links or none of them."

        Design: Corner/state_machines/chargeback_represent_applied_twice_rejected
        """
        env = build_scoring_env(api)
        approved = build_approved_assessment(api, env, STANDARD_ORDER_CENTS)
        set_clock(api, DISPUTE_RECEIVED_AT)

        filed = file_chargeback(
            api, approved["id"], STANDARD_ORDER_CENTS, DISPUTE_RECEIVED_AT
        )
        represented = transition_chargeback(
            api,
            filed["id"],
            ChargebackAction.REPRESENT,
            evidence_note="first submission",
        )
        assert represented["state"] == ChargebackState.REPRESENTED
        assert int(represented["version"]) == 2

        response = api.transition_chargeback(
            filed["id"],
            chargeback_transition_payload(
                ChargebackAction.REPRESENT, evidence_note="duplicate submission"
            ),
            ADMIN,
        )
        validate_error(response, ApiErrorId.ERR_CHARGEBACK_TRANSITION_INVALID, 409)

        unchanged = read_chargeback(api, filed["id"])
        assert unchanged["state"] == ChargebackState.REPRESENTED
        assert unchanged["evidence_note"] == "first submission", (
            "the refused retry must not overwrite the stored representment summary"
        )
        assert int(unchanged["version"]) == 2


class TestLostDisputeRepricesTheQueue:
    """A confirmed fraud in one corner of an account re-prices its open cases."""

    def test_lost_fraud_dispute_reverses_the_ledger_and_reprices_the_open_case(
        self, api: ApiClient
    ) -> None:
        """Losing the good-customer flag drops a queued case from 52.50 to 32.50.

        PRD: "Caused by link 4, and **only when the flag actually flipped**:
        `priority_score` is recomputed for every review case belonging to that
        customer's assessments whose state is `QUEUED`, `ASSIGNED` or `ESCALATED`,
        each such case's `version` incrementing by one."
        PRD: "Unlike the assessment's frozen `good_customer_at_decision`, this term
        reads the customer's **current** flag, which is exactly what lets a
        confirmed fraud elsewhere on the account re-price the queue — the same case,
        after the flag is lost, scores 32.50."

        Design: Difficulty/transitive_cascade/chargeback_loss_reprices_open_review_queue
        """
        env = build_scoring_env(api)
        approvals = build_good_customer(api, env, SMALL_ORDER_CENTS)
        assert read_customer(api, env.customer_id)["good_customer_flag"] is True

        assessment, case = build_reviewed_assessment(api, env, LARGE_ORDER_CENTS)
        assert_score(assessment["blended_score"], 50.00, "blended_score")
        assert_score(
            case["priority_score"], 52.50, "priority_score while the flag holds"
        )

        build_lost_chargeback(
            api, approvals[0]["id"], SMALL_ORDER_CENTS, CLOCK_EPOCH
        )

        customer = read_customer(api, env.customer_id)
        assert customer["confirmed_fraud_count"] == 1
        assert customer["approved_count"] == 2, (
            "a lost dispute does not undo the approval itself"
        )
        assert customer["good_customer_flag"] is False
        assert customer["lifetime_net_approved_cents"] == SMALL_ORDER_CENTS
        assert assert_net_approved_ledger(api, env.customer_id, ADMIN) == (
            SMALL_ORDER_CENTS
        )

        repriced = read_case(api, case["id"])
        assert_score(
            repriced["priority_score"], 32.50, "priority_score after the flag is lost"
        )
        assert repriced["state"] == CaseState.QUEUED, (
            "re-pricing does not staff or resolve the case"
        )
        assert int(repriced["version"]) > int(case["version"]), (
            "a recomputation of a derived field is a mutation"
        )

    def test_the_loss_recounts_the_device_and_the_shipping_cluster(
        self, api: ApiClient
    ) -> None:
        """The disputed order's device and address both pick up one confirmed fraud.

        PRD: "Also caused by link 2, the device profile's counters and `reputation`
        are recomputed, and the shipping cluster root's counters, `drop_risk_state`
        and `reshipper_confidence` are recomputed."
        PRD: "A `REIMBURSED` outcome sets `guarantee_eligible_cents` to the smallest
        of three figures — the disputed `amount_cents`, the order's own
        `amount_cents`, and the programme coverage cap of 500,000 cents; sets
        `guarantee_fee_cents` to the programme fee of 250 basis points, that is 2.50
        percent of the eligible amount, **floored** to whole cents and never rounded
        up; and sets `guarantee_reimbursed_cents` to the eligible amount minus the
        fee."

        Design: Difficulty/transitive_cascade/chargeback_loss_reprices_open_review_queue
        """
        env = build_scoring_env(api)
        approvals = build_good_customer(api, env, SMALL_ORDER_CENTS)
        build_reviewed_assessment(api, env, LARGE_ORDER_CENTS)

        lost = build_lost_chargeback(
            api, approvals[0]["id"], SMALL_ORDER_CENTS, CLOCK_EPOCH
        )
        assert lost["state"] == ChargebackState.LOST
        assert_guarantee_reimbursed(lost, SMALL_ORDER_CENTS, 375, 14625)

        assert read_assessment(api, approvals[0]["id"])["outcome_label"] == (
            OutcomeLabel.FRAUD
        )
        assert read_assessment(api, approvals[1]["id"])["outcome_label"] == (
            OutcomeLabel.UNKNOWN
        ), "the sibling order is untouched by the dispute"

        device = read_device(api, env.device_id)
        assert device["fraud_confirmed_count"] == 1
        assert device["reputation"] == DeviceReputation.SUSPECT

        address = read_address(api, env.address_id)
        assert address["fraud_confirmed_count"] == 1
        assert address["drop_risk_state"] == DropRiskState.WATCH
        assert_score(
            address["reshipper_confidence"], 0.20, "address.reshipper_confidence"
        )


class TestSecondLossOnTheSameOrder:
    """The ledger has an idempotence guard, and the recounts are recounts."""

    def test_second_lost_dispute_moves_neither_the_ledger_nor_the_fraud_count(
        self, api: ApiClient
    ) -> None:
        """A second loss on an order already labelled FRAUD changes nothing downstream.

        PRD: "It also fires **only** on that `UNKNOWN` to `FRAUD` transition: a
        second lost dispute on an order already labelled `FRAUD` moves neither this
        ledger nor `confirmed_fraud_count`."
        PRD: "A customer's `lifetime_net_approved_cents` must always equal the sum
        of `amount_cents` over that customer's assessments that are in state
        `DECIDED_APPROVE` and whose `outcome_label` is not `FRAUD`."

        Design: Difficulty/compensating_invariant/net_approved_ledger_survives_second_lost_chargeback
        """
        env = build_scoring_env(api)
        approvals = build_good_customer(api, env, SMALL_ORDER_CENTS)
        target = approvals[0]["id"]

        build_lost_chargeback(
            api, target, PARTIAL_DISPUTE_CENTS, CLOCK_EPOCH, represent_first=False
        )
        after_first = read_customer(api, env.customer_id)
        assert after_first["lifetime_net_approved_cents"] == SMALL_ORDER_CENTS, (
            "the reversal uses the order amount, not the partial disputed amount"
        )
        assert after_first["confirmed_fraud_count"] == 1

        build_lost_chargeback(
            api, target, PARTIAL_DISPUTE_CENTS, CLOCK_EPOCH, represent_first=False
        )

        after_second = read_customer(api, env.customer_id)
        assert after_second["lifetime_net_approved_cents"] == SMALL_ORDER_CENTS, (
            "the ledger must not be decremented twice for one order"
        )
        assert after_second["confirmed_fraud_count"] == 1
        assert after_second["approved_count"] == 2
        assert assert_net_approved_ledger(api, env.customer_id, ADMIN) == (
            SMALL_ORDER_CENTS
        )

        assert read_assessment(api, target)["state"] == (
            AssessmentState.DECIDED_APPROVE
        ), "the assessment's own state is not changed by a dispute"
        assert read_assessment(api, target)["outcome_label"] == OutcomeLabel.FRAUD
        assert read_assessment(api, approvals[1]["id"])["outcome_label"] == (
            OutcomeLabel.UNKNOWN
        )

    def test_second_loss_still_settles_its_own_guarantee_but_recounts_are_stable(
        self, api: ApiClient
    ) -> None:
        """Link one always runs, so the second dispute settles at 5,000/125/4,875.

        PRD: "1. `state` becomes `LOST`, `resolved_at` is stamped, `version`
        increments, and the guarantee waterfall runs, filling `guarantee_state`,
        `guarantee_denial_reason`, `guarantee_eligible_cents`, `guarantee_fee_cents`
        and `guarantee_reimbursed_cents`."
        PRD: "Because a recount is a count and not an increment, running it twice
        with the same underlying rows leaves the value unchanged — which is why a
        second lost chargeback against the same order does not double-count
        anything."

        Design: Difficulty/compensating_invariant/net_approved_ledger_survives_second_lost_chargeback
        """
        env = build_scoring_env(api)
        approvals = build_good_customer(api, env, SMALL_ORDER_CENTS)
        target = approvals[0]["id"]

        first = build_lost_chargeback(
            api, target, PARTIAL_DISPUTE_CENTS, CLOCK_EPOCH, represent_first=False
        )
        assert first["guarantee_state"] == GuaranteeState.REIMBURSED
        assert_guarantee_reimbursed(first, PARTIAL_DISPUTE_CENTS, 125, 4875)
        device_after_first = read_device(api, env.device_id)

        second = build_lost_chargeback(
            api, target, PARTIAL_DISPUTE_CENTS, CLOCK_EPOCH, represent_first=False
        )
        assert second["id"] != first["id"], "the two disputes are separate records"
        assert_guarantee_reimbursed(second, PARTIAL_DISPUTE_CENTS, 125, 4875)

        device_after_second = read_device(api, env.device_id)
        assert device_after_second["fraud_confirmed_count"] == (
            device_after_first["fraud_confirmed_count"]
        ), "the device recount is over rows, so it cannot double-count"
        assert device_after_second["fraud_confirmed_count"] == 1
        assert device_after_second["reputation"] == DeviceReputation.SUSPECT


class TestGuaranteeWaterfallShortCircuits:
    """Test one of the waterfall decides the reason before any later test runs."""

    def test_a_liability_shifted_fraud_dispute_denies_and_still_reverses_the_ledger(
        self, api: ApiClient
    ) -> None:
        """The denial is LIABILITY_SHIFTED, yet the fraud feedback loop still fires.

        PRD: "The **first** test that fails decides `guarantee_denial_reason`, and no
        later test is evaluated:"
        PRD: "A `DENIED` outcome leaves `guarantee_eligible_cents`,
        `guarantee_fee_cents` and `guarantee_reimbursed_cents` all at 0."

        Design: Corner/calculations/guarantee_waterfall_denies_on_liability_shift_before_later_tests
        """
        env = build_scoring_env(api)
        approved = build_approved_assessment(api, env, STANDARD_ORDER_CENTS)
        assert read_customer(api, env.customer_id)["lifetime_net_approved_cents"] == (
            STANDARD_ORDER_CENTS
        )
        set_clock(api, DISPUTE_RECEIVED_AT)

        lost = build_lost_chargeback(
            api,
            approved["id"],
            STANDARD_ORDER_CENTS,
            DISPUTE_RECEIVED_AT,
            represent_first=False,
            reason_code=ChargebackReasonCode.FRAUD_ATO,
            liability_shift=True,
        )
        assert lost["state"] == ChargebackState.LOST
        assert lost["resolved_at"] is not None
        assert_guarantee_denied(lost, GuaranteeDenialReason.LIABILITY_SHIFTED)

        assert read_assessment(api, approved["id"])["outcome_label"] == (
            OutcomeLabel.FRAUD
        ), "a covered fraud reason code still labels the order"

        customer = read_customer(api, env.customer_id)
        assert customer["lifetime_net_approved_cents"] == 0, (
            "the reversal uses the order's own amount"
        )
        assert customer["confirmed_fraud_count"] == 1
        assert customer["good_customer_flag"] is False

        device = read_device(api, env.device_id)
        assert device["fraud_confirmed_count"] == 1
        assert device["reputation"] == DeviceReputation.SUSPECT


class TestFilingChecksRunInTheirDeclaredOrder:
    """The approved-order check outranks both of the checks behind it."""

    def test_a_dispute_against_a_declined_order_reports_the_state_not_the_amount(
        self, api: ApiClient
    ) -> None:
        """Even an over-order amount still reports the unapproved assessment.

        PRD: "Filing checks run in this order: the referenced assessment must be in
        state `DECIDED_APPROVE`, or `ERR_CHARGEBACK_ASSESSMENT_NOT_APPROVED`;
        `received_at` must not precede the assessment's `decided_at`, or
        `ERR_CHARGEBACK_BEFORE_DECISION`; and the disputed `amount_cents` must not exceed
        the order's own `amount_cents`, or `ERR_CHARGEBACK_AMOUNT_EXCEEDS_ORDER`."
        PRD: "Validation is a single ordered ladder, not a set of independent checks.
        The **first** violated rule decides the response, and no later rule is
        evaluated."

        Design: Corner/validations/chargeback_against_declined_assessment_rejected
        """
        env = build_scoring_env(api)
        declined = open_and_score(
            api,
            env,
            amount_cents=STANDARD_ORDER_CENTS,
            model_raw_probability=PROB_DECLINE_EXACTLY_AT_DECLINE_FLOOR,
        )
        assert declined["state"] == AssessmentState.DECIDED_DECLINE
        assert_score(declined["blended_score"], 60.00, "blended_score")
        set_clock(api, DISPUTE_RECEIVED_AT)

        for amount_cents in (STANDARD_ORDER_CENTS, OVER_ORDER_DISPUTE_CENTS):
            response = api.create_chargeback(
                create_chargeback_payload(
                    declined["id"], amount_cents, DISPUTE_RECEIVED_AT
                ),
                ADMIN,
            )
            validate_error(
                response, ApiErrorId.ERR_CHARGEBACK_ASSESSMENT_NOT_APPROVED, 422
            )

        _rows, meta = validate_paginated(
            api.list_chargebacks(ADMIN, params={"assessment_id": declined["id"]})
        )
        assert meta["total_count"] == 0, "neither rejected filing was stored"

    def test_a_dispute_received_before_the_decision_is_refused_but_one_at_it_is_not(
        self, api: ApiClient
    ) -> None:
        """One second early is refused; exactly at ``decided_at`` is accepted.

        PRD: "`received_at` must not precede the assessment's `decided_at`, or
        `ERR_CHARGEBACK_BEFORE_DECISION`; and the disputed `amount_cents` must not exceed
        the order's own `amount_cents`, or `ERR_CHARGEBACK_AMOUNT_EXCEEDS_ORDER`."
        PRD: "The record starts in state `RECEIVED` with `guarantee_state`
        `NOT_APPLICABLE`, `guarantee_denial_reason` null, all three guarantee amounts at
        0 and `resolved_at` null."

        Design: Corner/validations/chargeback_received_before_decision_rejected
        """
        env = build_scoring_env(api)
        approved = build_approved_assessment(api, env, STANDARD_ORDER_CENTS)
        assert parse_instant(approved["decided_at"]) == parse_instant(CLOCK_EPOCH)
        set_clock(api, DISPUTE_RECEIVED_AT)

        too_early = api.create_chargeback(
            create_chargeback_payload(
                approved["id"], STANDARD_ORDER_CENTS, ONE_SECOND_BEFORE_DECISION
            ),
            ADMIN,
        )
        validate_error(too_early, ApiErrorId.ERR_CHARGEBACK_BEFORE_DECISION, 422)

        too_large = api.create_chargeback(
            create_chargeback_payload(
                approved["id"], STANDARD_ORDER_CENTS + 1, CLOCK_EPOCH
            ),
            ADMIN,
        )
        validate_error(too_large, ApiErrorId.ERR_CHARGEBACK_AMOUNT_EXCEEDS_ORDER, 422)

        accepted = validate_success(
            api.create_chargeback(
                create_chargeback_payload(
                    approved["id"], STANDARD_ORDER_CENTS, CLOCK_EPOCH
                ),
                ADMIN,
            ),
            201,
        )
        assert_chargeback(accepted)
        assert accepted["state"] == ChargebackState.RECEIVED, (
            "a dispute received exactly at the decision instant does not precede it"
        )

        _rows, meta = validate_paginated(
            api.list_chargebacks(ADMIN, params={"assessment_id": approved["id"]})
        )
        assert meta["total_count"] == 1
