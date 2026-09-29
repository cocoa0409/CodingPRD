"""Publishing decision policy, and reading back how well it performed.

A pack is drafted, shaped, activated against the freeze buffer and then
measured through its false-positive report.
"""

from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    ADMIN,
    CHECKOUT,
    ENGINEER,
    ENGINEER_APPROVER,
    ApiClient,
    ApiErrorId,
    assert_performance_report,
    assert_rate,
    assert_score,
    AssessmentState,
    build_active_rule_pack,
    build_approved_assessment,
    build_draft_rule_pack,
    build_lost_chargeback,
    build_scoring_env,
    CLOCK_EPOCH,
    Cohort,
    create_device_payload,
    create_rule_dominant_pack_payload,
    create_rule_pack_payload,
    create_rule_payload,
    Decision,
    DecisionReason,
    draft_rule_pack,
    emulator_hard_decline_rule_payload,
    FinalDisposition,
    get_success_data,
    open_and_score,
    OutcomeLabel,
    plus_seconds,
    PROB_DECLINE_EXACTLY_AT_DECLINE_FLOOR,
    read_assessment,
    read_customer,
    read_rule_pack,
    REFERENCE_RULES,
    RULE_PACK_ACTIVATION_FREEZE_SECONDS,
    RuleCode,
    RulePackStatus,
    ScoringEnv,
    set_clock,
    SignalFamily,
    SMALL_ORDER_CENTS,
    validate_error,
    validate_paginated,
    validate_success,
)

INCUMBENT_FROM = "2026-07-01T00:00:00Z"
INCUMBENT_UNTIL = "2026-08-01T12:00:00Z"
FAR_FUTURE = "2027-01-01T00:00:00Z"

#: One hash, registered twice.
SHARED_DEVICE_HASH = "dev-uniq-001"

#: One second short of the hour of slack the freeze buffer demands.
GAP_BELOW_BUFFER = plus_seconds(
    INCUMBENT_UNTIL, RULE_PACK_ACTIVATION_FREEZE_SECONDS - 1
)
#: Exactly the buffered instant, which the inequality accepts.
GAP_AT_BUFFER = plus_seconds(INCUMBENT_UNTIL, RULE_PACK_ACTIVATION_FREEZE_SECONDS)


class TestActivationFreezeBuffer:
    """A successor window is measured against the incumbent's inflated window."""

    def test_a_successor_starting_inside_the_buffer_cannot_be_activated(
        self, api: ApiClient
    ) -> None:
        """A gap of 3,599 seconds collides with the incumbent's inflated window.

        PRD: "Concretely, the candidate pack's window is inflated by one hour (3,600
        seconds) at **both** ends, and that inflated window is compared against the
        un-inflated window of every pack whose `status` is `ACTIVE` or `RETIRED`."
        PRD: "the window must clear the activation freeze buffer
        (`ERR_RULE_PACK_WINDOW_OVERLAP`)"

        Design: Difficulty/resource_temporal_overlap/rule_pack_buffer_inflated_window_rejects_gap_below_freeze
        """
        set_clock(api)
        incumbent = build_active_rule_pack(
            api,
            REFERENCE_RULES,
            effective_from=INCUMBENT_FROM,
            effective_until=INCUMBENT_UNTIL,
        )
        assert incumbent["status"] == RulePackStatus.ACTIVE

        candidate = build_draft_rule_pack(
            api,
            REFERENCE_RULES,
            effective_from=GAP_BELOW_BUFFER,
            effective_until=FAR_FUTURE,
        )
        response = api.activate_rule_pack(candidate["id"], ENGINEER_APPROVER)
        validate_error(response, ApiErrorId.ERR_RULE_PACK_WINDOW_OVERLAP, 409)

        rejected = read_rule_pack(api, candidate["id"])
        assert rejected["status"] == RulePackStatus.DRAFT
        assert rejected["activated_at"] is None
        assert rejected["activated_by_user_id"] is None
        assert read_rule_pack(api, incumbent["id"])["status"] == RulePackStatus.ACTIVE

    def test_a_successor_starting_exactly_one_hour_later_is_activated(
        self, api: ApiClient
    ) -> None:
        """A gap of exactly 3,600 seconds satisfies the buffer inequality.

        PRD: "The candidate is accepted only if it lies entirely clear of each such
        pack — that is, only if the candidate's `effective_until` plus one hour is at
        or before the other pack's `effective_from`, or the other pack's
        `effective_until` plus one hour is at or before the candidate's
        `effective_from`."
        PRD: "It also cascades: every **other** pack currently `ACTIVE` whose
        `effective_until` is at or before the newly activated pack's `effective_from`
        moves `ACTIVE → RETIRED`, receives `retired_at` at the current instant, and
        has its `version` incremented."

        Design: Difficulty/resource_temporal_overlap/rule_pack_buffer_inflated_window_rejects_gap_below_freeze
        """
        set_clock(api)
        incumbent = build_active_rule_pack(
            api,
            REFERENCE_RULES,
            effective_from=INCUMBENT_FROM,
            effective_until=INCUMBENT_UNTIL,
        )
        successor = build_active_rule_pack(
            api,
            REFERENCE_RULES,
            effective_from=GAP_AT_BUFFER,
            effective_until=FAR_FUTURE,
        )

        assert successor["status"] == RulePackStatus.ACTIVE
        assert successor["activated_at"] is not None
        assert successor["activated_by_user_id"] is not None

        retired = read_rule_pack(api, incumbent["id"])
        assert retired["status"] == RulePackStatus.RETIRED
        assert retired["retired_at"] is not None
        assert int(retired["version"]) > int(incumbent["version"])

        rows, meta = validate_paginated(
            api.list_rule_packs(ENGINEER, params={"status": RulePackStatus.ACTIVE})
        )
        assert meta["total_count"] == 1, (
            "retiring the incumbent leaves the successor as the only ACTIVE pack"
        )
        assert rows[0]["id"] == successor["id"]


class TestRuleFamilyMustMatchTheCodePrefix:
    """A rule's declared family is pinned by the family its code belongs to."""

    def test_declaring_a_behavioural_code_as_a_device_rule_is_refused(
        self, api: ApiClient
    ) -> None:
        """The mismatch leaves rule_count at 0; the coherent rule lifts it to 1.

        PRD: "The declared `signal_family` must be the family the code actually belongs
        to: `DEV_` codes belong to `DEVICE`, `BEH_` codes to `BEHAVIORAL`, `VEL_` codes
        to `VELOCITY`, `ID_` codes to `IDENTITY`, `ADDR_` codes to `ADDRESS` and `PROMO_`
        codes to `PROMO`; a mismatch is `ERR_RULE_FAMILY_MISMATCH`."
        PRD: "Each accepted rule increments the pack's `rule_count` by one."

        Design: Corner/validations/rule_signal_family_must_match_the_code_prefix
        """
        set_clock(api)
        pack = draft_rule_pack(api, version_label="P-fam")
        assert pack["rule_count"] == 0

        mismatched = api.create_rule(
            pack["id"],
            create_rule_payload(
                RuleCode.BEH_FAST_CHECKOUT,
                points=20,
                evaluation_order=10,
                signal_family=SignalFamily.DEVICE,
            ),
            ENGINEER,
        )
        validate_error(mismatched, ApiErrorId.ERR_RULE_FAMILY_MISMATCH, 422)
        assert read_rule_pack(api, pack["id"])["rule_count"] == 0, (
            "a rejected rule does not count against the pack"
        )

        accepted = validate_success(
            api.create_rule(
                pack["id"],
                create_rule_payload(
                    RuleCode.BEH_FAST_CHECKOUT, points=20, evaluation_order=10
                ),
                ENGINEER,
            ),
            201,
        )
        assert accepted["signal_family"] == SignalFamily.BEHAVIORAL
        assert read_rule_pack(api, pack["id"])["rule_count"] == 1

        _rows, meta = validate_paginated(api.list_rules(pack["id"], ENGINEER))
        assert meta["total_count"] == 1


class TestUniquenessScopes:
    """A device hash is unique globally; a rule code is unique only inside its pack."""

    def test_a_repeated_device_hash_is_refused_but_a_repeated_code_needs_a_new_pack(
        self, api: ApiClient
    ) -> None:
        """The same code is a duplicate in one pack and perfectly legal in another.

        PRD: "A device fingerprint is registered by the checkout service or an
        administrator with a `device_hash`, which must be globally unique across device
        profiles — a second registration of the same hash is
        `ERR_DUPLICATE_DEVICE_HASH`"
        PRD: "each `code` may appear at most once in a given pack — a repeat is
        `ERR_DUPLICATE_RULE_CODE`."

        Design: Corner/endpoints/uniqueness_on_device_hash_and_rule_code_rejected
        """
        set_clock(api)
        first_device = validate_success(
            api.create_device(
                create_device_payload(device_hash=SHARED_DEVICE_HASH), CHECKOUT
            ),
            201,
        )
        duplicate_device = api.create_device(
            create_device_payload(device_hash=SHARED_DEVICE_HASH), CHECKOUT
        )
        validate_error(duplicate_device, ApiErrorId.ERR_DUPLICATE_DEVICE_HASH, 409)

        _device_rows, device_meta = validate_paginated(api.list_devices(ADMIN))
        assert device_meta["total_count"] == 1
        assert _device_rows[0]["id"] == first_device["id"]

        first_pack = build_draft_rule_pack(
            api,
            REFERENCE_RULES,
            version_label="PA",
            effective_from=INCUMBENT_FROM,
            effective_until=INCUMBENT_UNTIL,
        )
        assert read_rule_pack(api, first_pack["id"])["rule_count"] == 1

        repeat_in_same_pack = api.create_rule(
            first_pack["id"],
            create_rule_payload(
                RuleCode.BEH_FAST_CHECKOUT, points=25, evaluation_order=20
            ),
            ENGINEER,
        )
        validate_error(repeat_in_same_pack, ApiErrorId.ERR_DUPLICATE_RULE_CODE, 409)
        assert read_rule_pack(api, first_pack["id"])["rule_count"] == 1

        second_pack = build_draft_rule_pack(
            api,
            (),
            version_label="PB",
            effective_from=GAP_AT_BUFFER,
            effective_until=FAR_FUTURE,
        )
        accepted = validate_success(
            api.create_rule(
                second_pack["id"],
                create_rule_payload(
                    RuleCode.BEH_FAST_CHECKOUT, points=20, evaluation_order=10
                ),
                ENGINEER,
            ),
            201,
        )
        assert accepted["code"] == RuleCode.BEH_FAST_CHECKOUT
        assert accepted["rule_pack_id"] == second_pack["id"], (
            "the same code in a different pack is not a duplicate"
        )
        assert read_rule_pack(api, second_pack["id"])["rule_count"] == 1


class TestAnActivePackIsFrozen:
    """Once activated, a pack accepts neither new rules nor a second activation."""

    def test_adding_a_rule_or_reactivating_an_active_pack_hits_the_same_gate(
        self, api: ApiClient
    ) -> None:
        """The DRAFT gate guards both the content path and the lifecycle path.

        PRD: "Rules are added to a pack only while it is still `DRAFT`; attempting to add
        one to an activated or retired pack is `ERR_RULE_PACK_NOT_DRAFT`."
        PRD: "On this path the checks run in the order: the pack must still be `DRAFT`
        (`ERR_RULE_PACK_NOT_DRAFT`); the acting engineer must not be the pack's
        `created_by_user_id` (`ERR_ACTIVATION_SEGREGATION_VIOLATION`)"

        Design: Corner/endpoints/rule_added_after_pack_activation_rejected
        """
        set_clock(api)
        pack = build_active_rule_pack(
            api,
            REFERENCE_RULES,
            version_label="P-frozen",
            effective_from=INCUMBENT_FROM,
            effective_until=FAR_FUTURE,
        )
        assert pack["status"] == RulePackStatus.ACTIVE
        assert pack["activated_by_user_id"] is not None

        late_rule = api.create_rule(
            pack["id"],
            emulator_hard_decline_rule_payload(points=45, evaluation_order=5),
            ENGINEER,
        )
        validate_error(late_rule, ApiErrorId.ERR_RULE_PACK_NOT_DRAFT, 409)

        second_activation = api.activate_rule_pack(pack["id"], ENGINEER_APPROVER)
        validate_error(second_activation, ApiErrorId.ERR_RULE_PACK_NOT_DRAFT, 409)

        frozen = read_rule_pack(api, pack["id"])
        assert frozen["status"] == RulePackStatus.ACTIVE
        assert frozen["rule_count"] == 1, "the refused rule was never added"

        rows, meta = validate_paginated(api.list_rules(pack["id"], ENGINEER))
        assert meta["total_count"] == 1
        assert rows[0]["code"] == RuleCode.BEH_FAST_CHECKOUT


class TestPackShapeInvariantsAreOrdered:
    """Weights are checked before bands, so a doubly broken pack reports the weights."""

    def test_broken_weights_beat_broken_bands_and_nothing_is_stored(
        self, api: ApiClient
    ) -> None:
        """0.90 weights, equal floors, and both at once: three refusals, no rows.

        PRD: "`rule_weight` and `model_weight`, summed and rounded half up to two
        decimals, must come to exactly 1.00, or the request is rejected with
        `ERR_WEIGHTS_NOT_NORMALIZED`."
        PRD: "And `review_floor_score` must be strictly below `decline_floor_score`, or
        the request is rejected with `ERR_INVALID_SCORE_BANDS`."

        Design: Corner/errors/rule_pack_weights_and_bands_rejected_in_priority_order
        """
        set_clock(api)

        bad_weights = api.create_rule_pack(
            create_rule_pack_payload(
                version_label="P-bad-weights", rule_weight=0.40, model_weight=0.50
            ),
            ENGINEER,
        )
        validate_error(bad_weights, ApiErrorId.ERR_WEIGHTS_NOT_NORMALIZED, 422)

        bad_bands = api.create_rule_pack(
            create_rule_pack_payload(
                version_label="P-bad-bands",
                review_floor_score=60.00,
                decline_floor_score=60.00,
            ),
            ENGINEER,
        )
        validate_error(bad_bands, ApiErrorId.ERR_INVALID_SCORE_BANDS, 422)

        both_broken = api.create_rule_pack(
            create_rule_dominant_pack_payload(
                version_label="P-bad-both",
                rule_weight=0.30,
                model_weight=0.30,
                review_floor_score=70.00,
                decline_floor_score=50.00,
            ),
            ENGINEER,
        )
        validate_error(both_broken, ApiErrorId.ERR_WEIGHTS_NOT_NORMALIZED, 422)
        assert both_broken.json()["data"]["error_id"] != (
            ApiErrorId.ERR_INVALID_SCORE_BANDS
        ), "the weights rule is stated before the bands rule and answers first"

        _rows, meta = validate_paginated(api.list_rule_packs(ENGINEER))
        assert meta["total_count"] == 0, "not one of the three refused drafts persisted"

def _report(api: ApiClient, pack_id: str, cohort: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_rule_pack_performance(pack_id, ENGINEER, params={"cohort": cohort})
    )


def _build_two_approvals_one_decline(api: ApiClient, env: ScoringEnv):
    """Two approvals taken before the flag existed, then a decline taken after it.

    The two approvals carry the account over the good-customer thresholds, so the
    third order — a decline — is the only one whose frozen snapshot is true.
    """
    first = build_approved_assessment(api, env, SMALL_ORDER_CENTS)
    second = build_approved_assessment(api, env, SMALL_ORDER_CENTS)
    assert read_customer(api, env.customer_id)["good_customer_flag"] is True
    declined = open_and_score(
        api,
        env,
        amount_cents=SMALL_ORDER_CENTS,
        model_raw_probability=PROB_DECLINE_EXACTLY_AT_DECLINE_FLOOR,
    )
    return first, second, declined


class TestInsultRateCohorts:
    """Two cohorts over one population, resolved from the frozen snapshot."""

    def test_decision_cohort_measures_every_terminal_order_on_the_pack(
        self, api: ApiClient
    ) -> None:
        """Three terminal orders, one unjustified decline: an insult rate of 0.3333.

        PRD: "Under `DECISION_COHORT`, the denominator is every terminal assessment
        on the pack, and the numerator is those whose `final_disposition` is
        `DECLINED` and whose `outcome_label` is not `FRAUD` — declines that fraud
        never justified."
        PRD: "`insult_rate` is the numerator divided by the denominator, rounded
        half up to four decimal places, and is reported as 0.0000 when the
        denominator is 0."

        Design: Difficulty/dual_variant_calc/insult_rate_decision_cohort_vs_good_customer_cohort
        """
        env = build_scoring_env(api)
        first, _second, declined = _build_two_approvals_one_decline(api, env)

        assert_score(declined["model_points"], 86.67, "model_points")
        assert_score(declined["blended_score"], 60.00, "blended_score")
        assert declined["decision"] == Decision.DECLINE
        assert declined["decision_reason"] == DecisionReason.SCORE_BAND
        assert declined["state"] == AssessmentState.DECIDED_DECLINE
        assert declined["final_disposition"] == FinalDisposition.DECLINED
        assert declined["outcome_label"] == OutcomeLabel.UNKNOWN

        build_lost_chargeback(
            api, first["id"], SMALL_ORDER_CENTS, CLOCK_EPOCH, represent_first=False
        )
        assert read_assessment(api, first["id"])["outcome_label"] == OutcomeLabel.FRAUD

        report = _report(api, env.pack_id, Cohort.DECISION_COHORT)
        assert_performance_report(report)
        assert report["cohort"] == Cohort.DECISION_COHORT
        assert report["denominator_count"] == 3
        assert report["approved_count"] == 2
        assert report["declined_count"] == 1
        assert report["false_positive_count"] == 1
        assert report["confirmed_fraud_count"] == 1
        assert_rate(report["insult_rate"], 0.3333, "insult_rate")
        assert_rate(report["fraud_capture_rate"], 0.0000, "fraud_capture_rate")

    def test_good_customer_cohort_narrows_to_the_frozen_snapshot(
        self, api: ApiClient
    ) -> None:
        """Only the order decided while the flag was true survives the narrowing.

        PRD: "Under `GOOD_CUSTOMER_COHORT`, the denominator narrows to terminal
        assessments whose `good_customer_at_decision` is true, and the numerator is
        those of *them* whose `final_disposition` is `DECLINED` and whose
        `outcome_label` is not `FRAUD`."
        PRD: "Cohort membership is resolved from the **frozen snapshot**
        `good_customer_at_decision` stored on the assessment, never from the
        customer's `good_customer_flag` as it stands now, and the evaluation order
        is: resolve membership from the snapshot, partition into numerator and
        denominator, divide, and round the **quotient** to four decimal places."

        Design: Difficulty/dual_variant_calc/insult_rate_decision_cohort_vs_good_customer_cohort
        """
        env = build_scoring_env(api)
        first, second, declined = _build_two_approvals_one_decline(api, env)

        assert first["good_customer_at_decision"] is False
        assert second["good_customer_at_decision"] is False, (
            "the snapshot is taken before the approval's own counters land"
        )
        assert declined["good_customer_at_decision"] is True

        build_lost_chargeback(
            api, first["id"], SMALL_ORDER_CENTS, CLOCK_EPOCH, represent_first=False
        )
        assert read_customer(api, env.customer_id)["good_customer_flag"] is False, (
            "the confirmed fraud has since disqualified the account"
        )

        report = _report(api, env.pack_id, Cohort.GOOD_CUSTOMER_COHORT)
        assert_performance_report(report)
        assert report["cohort"] == Cohort.GOOD_CUSTOMER_COHORT
        assert report["denominator_count"] == 1, (
            "membership follows the frozen snapshots, not the current flag"
        )
        assert report["approved_count"] == 0
        assert report["declined_count"] == 1
        assert report["false_positive_count"] == 1
        assert report["confirmed_fraud_count"] == 0
        assert_rate(report["insult_rate"], 1.0000, "insult_rate")
        assert_rate(report["fraud_capture_rate"], 0.0000, "fraud_capture_rate")


class TestCohortSelectorDefault:
    """Omitting the selector must reproduce the decision cohort exactly."""

    def test_the_default_report_equals_the_decision_cohort_and_an_empty_cohort_guards(
        self, api: ApiClient
    ) -> None:
        """One approval and one decline give 0.5000, while the good-customer cohort is 0.

        PRD: "The report is available to a `PolicyEngineer` or a `ReviewLead` and takes a
        single selector, `cohort`, which defaults to `DECISION_COHORT` and may instead be
        `GOOD_CUSTOMER_COHORT`."
        PRD: "`insult_rate` is the numerator divided by the denominator, rounded half up
        to four decimal places, and is reported as 0.0000 when the denominator is 0."

        Design: Corner/calculations/performance_cohort_selector_defaults_to_decision_cohort
        """
        env = build_scoring_env(api)
        approved = build_approved_assessment(api, env, SMALL_ORDER_CENTS)
        assert approved["state"] == AssessmentState.DECIDED_APPROVE
        assert approved["good_customer_at_decision"] is False

        declined = open_and_score(
            api,
            env,
            amount_cents=SMALL_ORDER_CENTS,
            model_raw_probability=PROB_DECLINE_EXACTLY_AT_DECLINE_FLOOR,
        )
        assert_score(declined["blended_score"], 60.00, "blended_score")
        assert declined["decision"] == Decision.DECLINE
        assert declined["decision_reason"] == DecisionReason.SCORE_BAND
        assert declined["final_disposition"] == FinalDisposition.DECLINED
        assert declined["good_customer_at_decision"] is False
        assert read_assessment(api, declined["id"])["outcome_label"] == (
            OutcomeLabel.UNKNOWN
        )

        default_report = get_success_data(
            api.get_rule_pack_performance(env.pack_id, ENGINEER)
        )
        assert_performance_report(default_report)
        assert default_report["cohort"] == Cohort.DECISION_COHORT, (
            "the omitted selector defaults to the decision cohort"
        )
        assert default_report["denominator_count"] == 2
        assert default_report["approved_count"] == 1
        assert default_report["declined_count"] == 1
        assert default_report["false_positive_count"] == 1
        assert default_report["confirmed_fraud_count"] == 0
        assert_rate(default_report["insult_rate"], 0.5000, "insult_rate")
        assert_rate(default_report["fraud_capture_rate"], 0.0000, "fraud_capture_rate")

        explicit_report = _report(api, env.pack_id, Cohort.DECISION_COHORT)
        for field in (
            "cohort",
            "denominator_count",
            "approved_count",
            "declined_count",
            "false_positive_count",
            "confirmed_fraud_count",
            "insult_rate",
            "fraud_capture_rate",
        ):
            assert explicit_report[field] == default_report[field], (
                f"the default report must agree with DECISION_COHORT on {field}"
            )

        empty_report = _report(api, env.pack_id, Cohort.GOOD_CUSTOMER_COHORT)
        assert_performance_report(empty_report)
        assert empty_report["cohort"] == Cohort.GOOD_CUSTOMER_COHORT
        assert empty_report["denominator_count"] == 0, (
            "no assessment froze a true good-customer snapshot"
        )
        assert empty_report["approved_count"] == 0
        assert empty_report["declined_count"] == 0
        assert empty_report["false_positive_count"] == 0
        assert_rate(empty_report["insult_rate"], 0.0000, "insult_rate")
        assert_rate(empty_report["fraud_capture_rate"], 0.0000, "fraud_capture_rate")
