"""Decisioning assets over time: model lifecycle and the pinning contract.

The retraining loop and the reason-code segment gate come first, then what
happens to an unscored order whose pinned pack or model has moved on.
"""

from __future__ import annotations

from test_helpers import (
    CHECKOUT,
    ENGINEER,
    ApiClient,
    ApiErrorId,
    AssessmentState,
    build_active_rule_pack,
    build_approved_assessment,
    build_lost_chargeback,
    build_scoring_env,
    ChargebackReasonCode,
    CLOCK_EPOCH,
    create_address,
    create_assessment_payload,
    create_customer,
    create_device,
    create_risk_model_payload,
    Decision,
    draft_risk_model,
    model_action,
    model_lifecycle_payload,
    open_assessment,
    parse_instant,
    PROB_APPROVE_JUST_UNDER_REVIEW_FLOOR,
    read_assessment,
    read_customer,
    read_risk_model,
    read_rule_pack,
    REFERENCE_RULES,
    retire_active_model_by_promoting_successor,
    retire_active_pack_by_activating_successor,
    RiskModelAction,
    RiskModelStatus,
    RulePackStatus,
    score_assessment,
    set_clock,
    SMALL_ORDER_CENTS,
    STANDARD_ORDER_CENTS,
    validate_error,
    validate_paginated,
    validate_success,
)

CNP_EARLY = "2026-08-01T00:00:00Z"
CNP_LATE = "2026-08-02T00:00:00Z"
ATO_EARLY = "2026-08-01T00:00:00Z"
#: The instant used as the cutoff in the first attempt, so this dispute sits on it.
ATO_ON_THE_CUTOFF = "2026-08-05T00:00:00Z"
CLOCK_AFTER_DISPUTES = "2026-08-06T00:00:00Z"
CUTOFF_AT_THE_DISPUTE = ATO_ON_THE_CUTOFF
CUTOFF_ONE_SECOND_LATER = "2026-08-05T00:00:01Z"
DISPUTE_CENTS = 5000

#: One month after the epoch the clock reads, so strictly in the future.
CUTOFF_ONE_MONTH_AHEAD = "2026-09-01T00:00:00Z"


def _build_lost_dispute_corpus(api: ApiClient):
    """Two lost CNP disputes and two lost ATO disputes across two approved orders."""
    env = build_scoring_env(api)
    first = build_approved_assessment(api, env, SMALL_ORDER_CENTS)
    second = build_approved_assessment(api, env, SMALL_ORDER_CENTS)
    set_clock(api, CLOCK_AFTER_DISPUTES)

    for assessment_id, reason_code, received_at in (
        (first["id"], ChargebackReasonCode.FRAUD_CNP, CNP_EARLY),
        (first["id"], ChargebackReasonCode.FRAUD_CNP, CNP_LATE),
        (second["id"], ChargebackReasonCode.FRAUD_ATO, ATO_EARLY),
        (second["id"], ChargebackReasonCode.FRAUD_ATO, ATO_ON_THE_CUTOFF),
    ):
        build_lost_chargeback(
            api,
            assessment_id,
            DISPUTE_CENTS,
            received_at,
            represent_first=False,
            reason_code=reason_code,
        )
    return env


class TestTrainingSegmentCutoffBoundary:
    """The segment gate counts disputes strictly earlier than the cutoff."""

    def test_a_dispute_received_exactly_at_the_cutoff_is_not_counted(
        self, api: ApiClient
    ) -> None:
        """With the cutoff on the fourth dispute, the ATO segment holds only one.

        PRD: "the chargeback records whose `state` is `LOST`, whose `reason_code` is
        that segment, and whose `received_at` is **strictly earlier** than the
        model's `trained_on_chargeback_cutoff_at` — a dispute received at exactly the
        cutoff instant is excluded."
        PRD: "Training proceeds only when **every** required segment holds at least 2
        such records; otherwise the request is rejected with
        `ERR_TRAINING_SEGMENT_UNDERFILLED`, identifying the first deficient segment in
        that same fixed order."

        Design: Difficulty/boundary_precision_check/training_cutoff_excludes_chargeback_received_at_cutoff_exactly
        """
        env = _build_lost_dispute_corpus(api)
        candidate = draft_risk_model(
            api, trained_on_chargeback_cutoff_at=CUTOFF_AT_THE_DISPUTE
        )
        assert candidate["status"] == RiskModelStatus.DRAFT
        assert candidate["training_segment_counts"] is None

        response = api.risk_model_lifecycle(
            candidate["id"],
            model_lifecycle_payload(RiskModelAction.START_TRAINING),
            ENGINEER,
        )
        validate_error(response, ApiErrorId.ERR_TRAINING_SEGMENT_UNDERFILLED, 422)

        unchanged = read_risk_model(api, candidate["id"])
        assert unchanged["status"] == RiskModelStatus.DRAFT
        assert unchanged["training_segment_counts"] is None, (
            "the frozen map is written only on a successful gate"
        )

        customer = read_customer(api, env.customer_id)
        assert customer["confirmed_fraud_count"] == 2, (
            "the two orders each carry one confirmed fraud, not two"
        )
        assert customer["lifetime_net_approved_cents"] == 0

    def test_moving_the_cutoff_one_second_later_admits_the_dispute(
        self, api: ApiClient
    ) -> None:
        """A cutoff one second past the dispute fills both segments and freezes the map.

        PRD: "**`DRAFT → TRAINING`** via `START_TRAINING`, permitted only when
        `trained_on_chargeback_cutoff_at` is non-null and the reason-code segment gate
        is satisfied. On success, `training_segment_counts` is **frozen** to the
        per-reason-code map the gate computed."

        Design: Difficulty/boundary_precision_check/training_cutoff_excludes_chargeback_received_at_cutoff_exactly
        """
        _build_lost_dispute_corpus(api)
        candidate = draft_risk_model(
            api, trained_on_chargeback_cutoff_at=CUTOFF_ONE_SECOND_LATER
        )

        trained = model_action(
            api, candidate["id"], RiskModelAction.START_TRAINING
        )
        assert trained["status"] == RiskModelStatus.TRAINING
        counts = trained["training_segment_counts"]
        assert counts is not None, "the gate freezes its map on success"
        assert counts[ChargebackReasonCode.FRAUD_CNP] == 2
        assert counts[ChargebackReasonCode.FRAUD_ATO] == 2, (
            "the dispute one second before the cutoff is counted"
        )
        assert int(trained["version"]) > int(candidate["version"]), (
            "every accepted lifecycle action increments the model's version"
        )


class TestRejectingAShadowModelIsCompensating:
    """REJECT walks a cold-start model back to DRAFT rather than ending it."""

    def test_a_rejected_shadow_returns_to_draft_and_cannot_be_promoted(
        self, api: ApiClient
    ) -> None:
        """DRAFT to SHADOW to DRAFT leaves the model at version 3 and unpromotable.

        PRD: "**`SHADOW → DRAFT`** via `REJECT`, which clears `training_segment_counts`
        back to null. This is the retraining loop: a rejected shadow model returns to
        the drawing board and may be trained again."
        PRD: "Any pairing of current status and requested action that is not one of the
        transitions below — including a shadow publication straight out of `DRAFT` when
        the cutoff is non-null — is rejected with `ERR_MODEL_TRANSITION_INVALID`. Every
        accepted action increments the model's `version` by one."

        Design: Corner/state_machines/risk_model_shadow_reject_returns_to_draft_and_clears_counts
        """
        set_clock(api)
        candidate = draft_risk_model(api, model_version_label="M-cold")
        assert candidate["status"] == RiskModelStatus.DRAFT
        assert candidate["trained_on_chargeback_cutoff_at"] is None
        assert int(candidate["version"]) == 1

        shadow = model_action(api, candidate["id"], RiskModelAction.PUBLISH_SHADOW)
        assert shadow["status"] == RiskModelStatus.SHADOW, (
            "a null cutoff is the cold-start branch, which skips TRAINING"
        )
        assert int(shadow["version"]) == 2

        rejected = model_action(api, candidate["id"], RiskModelAction.REJECT)
        assert rejected["status"] == RiskModelStatus.DRAFT
        assert rejected["training_segment_counts"] is None
        assert rejected["promoted_at"] is None
        assert int(rejected["version"]) == 3

        response = api.risk_model_lifecycle(
            candidate["id"],
            model_lifecycle_payload(RiskModelAction.PROMOTE),
            ENGINEER,
        )
        validate_error(response, ApiErrorId.ERR_MODEL_TRANSITION_INVALID, 409)

        unchanged = read_risk_model(api, candidate["id"])
        assert unchanged["status"] == RiskModelStatus.DRAFT, (
            "promotion is reachable only from SHADOW"
        )
        assert int(unchanged["version"]) == 3, (
            "a refused action does not increment the version"
        )
        assert unchanged["promoted_at"] is None


class TestTrainingCutoffMustNotLeadTheClock:
    """A cutoff may sit on the logical clock, but never after it."""

    def test_a_cutoff_a_month_ahead_is_refused_while_the_clock_instant_is_accepted(
        self, api: ApiClient
    ) -> None:
        """The gate is strict, so the accepted draft still carries a null count map.

        PRD: "A supplied `trained_on_chargeback_cutoff_at` that lies after the current
        logical clock reading is rejected with `ERR_TRAINING_CUTOFF_IN_FUTURE`."
        PRD: "It starts in `status` `DRAFT` with `training_segment_counts` null,
        `promoted_at` and `retired_at` null, and `scored_assessment_count` at 0."

        Design: Corner/errors/risk_model_training_cutoff_in_the_future_rejected
        """
        set_clock(api, CLOCK_EPOCH)

        ahead = api.create_risk_model(
            create_risk_model_payload(
                model_version_label="M-future",
                trained_on_chargeback_cutoff_at=CUTOFF_ONE_MONTH_AHEAD,
            ),
            ENGINEER,
        )
        validate_error(ahead, ApiErrorId.ERR_TRAINING_CUTOFF_IN_FUTURE, 422)

        accepted = validate_success(
            api.create_risk_model(
                create_risk_model_payload(
                    model_version_label="M-now",
                    trained_on_chargeback_cutoff_at=CLOCK_EPOCH,
                ),
                ENGINEER,
            ),
            201,
        )
        assert accepted["status"] == RiskModelStatus.DRAFT
        assert parse_instant(accepted["trained_on_chargeback_cutoff_at"]) == (
            parse_instant(CLOCK_EPOCH)
        ), "a cutoff exactly on the clock reading is not in the future"
        assert accepted["training_segment_counts"] is None, (
            "a fresh draft carries no segment counts, cutoff or not"
        )
        assert accepted["scored_assessment_count"] == 0
        assert accepted["promoted_at"] is None
        assert accepted["retired_at"] is None

        _rows, meta = validate_paginated(api.list_risk_models(ENGINEER))
        assert meta["total_count"] == 1, "only the accepted draft was stored"

#: The successor pack opens one hour after the incumbent's window closes, which is
#: exactly the activation freeze buffer.
SUCCESSOR_PACK_FROM = "2027-01-01T01:00:00Z"
SUCCESSOR_PACK_UNTIL = "2027-06-01T00:00:00Z"


class TestPinnedRiskModelMustStillBeActive:
    """Promoting a successor model strands every assessment pinned to the old one."""

    def test_scoring_is_refused_when_the_pinned_model_was_retired_by_a_successor(
        self, api: ApiClient
    ) -> None:
        """The stranded assessment is refused, not silently re-pinned.

        PRD: "Pinning creates a window in which the world can move underneath an
        unscored assessment, and the specification treats that as a hard failure
        rather than a silent re-pin. If either pinned asset has left `ACTIVE` by the
        time scoring is requested, scoring is refused — `ERR_RULE_PACK_NOT_ACTIVE`
        when the pack has moved on, `ERR_RISK_MODEL_NOT_ACTIVE` when the model has.
        The assessment stays in `PENDING_SIGNALS` forever; there is no repair path."

        Design: Difficulty/cross_entity_state_dependency/score_rejected_when_pinned_risk_model_retired_by_successor
        """
        env = build_scoring_env(api)
        stranded = open_assessment(api, env)
        assert stranded["state"] == AssessmentState.PENDING_SIGNALS
        assert stranded["risk_model_id"] == env.model_id
        assert stranded["rule_pack_id"] == env.pack_id

        successor = retire_active_model_by_promoting_successor(api)
        assert successor["status"] == RiskModelStatus.ACTIVE
        assert successor["id"] != env.model_id
        assert read_risk_model(api, env.model_id)["status"] == RiskModelStatus.RETIRED

        response = api.score_assessment(stranded["id"], CHECKOUT)
        validate_error(response, ApiErrorId.ERR_RISK_MODEL_NOT_ACTIVE, 409)

        unscored = read_assessment(api, stranded["id"])
        assert unscored["state"] == AssessmentState.PENDING_SIGNALS
        assert unscored["blended_score"] is None
        assert unscored["model_points"] is None
        assert unscored["decision"] is None
        assert unscored["decision_reason"] is None
        assert unscored["risk_model_id"] == env.model_id, (
            "a refused scoring attempt must not re-pin the assessment"
        )

    def test_an_assessment_opened_after_the_promotion_pins_and_scores_on_the_successor(
        self, api: ApiClient
    ) -> None:
        """Pinning happens at open time, so the next order rides the new model.

        PRD: "Aegis achieves that by **pinning** both decisioning assets at the moment
        the assessment is opened rather than at the moment it is scored: the assessment
        permanently records `rule_pack_id` (the rule pack whose `status` is `ACTIVE`
        and whose effective window contains the current instant) and `risk_model_id`
        (the risk model whose `status` is `ACTIVE`). Neither field is a client input;
        both are computed by the server, and neither is ever rewritten."
        PRD: "`decision` and `decision_reason` are all written, and the pinned model's
        `scored_assessment_count` increments by one."

        Design: Difficulty/cross_entity_state_dependency/score_rejected_when_pinned_risk_model_retired_by_successor
        """
        env = build_scoring_env(api)
        open_assessment(api, env)
        successor = retire_active_model_by_promoting_successor(api)

        fresh = open_assessment(api, env)
        assert fresh["risk_model_id"] == successor["id"], (
            "the newly promoted model is the one that is ACTIVE at open time"
        )
        assert fresh["rule_pack_id"] == env.pack_id, (
            "the pack was untouched by the model promotion"
        )

        scored = score_assessment(api, fresh["id"])
        assert scored["state"] != AssessmentState.PENDING_SIGNALS
        assert scored["decision"] in (
            Decision.APPROVE,
            Decision.REVIEW,
            Decision.DECLINE,
        )

        assert read_risk_model(api, successor["id"])["scored_assessment_count"] == 1
        assert read_risk_model(api, env.model_id)["scored_assessment_count"] == 0, (
            "the retired model scored nothing, since its own assessment was refused"
        )


class TestPinnedRulePackMustStillBeActive:
    """Activating a successor pack retires the incumbent and strands its assessments."""

    def test_scoring_is_refused_when_the_pinned_pack_was_retired_by_a_successor(
        self, api: ApiClient
    ) -> None:
        """The pinned rule_pack_id is never repointed at the pack that replaced it.

        PRD: "If either pinned asset has left `ACTIVE` by the time scoring is requested,
        scoring is refused — `ERR_RULE_PACK_NOT_ACTIVE` when the pack has moved on,
        `ERR_RISK_MODEL_NOT_ACTIVE` when the model has. The assessment stays in
        `PENDING_SIGNALS` forever; there is no repair path."
        PRD: "It also cascades: every **other** pack currently `ACTIVE` whose
        `effective_until` is at or before the newly activated pack's `effective_from`
        moves `ACTIVE → RETIRED`, receives `retired_at` at the current instant, and has
        its `version` incremented."

        Design: Corner/state_machines/score_rejected_when_pinned_rule_pack_retired_by_successor
        """
        env = build_scoring_env(api)
        stranded = open_assessment(api, env)
        assert stranded["state"] == AssessmentState.PENDING_SIGNALS
        assert stranded["rule_pack_id"] == env.pack_id

        successor = retire_active_pack_by_activating_successor(
            api, SUCCESSOR_PACK_FROM, SUCCESSOR_PACK_UNTIL, version_label="P2"
        )
        assert successor["status"] == RulePackStatus.ACTIVE
        assert successor["id"] != env.pack_id
        assert read_rule_pack(api, env.pack_id)["status"] == RulePackStatus.RETIRED

        response = api.score_assessment(stranded["id"], CHECKOUT)
        validate_error(response, ApiErrorId.ERR_RULE_PACK_NOT_ACTIVE, 409)

        unscored = read_assessment(api, stranded["id"])
        assert unscored["state"] == AssessmentState.PENDING_SIGNALS
        assert unscored["rule_pack_id"] == env.pack_id, (
            "a refused scoring attempt must not silently re-pin the pack"
        )
        assert unscored["blended_score"] is None
        assert unscored["decision"] is None
        assert unscored["rule_score"] is None

        assert read_customer(api, env.customer_id)["approved_count"] == 0, (
            "the failed score moved no customer counter"
        )


class TestOpeningNeedsSomethingToPin:
    """With nothing to pin, the two missing-prerequisite errors arrive in order."""

    def test_the_missing_pack_is_reported_before_the_missing_model(
        self, api: ApiClient
    ) -> None:
        """A bare system reports the pack; once a pack is ACTIVE it reports the model.

        PRD: "Symmetrically, an assessment cannot be opened at all when there is nothing
        to pin: the absence of an `ACTIVE` rule pack covering the current instant yields
        `ERR_NO_ACTIVE_RULE_PACK`, and the absence of an `ACTIVE` risk model yields
        `ERR_NO_ACTIVE_RISK_MODEL`. Those two are checked in that order, so a system with
        neither reports the missing rule pack."
        PRD: "A successful activation sets `status` to `ACTIVE`, stamps `activated_at`
        with the current instant, records the acting engineer's `X-User-ID` as
        `activated_by_user_id`, and increments the pack's `version`."

        Design: Corner/errors/assessment_creation_without_active_pack_then_model_rejected
        """
        set_clock(api)
        customer = create_customer(api, email="noboot@example.com", home_country="US")
        device = create_device(api, tz_offset_minutes=0)
        address = create_address(api, country_code="US")

        def _open():
            return api.create_assessment(
                create_assessment_payload(
                    customer["id"],
                    device["id"],
                    address["id"],
                    amount_cents=STANDARD_ORDER_CENTS,
                    model_raw_probability=PROB_APPROVE_JUST_UNDER_REVIEW_FLOOR,
                ),
                CHECKOUT,
            )

        no_pack = _open()
        validate_error(no_pack, ApiErrorId.ERR_NO_ACTIVE_RULE_PACK, 422)
        assert no_pack.json()["data"]["error_id"] != (
            ApiErrorId.ERR_NO_ACTIVE_RISK_MODEL
        ), "with neither asset present the rule pack is reported first"

        pack = build_active_rule_pack(api, REFERENCE_RULES, version_label="P1")
        assert pack["status"] == RulePackStatus.ACTIVE

        no_model = _open()
        validate_error(no_model, ApiErrorId.ERR_NO_ACTIVE_RISK_MODEL, 422)

        _rows, meta = validate_paginated(
            api.list_assessments(CHECKOUT, params={"customer_id": customer["id"]})
        )
        assert meta["total_count"] == 0, "neither refused open created a row"
