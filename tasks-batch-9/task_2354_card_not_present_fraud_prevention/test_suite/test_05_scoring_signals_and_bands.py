"""Blending the rule component with the calibrated model, and landing a band.

Every case here drives the pipeline end to end: an order is opened against an
ACTIVE pack and an ACTIVE model, then scored, and the resulting numbers are
compared against the worked examples the specification pins. The velocity and
device signals the rule walk reads are exercised here too.
"""

from __future__ import annotations

from test_helpers import (
    ADMIN,
    CHECKOUT,
    ApiClient,
    ApiErrorId,
    assert_queued_case_defaults,
    assert_score,
    AssessmentState,
    BlendMode,
    build_scoring_env,
    CaseState,
    create_assessment_payload,
    create_customer,
    create_rule_payload,
    Decision,
    DecisionReason,
    DeviceReputation,
    DropRiskState,
    emulator_hard_decline_rule_payload,
    fast_checkout_rule_payload,
    FinalDisposition,
    find_case_for_assessment,
    get_success_data,
    list_cases_for_assessment,
    open_and_score,
    open_assessment,
    PACK_REVIEW_FLOOR,
    PROB_APPROVE_JUST_UNDER_REVIEW_FLOOR,
    PROB_REVIEW_EXACTLY_AT_REVIEW_FLOOR,
    PROB_REVIEW_MID_BAND,
    read_address,
    read_assessment,
    read_customer,
    read_device,
    read_risk_model,
    REFERENCE_RULES,
    retire_active_pack_by_activating_successor,
    RuleCode,
    score_assessment,
    set_clock,
    SignalFamily,
    STANDARD_ORDER_CENTS,
    validate_error,
)

#: The window the first pack owns, so that a successor can clear the freeze buffer.
FIRST_PACK_FROM = "2026-07-01T00:00:00Z"
FIRST_PACK_UNTIL = "2026-08-01T12:00:00Z"
#: A successor window that starts one second past the first pack's buffered end.
SECOND_PACK_FROM = "2026-08-01T13:00:01Z"
SECOND_PACK_UNTIL = "2027-01-01T00:00:00Z"
LATER_INSTANT = "2026-08-01T14:00:00Z"


class TestBlendModeDivergence:
    """The same order, judged by two packs that differ only in ``blend_mode``."""

    def test_weighted_pack_approves_where_a_rule_dominant_pack_sends_to_review(
        self, api: ApiClient
    ) -> None:
        """One order shape produces 39.95 under WEIGHTED and 48.25 under RULE_DOMINANT.

        PRD: "Under `WEIGHTED`, the blended score is the pack's `rule_weight`
        multiplied by `rule_score`, plus the pack's `model_weight` multiplied by
        `model_points`, with **one** rounding step applied to the whole weighted
        sum."
        PRD: "Under `RULE_DOMINANT`, the model contribution is damped and the sum
        is then uplifted, in **two separately rounded steps**."

        Design: Difficulty/dual_variant_calc/blended_score_weighted_vs_rule_dominant_diverge
        """
        env = build_scoring_env(
            api,
            effective_from=FIRST_PACK_FROM,
            effective_until=FIRST_PACK_UNTIL,
        )
        weighted = open_and_score(
            api,
            env,
            amount_cents=STANDARD_ORDER_CENTS,
            model_raw_probability=PROB_APPROVE_JUST_UNDER_REVIEW_FLOOR,
        )
        assert_score(weighted["rule_score"], 20, "rule_score under the WEIGHTED pack")
        assert_score(weighted["model_points"], 53.25, "model_points")
        assert_score(weighted["blended_score"], 39.95, "WEIGHTED blended_score")
        assert weighted["decision"] == Decision.APPROVE, (
            "39.95 sits below the 40.00 review floor, so the order is approved"
        )
        assert weighted["state"] == AssessmentState.DECIDED_APPROVE

        set_clock(api, LATER_INSTANT)
        successor = retire_active_pack_by_activating_successor(
            api,
            effective_from=SECOND_PACK_FROM,
            effective_until=SECOND_PACK_UNTIL,
            rules=REFERENCE_RULES,
            blend_mode=BlendMode.RULE_DOMINANT,
        )
        env.pack = successor

        rule_dominant = open_and_score(
            api,
            env,
            amount_cents=STANDARD_ORDER_CENTS,
            model_raw_probability=PROB_APPROVE_JUST_UNDER_REVIEW_FLOOR,
        )
        assert rule_dominant["rule_pack_id"] == successor["id"], (
            "the second order must be judged by the RULE_DOMINANT pack"
        )
        assert_score(rule_dominant["rule_score"], 20, "rule_score")
        assert_score(rule_dominant["model_points"], 53.25, "model_points")
        assert_score(
            rule_dominant["blended_score"], 48.25, "RULE_DOMINANT blended_score"
        )
        assert rule_dominant["decision"] == Decision.REVIEW, (
            "48.25 reaches the 40.00 review floor without reaching the decline floor"
        )
        assert rule_dominant["state"] == AssessmentState.IN_REVIEW

    def test_divergence_comes_only_from_the_blend_and_not_from_the_components(
        self, api: ApiClient
    ) -> None:
        """Both packs see the same rule_score and model_points, 8.30 points apart.

        PRD: "`model_points` is calibrated as described in §3.3, and
        `blended_score` combines the two components according to the pinned pack's
        `blend_mode`."
        PRD: "taken when the band resolution yields `REVIEW`, meaning the score
        reached the review floor and no band-stage exception applied."

        Design: Difficulty/dual_variant_calc/blended_score_weighted_vs_rule_dominant_diverge
        """
        env = build_scoring_env(
            api,
            effective_from=FIRST_PACK_FROM,
            effective_until=FIRST_PACK_UNTIL,
        )
        weighted = open_and_score(
            api,
            env,
            amount_cents=STANDARD_ORDER_CENTS,
            model_raw_probability=PROB_APPROVE_JUST_UNDER_REVIEW_FLOOR,
        )
        assert find_case_for_assessment(api, weighted["id"]) is None, (
            "an approved order creates no review case"
        )

        set_clock(api, LATER_INSTANT)
        env.pack = retire_active_pack_by_activating_successor(
            api,
            effective_from=SECOND_PACK_FROM,
            effective_until=SECOND_PACK_UNTIL,
            rules=REFERENCE_RULES,
            blend_mode=BlendMode.RULE_DOMINANT,
        )
        rule_dominant = open_and_score(
            api,
            env,
            amount_cents=STANDARD_ORDER_CENTS,
            model_raw_probability=PROB_APPROVE_JUST_UNDER_REVIEW_FLOOR,
        )

        assert rule_dominant["rule_score"] == weighted["rule_score"], (
            "the rule walk is unaffected by the blend mode"
        )
        assert_score(
            rule_dominant["model_points"],
            float(weighted["model_points"]),
            "model_points is unaffected by the blend mode",
        )
        assert_score(
            float(rule_dominant["blended_score"]) - float(weighted["blended_score"]),
            8.30,
            "the gap between the RULE_DOMINANT and WEIGHTED blends",
        )
        case = find_case_for_assessment(api, rule_dominant["id"])
        assert case is not None, "the review branch creates a review case"
        assert_queued_case_defaults(case)


class TestRuleDominantNestedRounding:
    """The RULE_DOMINANT blend rounds twice, and the order of the two is pinned."""

    def test_inner_damped_term_is_rounded_to_one_decimal_before_the_uplift(
        self, api: ApiClient
    ) -> None:
        """0.35 x 53.25 rounds to 18.6 first, so the blend is 48.25 and not 48.30.

        PRD: "The nesting order is part of the contract: with the same inputs, the
        inner term is 0.35 × 53.25 = 18.6375 rounded to 18.6, the uplift gives
        (20 + 18.6) × 1.25 = 48.25, and the blended score is 48.25 — whereas
        collapsing the two steps into one would give 48.30, which is wrong."

        Design: Difficulty/combinatorial_formula/rule_dominant_nested_rounding_order_pinned
        """
        env = build_scoring_env(api, blend_mode=BlendMode.RULE_DOMINANT)
        scored = open_and_score(
            api,
            env,
            amount_cents=STANDARD_ORDER_CENTS,
            model_raw_probability=PROB_APPROVE_JUST_UNDER_REVIEW_FLOOR,
        )
        assert_score(scored["rule_score"], 20, "rule_score")
        assert_score(scored["model_points"], 53.25, "model_points")
        assert_score(scored["blended_score"], 48.25, "blended_score")
        assert float(scored["blended_score"]) != 48.30, (
            "48.30 is the value produced by collapsing the two rounding steps"
        )
        assert scored["decision"] == Decision.REVIEW
        assert scored["decision_reason"] == DecisionReason.SCORE_BAND

    def test_uplifted_sum_is_rounded_half_up_to_two_decimals(
        self, api: ApiClient
    ) -> None:
        """(20 + 24.5) x 1.25 is 55.625, which rounds half up to 55.63.

        PRD: "Second, that inner term is added to `rule_score`, the sum is
        multiplied by 1.25, and the result is rounded half up to two decimal
        places."
        PRD: "Scores and rates are decimals with pinned precision. Unless a rule
        explicitly says otherwise, rounding is **round half up**."

        Design: Difficulty/combinatorial_formula/rule_dominant_nested_rounding_order_pinned
        """
        env = build_scoring_env(api, blend_mode=BlendMode.RULE_DOMINANT)
        scored = open_and_score(
            api,
            env,
            amount_cents=STANDARD_ORDER_CENTS,
            model_raw_probability=PROB_REVIEW_MID_BAND,
        )
        assert_score(scored["model_points"], 70.00, "model_points")
        assert_score(scored["blended_score"], 55.63, "blended_score")
        assert scored["state"] == AssessmentState.IN_REVIEW


class TestHardDeclineShortCircuit:
    """A firing hard-decline rule stops the walk and forces the decline branch."""

    def test_rules_after_the_hard_decline_are_never_evaluated(
        self, api: ApiClient
    ) -> None:
        """DEV_EMULATOR at order 10 keeps BEH_FAST_CHECKOUT at order 20 out of the walk.

        PRD: "The walk **short-circuits** on the first firing rule whose
        `hard_decline` is true: rules after that point are never evaluated and
        never appear in `triggered_rule_codes`."
        PRD: "From the walk: `rule_score` is the sum of `points` over the fired
        rules, capped at 100; `triggered_rule_codes` lists the fired codes in
        evaluation order; `hard_decline_triggered` is true exactly when some fired
        rule had `hard_decline` true; and `primary_signal_family` is the
        `signal_family` of the fired rule with the highest `points`, with ties
        broken in favour of the **lowest** `evaluation_order`, or `MODEL` when no
        rule fired at all."

        Design: Difficulty/combinatorial_formula/hard_decline_short_circuit_evaluation_order_pinned
        """
        env = build_scoring_env(
            api,
            rules=(
                emulator_hard_decline_rule_payload(points=45, evaluation_order=10),
                fast_checkout_rule_payload(points=30, evaluation_order=20),
            ),
            device_overrides={"emulator_flag": True},
        )
        scored = open_and_score(
            api,
            env,
            amount_cents=STANDARD_ORDER_CENTS,
            model_raw_probability=PROB_APPROVE_JUST_UNDER_REVIEW_FLOOR,
        )
        assert scored["triggered_rule_codes"] == [RuleCode.DEV_EMULATOR], (
            "the behavioural rule sitting after the hard decline must not appear"
        )
        assert scored["rule_score"] == 45, (
            "only the hard-decline rule's 45 points are summed, not 45 + 30"
        )
        assert scored["hard_decline_triggered"] is True
        assert scored["primary_signal_family"] == SignalFamily.DEVICE

    def test_hard_decline_outranks_the_band_the_score_would_have_landed_in(
        self, api: ApiClient
    ) -> None:
        """A blend of 49.95 sits in the review band, yet the order is declined.

        PRD: "1. `hard_decline_triggered` is true → `decision` `DECLINE`,
        `decision_reason` `HARD_RULE`. No policy exception of any kind can rescue a
        hard decline."
        PRD: "It increments the customer's `declined_count` by one and their
        `version` by one, and leaves `lifetime_net_approved_cents` unchanged."

        Design: Difficulty/combinatorial_formula/hard_decline_short_circuit_evaluation_order_pinned
        """
        env = build_scoring_env(
            api,
            rules=(
                emulator_hard_decline_rule_payload(points=45, evaluation_order=10),
                fast_checkout_rule_payload(points=30, evaluation_order=20),
            ),
            device_overrides={"emulator_flag": True},
        )
        scored = open_and_score(
            api,
            env,
            amount_cents=STANDARD_ORDER_CENTS,
            model_raw_probability=PROB_APPROVE_JUST_UNDER_REVIEW_FLOOR,
        )
        assert_score(scored["blended_score"], 49.95, "blended_score")
        assert float(scored["blended_score"]) >= PACK_REVIEW_FLOOR, (
            "the blend does reach the review floor, which is what makes the "
            "hard-decline precedence observable"
        )
        assert scored["decision"] == Decision.DECLINE
        assert scored["decision_reason"] == DecisionReason.HARD_RULE
        assert scored["state"] == AssessmentState.DECIDED_DECLINE
        assert scored["final_disposition"] == FinalDisposition.DECLINED
        assert find_case_for_assessment(api, scored["id"]) is None, (
            "the decline branch creates no review case"
        )

        customer = read_customer(api, env.customer_id)
        assert customer["declined_count"] == 1
        assert customer["lifetime_net_approved_cents"] == 0


class TestReviewFloorBoundary:
    """The review-floor comparison is inclusive, to the stored second decimal."""

    def test_score_exactly_at_the_review_floor_lands_in_review(
        self, api: ApiClient
    ) -> None:
        """A blend of exactly 40.00 takes the review branch and queues a case.

        PRD: "3. `blended_score` is greater than or equal to the pack's
        `review_floor_score` (again inclusive, so a score exactly equal to
        `review_floor_score` lands here) → if an eligible band-stage exception
        exists, `decision` is `APPROVE` with `decision_reason` `POLICY_EXCEPTION`
        and `applied_exception_id` set to that exception; otherwise `decision` is
        `REVIEW` with `decision_reason` `SCORE_BAND`."
        PRD: "There is **no ledger movement** in this branch:
        `lifetime_net_approved_cents`, `approved_count` and `declined_count` are
        all left untouched, because nothing has been decided commercially yet."

        Design: Difficulty/boundary_precision_check/blended_score_exactly_at_review_floor_lands_in_review
        """
        env = build_scoring_env(api)
        scored = open_and_score(
            api,
            env,
            amount_cents=STANDARD_ORDER_CENTS,
            model_raw_probability=PROB_REVIEW_EXACTLY_AT_REVIEW_FLOOR,
        )
        assert_score(scored["model_points"], 53.34, "model_points")
        assert_score(scored["blended_score"], 40.00, "blended_score")
        assert float(scored["blended_score"]) == float(
            env.pack["review_floor_score"]
        ), "the blend must land exactly on the pack's review floor"
        assert scored["decision"] == Decision.REVIEW
        assert scored["decision_reason"] == DecisionReason.SCORE_BAND
        assert scored["state"] == AssessmentState.IN_REVIEW

        rows, meta = list_cases_for_assessment(api, scored["id"])
        assert meta["total_count"] == 1, "the review branch creates exactly one case"
        case = rows[0]
        assert case["state"] == CaseState.QUEUED
        assert_score(case["priority_score"], 22.00, "case.priority_score")

        customer = read_customer(api, env.customer_id)
        assert customer["approved_count"] == 0
        assert customer["declined_count"] == 0
        assert customer["lifetime_net_approved_cents"] == 0

    def test_score_one_cent_of_a_point_below_the_review_floor_approves(
        self, api: ApiClient
    ) -> None:
        """A blend of 39.95 misses the floor and is approved by the score band.

        PRD: "3. `blended_score` is greater than or equal to the pack's
        `review_floor_score` (again inclusive, so a score exactly equal to
        `review_floor_score` lands here)"
        PRD: "4. Otherwise → `decision` `APPROVE`, `decision_reason` `SCORE_BAND`."
        PRD: "Band comparisons use the stored two-decimal `blended_score` exactly
        as stored, with no re-derivation and no tolerance."

        Design: Difficulty/boundary_precision_check/blended_score_exactly_at_review_floor_lands_in_review
        """
        env = build_scoring_env(api)
        scored = open_and_score(
            api,
            env,
            amount_cents=STANDARD_ORDER_CENTS,
            model_raw_probability=PROB_APPROVE_JUST_UNDER_REVIEW_FLOOR,
        )
        assert_score(scored["blended_score"], 39.95, "blended_score")
        assert scored["decision"] == Decision.APPROVE
        assert scored["decision_reason"] == DecisionReason.SCORE_BAND
        assert scored["state"] == AssessmentState.DECIDED_APPROVE
        assert scored["final_disposition"] == FinalDisposition.APPROVED
        assert find_case_for_assessment(api, scored["id"]) is None, (
            "an order below the review floor never reaches the queue"
        )

        customer = read_customer(api, env.customer_id)
        assert customer["approved_count"] == 1
        assert customer["lifetime_net_approved_cents"] == STANDARD_ORDER_CENTS


class TestScoringIsGuardedByItsOwnIdempotencyCheck:
    """A retried score call replays none of the pipeline's side effects."""

    def test_a_second_score_on_a_decided_order_is_refused_and_replays_nothing(
        self, api: ApiClient
    ) -> None:
        """The already-scored gate is the idempotency guard, so no counter moves twice.

        PRD: "the assessment must still be in `PENDING_SIGNALS`, or the request is
        `ERR_ASSESSMENT_ALREADY_SCORED` — this is also the idempotency guard, so a
        second scoring attempt on the same assessment always fails here"
        PRD: "Whichever branch is taken, `velocity_*` fields, `rule_score`,
        `model_points`, `blended_score`, `triggered_rule_codes`,
        `hard_decline_triggered`, `primary_signal_family`, `decision` and
        `decision_reason` are all written, and the pinned model's
        `scored_assessment_count` increments by one."

        Design: Corner/state_machines/assessment_scored_twice_rejected_without_double_ledger_movement
        """
        env = build_scoring_env(api)
        scored = open_and_score(
            api,
            env,
            amount_cents=STANDARD_ORDER_CENTS,
            model_raw_probability=PROB_APPROVE_JUST_UNDER_REVIEW_FLOOR,
        )
        assert scored["state"] == AssessmentState.DECIDED_APPROVE

        response = api.score_assessment(scored["id"], CHECKOUT)
        validate_error(response, ApiErrorId.ERR_ASSESSMENT_ALREADY_SCORED, 409)

        unchanged = read_assessment(api, scored["id"])
        assert unchanged["state"] == AssessmentState.DECIDED_APPROVE
        assert_score(unchanged["blended_score"], 39.95, "blended_score")
        assert unchanged["decision"] == Decision.APPROVE

        customer = read_customer(api, env.customer_id)
        assert customer["approved_count"] == 1, "the approve branch ran exactly once"
        assert customer["lifetime_net_approved_cents"] == STANDARD_ORDER_CENTS

        assert read_risk_model(api, env.model_id)["scored_assessment_count"] == 1, (
            "the pinned model counts one scoring, not two"
        )
        assert read_device(api, env.device_id)["approved_use_count"] == 1


class TestScoringSideEffectsLandInsideTheSameRequest:
    """The score response is already authoritative, and so is every read after it."""

    def test_the_second_approval_flips_the_flag_and_every_counter_in_one_request(
        self, api: ApiClient
    ) -> None:
        """No denormalised counter lags: one score, then one read each, all settled.

        PRD: "It sets `final_disposition` to `APPROVED`, stamps `decided_at` with the
        current instant, and freezes `good_customer_at_decision` to the customer's
        `good_customer_flag` as it stands at that instant — a snapshot retained for
        insult-rate audits and never revised."
        PRD: "Because the recomputation happens after the counters move, the approval
        that carries an account to its second approved order flips the flag inside that
        very request."

        Design: Corner/consistency_model/scoring_side_effects_are_visible_in_the_same_response
        """
        env = build_scoring_env(api)

        first = open_and_score(
            api,
            env,
            amount_cents=STANDARD_ORDER_CENTS,
            model_raw_probability=PROB_APPROVE_JUST_UNDER_REVIEW_FLOOR,
        )
        assert first["state"] == AssessmentState.DECIDED_APPROVE
        assert first["good_customer_at_decision"] is False

        second = open_and_score(
            api,
            env,
            amount_cents=STANDARD_ORDER_CENTS,
            model_raw_probability=PROB_APPROVE_JUST_UNDER_REVIEW_FLOOR,
        )
        assert second["state"] == AssessmentState.DECIDED_APPROVE, (
            "the score response body already carries the terminal state"
        )
        assert second["rule_score"] == 20
        assert_score(second["model_points"], 53.25, "model_points")
        assert_score(second["blended_score"], 39.95, "blended_score")
        assert second["decision"] == Decision.APPROVE
        assert second["decision_reason"] == DecisionReason.SCORE_BAND
        assert second["final_disposition"] == FinalDisposition.APPROVED
        assert second["decided_at"] is not None
        assert second["good_customer_at_decision"] is False, (
            "the snapshot is frozen before this request's own counters move"
        )

        customer = read_customer(api, env.customer_id)
        assert customer["approved_count"] == 2
        assert customer["lifetime_net_approved_cents"] == 2 * STANDARD_ORDER_CENTS
        assert customer["good_customer_flag"] is True, (
            "the second approval flips the flag inside that very request"
        )

        device = read_device(api, env.device_id, CHECKOUT)
        assert device["approved_use_count"] == 2
        assert device["distinct_customer_count"] == 1
        assert device["fraud_confirmed_count"] == 0
        assert device["reputation"] == DeviceReputation.NEW, (
            "TRUSTED still wants a third approval"
        )

        address = read_address(api, env.address_id, CHECKOUT)
        assert address["approved_use_count"] == 2
        assert address["distinct_customer_count"] == 1
        assert address["promo_redemption_count"] == 0
        assert address["drop_risk_state"] == DropRiskState.CLEAN
        assert_score(address["reshipper_confidence"], 0.20, "reshipper_confidence")

#: The velocity pack holds nothing but the customer-hour rule, so no behavioural
#: or identity rule can contaminate ``rule_score``.
VELOCITY_ONLY_RULES = (
    create_rule_payload(RuleCode.VEL_CUSTOMER_1H, points=30, evaluation_order=10),
)


class TestCustomerHourVelocityThreshold:
    """The customer-hour rule needs three *prior* siblings, and state is not filtered."""

    def test_the_third_checkout_stays_approved_and_the_fourth_crosses_into_review(
        self, api: ApiClient
    ) -> None:
        """Two unscored siblings leave 31.95; a third sibling lifts the score to 43.95.

        PRD: "`velocity_customer_assessment_count_1h` is the number of assessments
        belonging to the same customer, other than the one being scored, whose
        `created_at` falls within the hour ending now — that is, at or after one hour
        (3,600 seconds) before now and at or before now. State is deliberately **not**
        filtered: abandoned attempts still sitting in `PENDING_SIGNALS` count as
        velocity, because a burst of attempts is the signal."
        PRD: "`VEL_CUSTOMER_1H` fires when `velocity_customer_assessment_count_1h` is at
        least 3."

        Design: Corner/calculations/velocity_window_threshold_fires_only_at_the_third_prior_attempt
        """
        env = build_scoring_env(api, rules=VELOCITY_ONLY_RULES)

        # Two attempts are opened and deliberately abandoned in PENDING_SIGNALS.
        open_assessment(
            api,
            env,
            amount_cents=STANDARD_ORDER_CENTS,
            model_raw_probability=PROB_APPROVE_JUST_UNDER_REVIEW_FLOOR,
        )
        open_assessment(
            api,
            env,
            amount_cents=STANDARD_ORDER_CENTS,
            model_raw_probability=PROB_APPROVE_JUST_UNDER_REVIEW_FLOOR,
        )

        third = open_and_score(
            api,
            env,
            amount_cents=STANDARD_ORDER_CENTS,
            model_raw_probability=PROB_APPROVE_JUST_UNDER_REVIEW_FLOOR,
        )
        assert third["velocity_customer_assessment_count_1h"] == 2, (
            "the two abandoned attempts count, and the assessment excludes itself"
        )
        assert third["triggered_rule_codes"] == []
        assert third["rule_score"] == 0
        assert_score(third["model_points"], 53.25, "model_points")
        assert_score(third["blended_score"], 31.95, "blended_score")
        assert third["decision"] == Decision.APPROVE
        assert third["decision_reason"] == DecisionReason.SCORE_BAND
        assert third["primary_signal_family"] == SignalFamily.MODEL, (
            "no rule fired, so the primary family falls back to MODEL"
        )
        assert find_case_for_assessment(api, third["id"]) is None

        fourth = open_and_score(
            api,
            env,
            amount_cents=STANDARD_ORDER_CENTS,
            model_raw_probability=PROB_APPROVE_JUST_UNDER_REVIEW_FLOOR,
        )
        assert fourth["velocity_customer_assessment_count_1h"] == 3
        assert fourth["triggered_rule_codes"] == [RuleCode.VEL_CUSTOMER_1H]
        assert fourth["rule_score"] == 30
        assert_score(fourth["blended_score"], 43.95, "blended_score")
        assert fourth["decision"] == Decision.REVIEW
        assert fourth["decision_reason"] == DecisionReason.SCORE_BAND
        assert fourth["primary_signal_family"] == SignalFamily.VELOCITY

        rows, meta = list_cases_for_assessment(api, fourth["id"])
        assert meta["total_count"] == 1
        case = rows[0]
        assert case["state"] == CaseState.QUEUED
        assert case["primary_signal_family"] == SignalFamily.VELOCITY
        assert_score(case["priority_score"], 23.98, "priority_score")


class TestDeviceReputationLadderIsOrdered:
    """The ladder takes its first matching clause, so SUSPECT outranks TRUSTED."""

    def test_a_third_distinct_customer_demotes_a_trusted_device_to_suspect(
        self, api: ApiClient
    ) -> None:
        """Three approvals reach TRUSTED; a third distinct customer forces SUSPECT.

        PRD: "From those, `reputation` is resolved by taking the **first** matching
        clause of this pinned ladder:"
        PRD: "`fraud_confirmed_count` of exactly 1, or `distinct_customer_count` of 3 or
        more, or `emulator_flag` true → `SUSPECT`."

        Design: Corner/calculations/device_reputation_suspect_beats_trusted_in_pinned_order
        """
        env = build_scoring_env(api)
        second_customer = create_customer(api, email="rep-c2@example.com")
        third_customer = create_customer(api, email="rep-c3@example.com")

        for _ in range(3):
            open_and_score(
                api,
                env,
                amount_cents=STANDARD_ORDER_CENTS,
                model_raw_probability=PROB_APPROVE_JUST_UNDER_REVIEW_FLOOR,
            )

        trusted = read_device(api, env.device_id, ADMIN)
        assert trusted["approved_use_count"] == 3
        assert trusted["distinct_customer_count"] == 1
        assert trusted["fraud_confirmed_count"] == 0
        assert trusted["reputation"] == DeviceReputation.TRUSTED

        self._score_on_shared_device(api, env, second_customer["id"])
        still_trusted = read_device(api, env.device_id, ADMIN)
        assert still_trusted["distinct_customer_count"] == 2
        assert still_trusted["approved_use_count"] == 4
        assert still_trusted["reputation"] == DeviceReputation.TRUSTED, (
            "two distinct customers is still at or under the TRUSTED limit"
        )

        last = self._score_on_shared_device(api, env, third_customer["id"])
        demoted = read_device(api, env.device_id, ADMIN)
        assert demoted["distinct_customer_count"] == 3
        assert demoted["approved_use_count"] == 5
        assert demoted["fraud_confirmed_count"] == 0
        assert demoted["reputation"] == DeviceReputation.SUSPECT, (
            "the distinct-customer clause is tested before the TRUSTED clause"
        )

        assert_score(last["blended_score"], 39.95, "blended_score")
        assert last["decision"] == Decision.APPROVE, (
            "the recompute happens after this assessment's own decision"
        )
        assert last["triggered_rule_codes"] == [RuleCode.BEH_FAST_CHECKOUT], (
            "the pack holds no device rule, so the demotion cannot feed back"
        )

    @staticmethod
    def _score_on_shared_device(api: ApiClient, env, customer_id: str) -> dict:
        """Score an order for another customer on the same device and address."""
        opened = get_success_data(
            api.create_assessment(
                create_assessment_payload(
                    customer_id,
                    env.device_id,
                    env.address_id,
                    amount_cents=STANDARD_ORDER_CENTS,
                    model_raw_probability=PROB_APPROVE_JUST_UNDER_REVIEW_FLOOR,
                ),
                CHECKOUT,
            )
        )
        return score_assessment(api, opened["id"])
