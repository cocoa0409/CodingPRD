"""Validation rules taken one family at a time: which rule owns the answer when
several are broken at once, and what the accepted call looks like afterwards."""
from test_helpers import (
    ApiErrorId,
    assert_agent_index,
    assert_attainment,
    assert_evaluator_load,
    assert_instant,
    assert_money,
    assert_scores,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)

NOW = "2026-08-05T09:00:00Z"


class TestItemScoresRejectionFamilyThenAcceptance:
    """The four cover rules of a submitted scorecard, each answering for itself."""

    #: A cover omitting the not-applicable-eligible behaviour entirely.
    MISSING_SURVEY = {"DISCLOSE": 5, "GREET": 4, "RESOLVE": 3}
    #: A cover scoring one behaviour above its own maximum.
    OVER_MAX = {"DISCLOSE": 6, "GREET": 4, "RESOLVE": 3, "SURVEY": 5}
    #: A cover marking a behaviour that does not allow it not applicable.
    MISPLACED_NA = {"DISCLOSE": 5, "GREET": "NA", "RESOLVE": 3, "SURVEY": 5}
    #: A cover naming a behaviour the pinned scorecard does not carry.
    UNKNOWN_CODE = {"DISCLOSE": 5, "GREET": 4, "RESOLVE": 3, "SURVEY": 5, "EMPATHY": 4}
    #: The unknown key and an out-of-range value broken at the same time.
    UNKNOWN_AND_OVER_MAX = {
        "DISCLOSE": 6,
        "GREET": 4,
        "RESOLVE": 3,
        "SURVEY": 5,
        "EMPATHY": 4,
    }

    def test_each_broken_cover_answers_with_its_own_rule_and_leaves_no_trace(self, api):
        """Four rules, four errors, and the unknown key outranks the range check.

        PRD: "Every key of `item_scores` must be a behaviour code of the pinned form,
        and an unknown key answers `ERR_FORM_VERSION_MISMATCH` rather than an
        incompleteness error, because a key the form does not recognise means the client
        scored against a different form version."
        PRD: "Every behaviour code of the form must then appear exactly once, with none
        omitted and none repeated, else `ERR_ITEM_SCORE_INCOMPLETE`; every numeric value
        must be an integer from `0` through that behaviour's `max_points`, else
        `ERR_ITEM_SCORE_OUT_OF_RANGE`; and the literal `"NA"` may appear only against a
        behaviour whose `allows_not_applicable` is `true` and never against a
        `compliance_critical` behaviour, else `ERR_NA_NOT_ALLOWED`."
        PRD: "The row is born with `review_status` of `DRAFT` and `feedback_status` of
        `PENDING`, with `item_scores` an empty object, and with `weighted_score`,
        `raw_weighted_score`, `adjusted_weighted_score`, `submitted_at`,
        `feedback_delivered_at` and `agreement` all null, `auto_fail_triggered` `false`,
        and `compliance_result` at `NOT_EVALUATED`."

        Design: Corner/validations/validation_item_scores_family_rejected_then_accepted
        """
        env = fx.draft_evaluation_env(api)
        headers = fx.make_evaluator_headers(env.evaluator["id"])
        expected = [
            (self.MISSING_SURVEY, ApiErrorId.ITEM_SCORE_INCOMPLETE.value),
            (self.OVER_MAX, ApiErrorId.ITEM_SCORE_OUT_OF_RANGE.value),
            (self.MISPLACED_NA, ApiErrorId.NA_NOT_ALLOWED.value),
            (self.UNKNOWN_CODE, ApiErrorId.FORM_VERSION_MISMATCH.value),
            (self.UNKNOWN_AND_OVER_MAX, ApiErrorId.FORM_VERSION_MISMATCH.value),
        ]

        for cover, error_id in expected:
            validate_error(
                api.submit_evaluation(
                    env.evaluation["id"], f.submit_payload(cover), headers
                ),
                error_id,
                422,
            )

        untouched = fx.read_evaluation(api, env.evaluation["id"])
        assert untouched["version"] == env.evaluation["version"]
        assert untouched["review_status"] == "DRAFT"
        assert untouched["item_scores"] == {}
        assert untouched["weighted_score"] is None
        assert fx.read_selection(api, env.selection["id"])["status"] == "ASSIGNED"

    def test_the_valid_cover_is_scored_and_the_row_then_refuses_a_second_score(self, api):
        """One accepted submit closes the door on the next one.

        PRD: "**Step one:** `item_scores` is stored and `weighted_score`,
        `raw_weighted_score`, `auto_fail_triggered` and `compliance_result` take the values
        just computed."
        PRD: "The evaluation's `review_status` must be `DRAFT` or `REOPENED`, else
        `ERR_EVALUATION_NOT_EDITABLE`."

        Design: Corner/validations/validation_item_scores_family_rejected_then_accepted
        """
        env = fx.draft_evaluation_env(api)
        headers = fx.make_evaluator_headers(env.evaluator["id"])

        scored = validate_success(
            api.submit_evaluation(
                env.evaluation["id"], f.submit_payload(f.PASSING_ITEM_SCORES), headers
            )
        )

        assert_scores(
            scored,
            weighted_score=82.00,
            raw_weighted_score=82.00,
            compliance_result="PASS",
        )
        assert scored["review_status"] == "SUBMITTED"
        assert_instant(scored["submitted_at"], NOW)
        assert scored["version"] == env.evaluation["version"] + 1

        validate_error(
            api.submit_evaluation(
                env.evaluation["id"],
                f.submit_payload({"DISCLOSE": 5, "GREET": 5, "RESOLVE": 5, "SURVEY": 5}),
                headers,
            ),
            ApiErrorId.EVALUATION_NOT_EDITABLE.value,
            409,
        )
        after = fx.read_evaluation(api, env.evaluation["id"])
        assert_money(after["weighted_score"], 82.00)
        assert after["version"] == scored["version"]


class TestRecognitionGateOpensAtExactlyNinetyTwo:
    """Three scored evaluations walk the agent up to the threshold, and each gate
    refuses in its own turn on the way."""

    @staticmethod
    def _score_one_more(api, env, interaction, item_scores, window):
        """Pull, assign, open and submit one more evaluation of the same agent."""
        selection = fx.create_selection(
            api, env.plan["id"], interaction["id"], "RANDOM"
        )
        fx.assign_selection(
            api,
            selection["id"],
            env.evaluator["id"],
            review_window_start=window[0],
            review_window_end=window[1],
        )
        evaluation = fx.open_evaluation(api, selection["id"], env.evaluator["id"])
        return fx.submit_evaluation(
            api, evaluation["id"], env.evaluator["id"], item_scores
        )

    @classmethod
    def _one_high_score(cls, api):
        """A single scored evaluation at 93.00, plus two more contacts waiting."""
        env = fx.program_env(
            api,
            per_agent_target_volume=4,
            mix=dict(f.ALL_RANDOM_MIX),
            csat_score=5,
        )
        env.interaction2 = fx.create_verified_interaction(
            api,
            env.agent["id"],
            started_at="2026-08-03T11:00:00Z",
            ended_at="2026-08-03T11:10:00Z",
            csat_score=5,
        )
        env.interaction3 = fx.create_verified_interaction(
            api,
            env.agent["id"],
            started_at="2026-08-04T10:00:00Z",
            ended_at="2026-08-04T10:10:00Z",
            csat_score=5,
        )
        env.evaluation1 = cls._score_one_more(
            api,
            env,
            env.interaction,
            f.HIGH_ITEM_SCORES_93,
            ("2026-08-05T09:00:00Z", "2026-08-05T11:00:00Z"),
        )
        return env

    def test_the_history_gate_speaks_first_and_the_threshold_gate_second(self, api):
        """A 93.00 average is worth nothing on one evaluation.

        PRD: "Three gates apply in order: the agent must have at least two evaluations
        in `review_status` `SUBMITTED`, `FINALIZED` or `REOPENED`, else
        `ERR_INSUFFICIENT_EVALUATION_HISTORY`; the agent's `open_compliance_findings` must
        be `0`, else `ERR_COMPLIANCE_HOLD_OPEN`; and the agent's `quality_index_rolling`
        must be at least `92.00`, else `ERR_RECOGNITION_THRESHOLD_NOT_MET`."
        PRD: "`quality_index_rolling` is the unweighted mean of the four most recent
        effective scores."

        Design: Corner/validations/validation_recognition_gate_passes_only_at_ninety_two_exactly
        """
        env = self._one_high_score(api)
        assert_agent_index(fx.read_agent(api, env.agent["id"]), rolling=93.00)

        validate_error(
            api.award_recognition(
                env.agent["id"],
                f.recognition_payload(award_code="TOP_QUALITY", points=50),
                fx.make_quality_manager_headers(),
            ),
            ApiErrorId.INSUFFICIENT_EVALUATION_HISTORY.value,
            422,
        )

        second = self._score_one_more(
            api,
            env,
            env.interaction2,
            f.HIGH_ITEM_SCORES_90,
            ("2026-08-05T11:00:00Z", "2026-08-05T13:00:00Z"),
        )
        assert_money(second["weighted_score"], 90.00)
        assert_agent_index(fx.read_agent(api, env.agent["id"]), rolling=91.50)

        validate_error(
            api.award_recognition(
                env.agent["id"],
                f.recognition_payload(award_code="TOP_QUALITY", points=50),
                fx.make_quality_manager_headers(),
            ),
            ApiErrorId.RECOGNITION_THRESHOLD_NOT_MET.value,
            422,
        )
        assert fx.read_agent(api, env.agent["id"])["recognition_points"] == 0

    def test_a_rolling_index_of_exactly_ninety_two_clears_the_inclusive_gate(self, api):
        """The comparison is at least, so the boundary value passes.

        PRD: "On success the awarded `points` are added to the agent's
        `recognition_points` and the agent's `version` is incremented; the operation
        answers with the updated agent rather than a separate award record."
        PRD: "It is recomputed on every submit, and it advances by one when the agent
        acknowledges an evaluation whose `compliance_result` is `PASS` and whose effective
        score is at least `85.00`."

        Design: Corner/validations/validation_recognition_gate_passes_only_at_ninety_two_exactly
        """
        env = self._one_high_score(api)
        self._score_one_more(
            api,
            env,
            env.interaction2,
            f.HIGH_ITEM_SCORES_90,
            ("2026-08-05T11:00:00Z", "2026-08-05T13:00:00Z"),
        )
        third = self._score_one_more(
            api,
            env,
            env.interaction3,
            f.HIGH_ITEM_SCORES_93,
            ("2026-08-05T13:00:00Z", "2026-08-05T15:00:00Z"),
        )
        assert_money(third["weighted_score"], 93.00)
        before = fx.read_agent(api, env.agent["id"])
        # (93.00 + 90.00 + 93.00) / 3 lands exactly on the 92.00 constant.
        assert_agent_index(before, rolling=92.00)

        awarded = validate_success(
            api.award_recognition(
                env.agent["id"],
                f.recognition_payload(award_code="TOP_QUALITY", points=50),
                fx.make_quality_manager_headers(),
            )
        )

        assert awarded["recognition_points"] == 50
        assert awarded["version"] == before["version"] + 1
        assert_agent_index(
            awarded,
            rolling=92.00,
            open_compliance_findings=0,
            consecutive_passing_evaluations=3,
        )


class TestPlanStateOutranksConsentAndSelectionState:
    """Three rules broken at once on one closed plan, and the state rule answers
    every time until the plan state is fixed."""

    @staticmethod
    def _closed_plan_env(api):
        """A swept, CLOSED plan plus one contact whose consent is still pending."""
        fx.set_clock(api, NOW)
        form = fx.create_active_form(api)
        agent = fx.create_agent(api)
        evaluator = fx.create_evaluator(api)
        cleared = fx.create_verified_interaction(api, agent["id"])
        pending = fx.create_interaction(
            api,
            agent["id"],
            started_at="2026-08-04T10:00:00Z",
            ended_at="2026-08-04T10:10:00Z",
            required_disclosures=["RECORDING"],
        )
        plan = fx.create_open_plan(
            api, form["id"], per_agent_target_volume=4, mix=dict(f.ALL_RANDOM_MIX)
        )
        selection = fx.create_selection(api, plan["id"], cleared["id"], "RANDOM")
        plan = fx.close_plan(api, plan["id"])
        return fx.Env(
            form=form,
            agent=agent,
            evaluator=evaluator,
            cleared=cleared,
            pending=pending,
            plan=plan,
            selection=selection,
        )

    def test_the_closed_plan_answers_before_consent_and_before_selection_state(self, api):
        """Two calls, two other broken rules, and one error both times.

        PRD: "The plan must be `OPEN`, else `ERR_PLAN_NOT_OPEN`, and the interaction
        must satisfy the consent gate of §2.8."
        PRD: "Seven preconditions guard the transition: the selection must be
        `SELECTED`, else `ERR_SELECTION_NOT_ASSIGNABLE`; its plan must be `OPEN`, else
        `ERR_PLAN_NOT_OPEN`; its interaction must satisfy the consent gate, else
        `ERR_CONSENT_NOT_VERIFIED`; the named evaluator's `calibration_status` must not be
        `SUSPENDED`, else `ERR_EVALUATOR_NOT_CALIBRATED`; `review_window_end` must be
        strictly after `review_window_start`, else `ERR_INVALID_TIME_RANGE`; the requested
        window must not intersect any window that evaluator already holds on a selection in
        status `ASSIGNED`, using **half-open** semantics where the start is included and
        the end excluded — so a window ending at 11:00 sits legally beside one starting at
        11:00, while any genuine overlap is rejected with `ERR_EVALUATOR_WINDOW_CONFLICT`;
        and the evaluator's `open_assignment_count`, measured *before* this assignment,
        must be strictly below their `max_open_assignments`, else
        `ERR_EVALUATOR_CAPACITY_EXCEEDED`."

        Design: Corner/validations/validation_plan_state_outranks_consent_and_selection_state
        """
        env = self._closed_plan_env(api)
        assert env.plan["status"] == "CLOSED"
        swept = fx.read_selection(api, env.selection["id"])
        assert swept["status"] == "EXCLUDED"
        assert swept["exclusion_reason"] == "PLAN_CLOSED_SWEEP"

        validate_error(
            api.create_selection(
                f.sample_selection_payload(
                    env.plan["id"], env.pending["id"], source="RANDOM"
                ),
                fx.make_quality_manager_headers(),
            ),
            ApiErrorId.PLAN_NOT_OPEN.value,
            409,
        )
        validate_error(
            api.assign_selection(
                env.selection["id"],
                f.assign_payload(
                    env.evaluator["id"],
                    review_window_start="2026-08-05T09:00:00Z",
                    review_window_end="2026-08-05T11:00:00Z",
                ),
                fx.make_quality_manager_headers(),
            ),
            ApiErrorId.PLAN_NOT_OPEN.value,
            409,
        )

    def test_a_fresh_open_plan_lets_the_consent_rules_speak_in_their_own_order(self, api):
        """Pending, then denied, then frozen — and the cleared contact still enters.

        PRD: "Before a plan is drafted, and again when it is opened, the server
        compares its period against every other plan sharing the same `form_id` whose
        status is `DRAFT` or `OPEN`, using **closed-interval** semantics: two periods
        collide when they share even a single instant, so touching endpoints collide — a
        plan ending on 31 August collides with a plan starting on 31 August."
        PRD: "Separately, a `DENIED` interaction is frozen against further consent
        review and against new analytics screening: both are rejected with
        `ERR_CONSENT_ALREADY_DENIED` (HTTP 409)."
        PRD: "On success the selection is stored with `status` of `SELECTED`, with
        `agent_id` denormalised from the interaction's `agent_id` at creation and never
        updated afterwards even if the interaction is later re-attributed, with
        `assigned_evaluator_id`, `review_window_start`, `review_window_end` and
        `exclusion_reason` all null; the plan's `agent_volume_attainment` and
        `selections_count` and the interaction's `sampled_count` are recomputed, and the
        plan's `version` is incremented."

        Design: Corner/validations/validation_plan_state_outranks_consent_and_selection_state
        """
        env = self._closed_plan_env(api)

        # The CLOSED plan is invisible to the overlap check, so the identical period
        # is free again.
        second = fx.create_open_plan(
            api, env.form["id"], per_agent_target_volume=4, mix=dict(f.ALL_RANDOM_MIX)
        )
        pull_pending = f.sample_selection_payload(
            second["id"], env.pending["id"], source="RANDOM"
        )
        validate_error(
            api.create_selection(pull_pending, fx.make_quality_manager_headers()),
            ApiErrorId.CONSENT_NOT_VERIFIED.value,
            422,
        )

        denied = fx.consent_review(api, env.pending["id"], "DENIED", [])
        assert denied["recording_consent_status"] == "DENIED"
        validate_error(
            api.create_selection(pull_pending, fx.make_quality_manager_headers()),
            ApiErrorId.CONSENT_NOT_VERIFIED.value,
            422,
        )
        validate_error(
            api.consent_review(
                env.pending["id"],
                f.consent_review_payload("VERIFIED", captured_disclosures=["RECORDING"]),
                fx.make_compliance_auditor_headers(),
            ),
            ApiErrorId.CONSENT_ALREADY_DENIED.value,
            409,
        )

        accepted = fx.create_selection(api, second["id"], env.cleared["id"], "RANDOM")
        assert accepted["status"] == "SELECTED"
        assert accepted["agent_id"] == env.agent["id"]


class TestRecognitionTurnsOnAnotherEntitysComplianceHold:
    """The recognition payload never changes; a contact's compliance hold does."""

    @staticmethod
    def _score_one_more(api, env, interaction, item_scores, window):
        """Pull, assign, open and submit one more evaluation of the same agent."""
        selection = fx.create_selection(
            api, env.plan["id"], interaction["id"], "RANDOM"
        )
        fx.assign_selection(
            api,
            selection["id"],
            env.evaluator["id"],
            review_window_start=window[0],
            review_window_end=window[1],
        )
        evaluation = fx.open_evaluation(api, selection["id"], env.evaluator["id"])
        return fx.submit_evaluation(
            api, evaluation["id"], env.evaluator["id"], item_scores
        )

    @classmethod
    def _two_clean_high_scores(cls, api):
        """Two evaluations at 93.00 apiece and a third contact still unscored."""
        env = fx.program_env(
            api, per_agent_target_volume=4, mix=dict(f.ALL_RANDOM_MIX), csat_score=5
        )
        env.interaction2 = fx.create_verified_interaction(
            api,
            env.agent["id"],
            started_at="2026-08-03T11:00:00Z",
            ended_at="2026-08-03T11:10:00Z",
            csat_score=5,
        )
        env.interaction3 = fx.create_verified_interaction(
            api,
            env.agent["id"],
            started_at="2026-08-04T10:00:00Z",
            ended_at="2026-08-04T10:10:00Z",
            csat_score=4,
        )
        env.evaluation1 = cls._score_one_more(
            api,
            env,
            env.interaction,
            f.HIGH_ITEM_SCORES_93,
            ("2026-08-05T09:00:00Z", "2026-08-05T11:00:00Z"),
        )
        env.evaluation2 = cls._score_one_more(
            api,
            env,
            env.interaction2,
            f.HIGH_ITEM_SCORES_93,
            ("2026-08-05T11:00:00Z", "2026-08-05T13:00:00Z"),
        )
        return env

    def test_the_award_lands_and_then_a_third_contacts_hold_refuses_the_next_one(self, api):
        """Same call, same agent, and the hold outranks the threshold gate.

        PRD: "Three gates apply in order: the agent must have at least two evaluations
        in `review_status` `SUBMITTED`, `FINALIZED` or `REOPENED`, else
        `ERR_INSUFFICIENT_EVALUATION_HISTORY`; the agent's `open_compliance_findings` must
        be `0`, else `ERR_COMPLIANCE_HOLD_OPEN`; and the agent's `quality_index_rolling`
        must be at least `92.00`, else `ERR_RECOGNITION_THRESHOLD_NOT_MET`."
        PRD: "**Step five, hop one:** when `compliance_result` is `FAIL`, the
        interaction's `compliance_hold` is set to `true`."

        Design: Corner/validations/validation_recognition_depends_on_interaction_compliance_hold
        """
        env = self._two_clean_high_scores(api)
        award = f.recognition_payload(award_code="TOP_QUALITY", points=40)

        granted = validate_success(
            api.award_recognition(
                env.agent["id"], award, fx.make_quality_manager_headers()
            )
        )
        assert granted["recognition_points"] == 40

        failed = self._score_one_more(
            api,
            env,
            env.interaction3,
            f.AUTO_FAIL_ITEM_SCORES,
            ("2026-08-05T13:00:00Z", "2026-08-05T15:00:00Z"),
        )
        assert_scores(
            failed,
            weighted_score=52.00,
            auto_fail_triggered=True,
            compliance_result="FAIL",
        )

        validate_error(
            api.award_recognition(
                env.agent["id"], award, fx.make_quality_manager_headers()
            ),
            ApiErrorId.COMPLIANCE_HOLD_OPEN.value,
            409,
        )
        assert fx.read_agent(api, env.agent["id"])["recognition_points"] == 40

    def test_only_the_failed_contact_carries_the_hold_that_closes_the_gate(self, api):
        """The refusal is driven by one row of a different collection.

        PRD: "**Step six, hop two:** precisely because `compliance_hold` moved from
        `false` to `true`, the agent's `open_compliance_findings` is recomputed one higher —
        it is always the count of that agent's interactions carrying `compliance_hold` — and
        the agent's `coaching_state` becomes `REQUIRED` when it had been `NONE` or
        `CLEARED`."
        PRD: "Interactions are readable individually — exposing the consent posture,
        both disclosure arrays, `compliance_hold` and `sampled_count` — and the collection
        listing accepts `agent_id`, `channel`, `customer_flagged`,
        `recording_consent_status` and `compliance_hold` filters, which together give the
        reverse path from an agent back to their contacts."

        Design: Corner/validations/validation_recognition_depends_on_interaction_compliance_hold
        """
        env = self._two_clean_high_scores(api)
        validate_success(
            api.award_recognition(
                env.agent["id"],
                f.recognition_payload(award_code="TOP_QUALITY", points=40),
                fx.make_quality_manager_headers(),
            )
        )
        self._score_one_more(
            api,
            env,
            env.interaction3,
            f.AUTO_FAIL_ITEM_SCORES,
            ("2026-08-05T13:00:00Z", "2026-08-05T15:00:00Z"),
        )

        assert fx.read_interaction(api, env.interaction3["id"])["compliance_hold"] is True
        assert fx.read_interaction(api, env.interaction["id"])["compliance_hold"] is False
        assert fx.read_interaction(api, env.interaction2["id"])["compliance_hold"] is False
        # (93.00 + 93.00 + 52.00) / 3 = 79.3333... on the rolling window.
        assert_agent_index(
            fx.read_agent(api, env.agent["id"]),
            rolling=79.33,
            open_compliance_findings=1,
            coaching_state="REQUIRED",
            recognition_points=40,
        )
        held, meta = validate_paginated(
            api.list_interactions(
                fx.make_compliance_auditor_headers(), {"compliance_hold": "true"}
            )
        )
        assert meta["total_count"] == 1
        assert held[0]["id"] == env.interaction3["id"]


class TestDisputeWindowIsInclusiveToTheSecond:
    """Two sibling evaluations delivered at the same instant, disputed one second
    apart across the seven-day deadline."""

    SEVEN_DAYS_LATER = "2026-08-12T09:00:00Z"
    ONE_SECOND_LATE = "2026-08-12T09:00:01Z"

    @staticmethod
    def _two_delivered_evaluations(api):
        """Two scored evaluations of one agent, both delivered at the pinned
        clock instant."""
        env = fx.two_selection_env(
            api, per_agent_target_volume=4, mix=dict(f.ALL_RANDOM_MIX)
        )
        env.evaluation = fx.open_evaluation(
            api, env.selection["id"], env.evaluator["id"]
        )
        fx.submit_evaluation(api, env.evaluation["id"], env.evaluator["id"])
        env.evaluation = fx.deliver_evaluation(
            api, env.evaluation["id"], env.evaluator["id"]
        )
        env.evaluation2 = fx.open_evaluation(
            api, env.selection2["id"], env.evaluator["id"]
        )
        fx.submit_evaluation(api, env.evaluation2["id"], env.evaluator["id"])
        env.evaluation2 = fx.deliver_evaluation(
            api, env.evaluation2["id"], env.evaluator["id"]
        )
        return env

    def test_a_filing_exactly_seven_days_after_delivery_is_accepted(self, api):
        """The deadline instant itself is inside the window.

        PRD: "On success `feedback_status` moves `PENDING → DELIVERED`,
        `feedback_delivered_at` takes the current logical-clock instant, and the
        evaluation's `version` is incremented."
        PRD: "Finally, the filing must occur no later than seven days after the
        evaluation's `feedback_delivered_at`, measured against the logical clock; a later
        filing is rejected with `ERR_DISPUTE_WINDOW_EXPIRED`."
        PRD: "A filed dispute is stored with `agent_id` copied from the evaluation,
        `status` at `SUBMITTED`, `round_count` at `0`, and `reviewer_evaluator_id`,
        `adjusted_item_scores` and `outcome_note` all null."

        Design: Corner/validations/validation_dispute_window_exactly_seven_days_then_one_second_late
        """
        env = self._two_delivered_evaluations(api)
        assert_instant(env.evaluation["feedback_delivered_at"], NOW)
        assert_instant(env.evaluation2["feedback_delivered_at"], NOW)

        fx.set_clock(api, self.SEVEN_DAYS_LATER)
        dispute = validate_success(
            api.create_dispute(
                f.dispute_payload(
                    env.evaluation["id"],
                    env.evaluation["version"],
                    disputed_behavior_codes=["RESOLVE"],
                    rationale="The customer confirmed the fix on the call.",
                ),
                fx.make_agent_headers(env.agent["id"]),
            ),
            201,
        )

        assert dispute["status"] == "SUBMITTED"
        assert dispute["round_count"] == 0
        assert dispute["reviewer_evaluator_id"] is None
        assert (
            fx.read_evaluation(api, env.evaluation["id"])["feedback_status"]
            == "DISPUTED"
        )

    def test_one_second_past_the_same_offset_is_refused_and_creates_nothing(self, api):
        """Only the clock differs between the accepted and the refused filing.

        PRD: "That instant is the start of the dispute window, which runs for seven
        days."
        PRD: "Finally, the filing must occur no later than seven days after the
        evaluation's `feedback_delivered_at`, measured against the logical clock; a later
        filing is rejected with `ERR_DISPUTE_WINDOW_EXPIRED`."

        Design: Corner/validations/validation_dispute_window_exactly_seven_days_then_one_second_late
        """
        env = self._two_delivered_evaluations(api)
        fx.set_clock(api, self.SEVEN_DAYS_LATER)
        fx.file_dispute(
            api,
            env.evaluation["id"],
            env.agent["id"],
            env.evaluation["version"],
            disputed_behavior_codes=["RESOLVE"],
        )

        fx.set_clock(api, self.ONE_SECOND_LATE)
        validate_error(
            api.create_dispute(
                f.dispute_payload(
                    env.evaluation2["id"],
                    env.evaluation2["version"],
                    disputed_behavior_codes=["RESOLVE"],
                    rationale="Same argument, filed one second too late.",
                ),
                fx.make_agent_headers(env.agent["id"]),
            ),
            ApiErrorId.DISPUTE_WINDOW_EXPIRED.value,
            422,
        )

        sibling = fx.read_evaluation(api, env.evaluation2["id"])
        assert sibling["feedback_status"] == "DELIVERED"
        assert sibling["version"] == env.evaluation2["version"]
        _, meta = validate_paginated(
            api.list_disputes(
                fx.make_quality_manager_headers(),
                {"evaluation_id": env.evaluation2["id"]},
            )
        )
        assert meta["total_count"] == 0


class TestEvaluatorCapacityIsAnAggregateNotAPerRowRule:
    """Two individually legal assignments, one evaluator allowed only one at a
    time, and the ledger releasing the slot again."""

    FIRST_WINDOW = ("2026-08-05T09:00:00Z", "2026-08-05T11:00:00Z")
    OVERLAPPING_WINDOW = ("2026-08-05T10:00:00Z", "2026-08-05T12:00:00Z")
    ADJACENT_WINDOW = ("2026-08-05T11:00:00Z", "2026-08-05T13:00:00Z")

    @classmethod
    def _one_slot_evaluator_env(cls, api):
        """Two pulled selections and an evaluator who may hold only one."""
        env = fx.two_selection_env(
            api,
            per_agent_target_volume=4,
            mix=dict(f.ALL_RANDOM_MIX),
            max_open_assignments=1,
            assign_both=False,
        )
        env.selection = fx.assign_selection(
            api,
            env.selection["id"],
            env.evaluator["id"],
            review_window_start=cls.FIRST_WINDOW[0],
            review_window_end=cls.FIRST_WINDOW[1],
        )
        return env

    def test_the_overlap_rule_answers_before_the_capacity_rule(self, api):
        """An intersecting window never reaches the aggregate count.

        PRD: "the requested window must not intersect any window that evaluator already
        holds on a selection in status `ASSIGNED`, using **half-open** semantics where the
        start is included and the end excluded — so a window ending at 11:00 sits legally
        beside one starting at 11:00, while any genuine overlap is rejected with
        `ERR_EVALUATOR_WINDOW_CONFLICT`; and the evaluator's `open_assignment_count`,
        measured *before* this assignment, must be strictly below their
        `max_open_assignments`, else `ERR_EVALUATOR_CAPACITY_EXCEEDED`."
        PRD: "An evaluator carries a `full_name` and an optional `max_open_assignments`
        capping how many selections they may hold concurrently in the assigned state; it
        defaults to `3` and must be at least `1` and at most `20`."

        Design: Corner/validations/validation_evaluator_capacity_is_an_aggregate_over_open_assignments
        """
        env = self._one_slot_evaluator_env(api)
        assert env.selection["status"] == "ASSIGNED"
        assert_evaluator_load(fx.read_evaluator(api, env.evaluator["id"]), 1)

        validate_error(
            api.assign_selection(
                env.selection2["id"],
                f.assign_payload(
                    env.evaluator["id"],
                    review_window_start=self.OVERLAPPING_WINDOW[0],
                    review_window_end=self.OVERLAPPING_WINDOW[1],
                ),
                fx.make_quality_manager_headers(),
            ),
            ApiErrorId.EVALUATOR_WINDOW_CONFLICT.value,
            409,
        )
        validate_error(
            api.assign_selection(
                env.selection2["id"],
                f.assign_payload(
                    env.evaluator["id"],
                    review_window_start=self.ADJACENT_WINDOW[0],
                    review_window_end=self.ADJACENT_WINDOW[1],
                ),
                fx.make_quality_manager_headers(),
            ),
            ApiErrorId.EVALUATOR_CAPACITY_EXCEEDED.value,
            422,
        )

        waiting = fx.read_selection(api, env.selection2["id"])
        assert waiting["status"] == "SELECTED"
        assert waiting["assigned_evaluator_id"] is None
        assert_evaluator_load(fx.read_evaluator(api, env.evaluator["id"]), 1)

    def test_scoring_the_first_row_frees_the_slot_for_the_refused_payload(self, api):
        """The identical request that failed now succeeds, unchanged.

        PRD: "**Step three:** the underlying selection moves `ASSIGNED → EVALUATED` and
        the evaluator's `open_assignment_count` is recomputed downward, releasing capacity."
        PRD: "`open_assignment_count` is always the number of selections whose
        `assigned_evaluator_id` names this evaluator and whose status is `ASSIGNED` —
        selections that are merely `SELECTED`, or that have reached `EVALUATED` or
        `EXCLUDED`, cost the evaluator nothing."

        Design: Corner/validations/validation_evaluator_capacity_is_an_aggregate_over_open_assignments
        """
        env = self._one_slot_evaluator_env(api)
        refused = f.assign_payload(
            env.evaluator["id"],
            review_window_start=self.ADJACENT_WINDOW[0],
            review_window_end=self.ADJACENT_WINDOW[1],
        )
        validate_error(
            api.assign_selection(
                env.selection2["id"], refused, fx.make_quality_manager_headers()
            ),
            ApiErrorId.EVALUATOR_CAPACITY_EXCEEDED.value,
            422,
        )

        evaluation = fx.open_evaluation(
            api, env.selection["id"], env.evaluator["id"]
        )
        fx.submit_evaluation(api, evaluation["id"], env.evaluator["id"])
        assert fx.read_selection(api, env.selection["id"])["status"] == "EVALUATED"
        assert_evaluator_load(fx.read_evaluator(api, env.evaluator["id"]), 0)

        assigned = validate_success(
            api.assign_selection(
                env.selection2["id"], refused, fx.make_quality_manager_headers()
            )
        )

        assert assigned["status"] == "ASSIGNED"
        assert_instant(assigned["review_window_start"], self.ADJACENT_WINDOW[0])
        assert_evaluator_load(fx.read_evaluator(api, env.evaluator["id"]), 1)


class TestSourceEligibilityDependsOnAFlagAndOnAnotherRow:
    """One source turns on the contact's own flag, one on a screening row that
    must already exist, and one on nothing at all."""

    @staticmethod
    def _flagged_and_unflagged_env(api):
        """An OPEN plan over a 25/50/25 mix with one ordinary and one
        customer-flagged contact, neither of them screened yet."""
        env = fx.program_env(
            api, per_agent_target_volume=4, mix=f.source_mix(25, 50, 25)
        )
        env.flagged = fx.create_verified_interaction(
            api,
            env.agent["id"],
            started_at="2026-08-04T10:00:00Z",
            ended_at="2026-08-04T10:10:00Z",
            csat_score=2,
            customer_flagged=True,
        )
        return env

    def test_the_targeted_source_opens_only_once_a_screening_row_exists(self, api):
        """The identical pull is refused before the scan and accepted after it.

        PRD: "Source eligibility is then checked: `CUSTOMER_FLAGGED` requires the
        interaction's `customer_flagged` to be `true`; `TARGETED` requires the interaction to
        carry an analytics scan whose `status` is `CURRENT` and whose `priority_tier` is `P1`
        or `P2`; `RANDOM` carries no additional requirement."
        PRD: "An ineligible pull is rejected with `ERR_SOURCE_NOT_ELIGIBLE`."
        PRD: "A new scan is stored with `status` of `CURRENT`, and every earlier scan of
        the same interaction whose `status` was `CURRENT` moves to `SUPERSEDED` with its
        `version` incremented; a successful create also increments the parent interaction's
        `version`, which is why a second screening of the same contact must re-read the
        interaction first."

        Design: Corner/validations/validation_source_eligibility_depends_on_flag_and_scan
        """
        env = self._flagged_and_unflagged_env(api)
        targeted_pull = f.sample_selection_payload(
            env.plan["id"], env.interaction["id"], source="TARGETED"
        )
        validate_error(
            api.create_selection(
                f.sample_selection_payload(
                    env.plan["id"], env.interaction["id"], source="CUSTOMER_FLAGGED"
                ),
                fx.make_quality_manager_headers(),
            ),
            ApiErrorId.SOURCE_NOT_ELIGIBLE.value,
            422,
        )
        validate_error(
            api.create_selection(targeted_pull, fx.make_quality_manager_headers()),
            ApiErrorId.SOURCE_NOT_ELIGIBLE.value,
            422,
        )

        scan = validate_success(
            api.create_scan(
                f.analytics_scan_payload(
                    env.interaction["id"],
                    env.interaction["version"],
                    silence_pct=30.00,
                    sentiment_delta=-0.40,
                    flagged_categories=["NO_DISCLOSURE"],
                ),
                fx.make_compliance_auditor_headers(),
            ),
            201,
        )
        # 57.50 * 1.20 with no gap bonus, because the disclosure was captured.
        assert_money(scan["risk_score"], 69.00)
        assert scan["priority_tier"] == "P2"
        assert scan["status"] == "CURRENT"

        accepted = validate_success(
            api.create_selection(targeted_pull, fx.make_quality_manager_headers()), 201
        )
        assert accepted["source"] == "TARGETED"
        assert accepted["status"] == "SELECTED"

    def test_the_duplicate_rule_owns_the_second_pull_of_a_held_contact(self, api):
        """RANDOM has no eligibility condition, so the refusal must be the other rule.

        PRD: "Next, the same interaction may not be held twice inside the same plan by a
        live selection — one whose status is `SELECTED`, `ASSIGNED` or `EVALUATED` — and a
        second attempt answers `ERR_DUPLICATE_INTERACTION_SELECTION`."
        PRD: "`sampled_count` is always the number of selections referencing this
        interaction whose status is `SELECTED`, `ASSIGNED` or `EVALUATED`."

        Design: Corner/validations/validation_source_eligibility_depends_on_flag_and_scan
        """
        env = self._flagged_and_unflagged_env(api)
        fx.create_scan(
            api,
            env.interaction["id"],
            env.interaction["version"],
            silence_pct=30.00,
            sentiment_delta=-0.40,
            flagged_categories=["NO_DISCLOSURE"],
        )
        fx.create_selection(api, env.plan["id"], env.interaction["id"], "TARGETED")

        validate_error(
            api.create_selection(
                f.sample_selection_payload(
                    env.plan["id"], env.interaction["id"], source="RANDOM"
                ),
                fx.make_quality_manager_headers(),
            ),
            ApiErrorId.DUPLICATE_INTERACTION_SELECTION.value,
            409,
        )
        flagged_pull = fx.create_selection(
            api, env.plan["id"], env.flagged["id"], "CUSTOMER_FLAGGED"
        )

        assert flagged_pull["status"] == "SELECTED"
        assert_attainment(
            fx.read_plan(api, env.plan["id"]),
            env.agent["id"],
            consumed=2,
            remaining=2,
            by_source={"RANDOM": 0, "TARGETED": 1, "CUSTOMER_FLAGGED": 1},
        )
        assert fx.read_interaction(api, env.interaction["id"])["sampled_count"] == 1
        assert fx.read_interaction(api, env.flagged["id"])["sampled_count"] == 1


class TestSessionRequirementIsComputedBeforeItIsChecked:
    """Completion is measured against the number the sizing calculation produced,
    not against a constant."""

    FIRST_SESSION = "2026-08-06T09:00:00Z"
    SECOND_SESSION = "2026-08-07T09:00:00Z"

    def test_completion_is_refused_at_zero_and_at_one_logged_session(self, api):
        """The requirement is two, so one session is not enough.

        PRD: "Fourth, `required_session_count` is the adjusted deficit divided by the
        tier's expected gain per session — two and a half points for `T1`, two points for
        `T2`, one and a half points for `T3` — rounded **up** to the next whole number, then
        clamped to no fewer than one and no more than eight sessions."
        PRD: "Completing a plan moves it `IN_PROGRESS → COMPLETED` and has three
        preconditions, checked in this order: the plan must not already be `COMPLETED`,
        `ESCALATED` or `VOIDED`, else `ERR_COACHING_PLAN_TERMINAL`; the agent's
        `open_compliance_findings` must be exactly `0`, else `ERR_COMPLIANCE_HOLD_OPEN`,
        because a coaching plan cannot be signed off while a compliance failure stands; and
        `completed_session_count` must be at least `required_session_count`, else
        `ERR_SESSIONS_INCOMPLETE`."
        PRD: "The first logged session moves the plan `ASSIGNED → IN_PROGRESS`; each
        subsequent one is a self-loop that leaves the status at `IN_PROGRESS`."

        Design: Corner/validations/validation_session_requirement_is_computed_before_it_is_checked
        """
        env = fx.coaching_plan_env(api, target_score=85.00)
        plan = env.coaching_plan
        # 85.00 - 82.00 = 3.00 -> T1 -> ceil(3.00 / 2.50) = 2 sessions.
        assert_money(plan["deficit_pct"], 3.00)
        assert plan["required_session_count"] == 2
        assert plan["escalation_tier"] == "T1"
        assert plan["completed_session_count"] == 0
        assert plan["status"] == "ASSIGNED"
        assert_instant(plan["due_at"], "2026-09-04T09:00:00Z")
        assert env.agent["open_compliance_findings"] == 0

        validate_error(
            api.complete_coaching_plan(plan["id"], fx.make_supervisor_headers()),
            ApiErrorId.SESSIONS_INCOMPLETE.value,
            422,
        )

        first = fx.log_coaching_session(api, plan["id"], session_at=self.FIRST_SESSION)
        assert first["status"] == "IN_PROGRESS"
        assert first["completed_session_count"] == 1

        validate_error(
            api.complete_coaching_plan(plan["id"], fx.make_supervisor_headers()),
            ApiErrorId.SESSIONS_INCOMPLETE.value,
            422,
        )
        assert fx.read_coaching_plan(api, plan["id"])["required_session_count"] == 2

    def test_the_second_session_completes_the_plan_and_clears_the_agent(self, api):
        """Two logged sessions, one completion, and four version bumps in total.

        PRD: "On success the plan becomes `COMPLETED` and the agent's `coaching_state`
        becomes `CLEARED`; both `version` values are incremented."
        PRD: "Either way `completed_session_count` increases by one and the plan's
        `version` is incremented."

        Design: Corner/validations/validation_session_requirement_is_computed_before_it_is_checked
        """
        env = fx.coaching_plan_env(api, target_score=85.00)
        plan_id = env.coaching_plan["id"]
        assert env.coaching_plan["version"] == 1
        validate_error(
            api.complete_coaching_plan(plan_id, fx.make_supervisor_headers()),
            ApiErrorId.SESSIONS_INCOMPLETE.value,
            422,
        )
        fx.log_coaching_session(api, plan_id, session_at=self.FIRST_SESSION)
        second = fx.log_coaching_session(api, plan_id, session_at=self.SECOND_SESSION)
        assert second["completed_session_count"] == 2

        completed = validate_success(
            api.complete_coaching_plan(plan_id, fx.make_supervisor_headers())
        )

        assert completed["status"] == "COMPLETED"
        assert completed["required_session_count"] == 2
        # One version at create, one per logged session, one at completion, and
        # nothing at all for the two refusals.
        assert completed["version"] == 4
        assert fx.read_agent(api, env.agent["id"])["coaching_state"] == "CLEARED"


class TestDisputeStateRulesRejectEveryOutOfTurnStep:
    """Three dispute actions, three different guarded statuses, three different
    refusals — never one generic conflict."""

    def test_resolve_respond_and_a_second_filing_each_get_their_own_refusal(self, api):
        """On a freshly filed dispute only a pickup is legal.

        PRD: "A filed dispute is stored with `agent_id` copied from the evaluation,
        `status` at `SUBMITTED`, `round_count` at `0`, and `reviewer_evaluator_id`,
        `adjusted_item_scores` and `outcome_note` all null."
        PRD: "The dispute must be `UNDER_REVIEW`, else `ERR_DISPUTE_NOT_RESOLVABLE`,
        and the acting `X-User-ID` must equal the dispute's recorded
        `reviewer_evaluator_id`, else `ERR_NOT_RESOURCE_OWNER`; the
        segregation-of-duties check applies here as well."
        PRD: "The dispute must be `NEEDS_MORE_INFO`, else
        `ERR_DISPUTE_NOT_RESPONDABLE`, and the acting `X-User-ID` must equal the
        dispute's `agent_id`, else `ERR_NOT_RESOURCE_OWNER`."
        PRD: "an evaluation that already carries a dispute in `SUBMITTED`,
        `UNDER_REVIEW` or `NEEDS_MORE_INFO` is rejected with
        `ERR_DISPUTE_ALREADY_OPEN`."

        Design: Corner/validations/validation_dispute_state_rules_reject_every_out_of_turn_step
        """
        env = fx.disputed_evaluation_env(api)
        assert env.dispute["status"] == "SUBMITTED"
        assert env.dispute["round_count"] == 0
        assert env.dispute["reviewer_evaluator_id"] is None
        assert env.evaluation["feedback_status"] == "DISPUTED"

        validate_error(
            api.resolve_dispute(
                env.dispute["id"],
                f.resolve_payload("REJECTED", outcome_note="Too early to say."),
                fx.make_evaluator_headers(env.reviewer["id"]),
            ),
            ApiErrorId.DISPUTE_NOT_RESOLVABLE.value,
            409,
        )
        validate_error(
            api.respond_dispute(
                env.dispute["id"],
                f.respond_payload("Adding detail nobody asked for."),
                fx.make_agent_headers(env.agent["id"]),
            ),
            ApiErrorId.DISPUTE_NOT_RESPONDABLE.value,
            409,
        )
        # The second filing carries the evaluation's current version, so the
        # concurrency rule passes and the duplicate rule is the one talking.
        current = fx.read_evaluation(api, env.evaluation["id"])
        validate_error(
            api.create_dispute(
                f.dispute_payload(
                    env.evaluation["id"],
                    current["version"],
                    disputed_behavior_codes=["GREET"],
                    rationale="A second, parallel complaint about the greeting.",
                ),
                fx.make_agent_headers(env.agent["id"]),
            ),
            ApiErrorId.DISPUTE_ALREADY_OPEN.value,
            409,
        )
        _, meta = validate_paginated(
            api.list_disputes(
                fx.make_quality_manager_headers(),
                {"evaluation_id": env.evaluation["id"]},
            )
        )
        assert meta["total_count"] == 1

    def test_the_author_may_not_review_and_the_pickup_is_not_repeatable(self, api):
        """A reviewable status is not enough if the actor wrote the score.

        PRD: "The dispute must be `SUBMITTED`, else `ERR_DISPUTE_NOT_REVIEWABLE`."
        PRD: "The acting `X-User-ID` must **differ** from the `evaluator_id` of the
        disputed evaluation, else `ERR_SEGREGATION_OF_DUTIES` — the evaluator who produced
        a score may never adjudicate its challenge."

        Design: Corner/validations/validation_dispute_state_rules_reject_every_out_of_turn_step
        """
        env = fx.disputed_evaluation_env(api)

        validate_error(
            api.review_dispute(
                env.dispute["id"], fx.make_evaluator_headers(env.evaluator["id"])
            ),
            ApiErrorId.SEGREGATION_OF_DUTIES.value,
            403,
        )
        picked_up = fx.review_dispute(api, env.dispute["id"], env.reviewer["id"])
        assert picked_up["status"] == "UNDER_REVIEW"
        assert picked_up["reviewer_evaluator_id"] == env.reviewer["id"]

        validate_error(
            api.review_dispute(
                env.dispute["id"], fx.make_evaluator_headers(env.reviewer["id"])
            ),
            ApiErrorId.DISPUTE_NOT_REVIEWABLE.value,
            409,
        )
        assert (
            fx.read_dispute(api, env.dispute["id"])["reviewer_evaluator_id"]
            == env.reviewer["id"]
        )

    def test_responding_becomes_legal_only_once_the_status_says_so(self, api):
        """The same call is refused under review and accepted after the request.

        PRD: "On success `status` becomes `NEEDS_MORE_INFO`, `outcome_note` is stored,
        and `reviewer_evaluator_id` is retained."
        PRD: "The payload carries `additional_rationale`, which is appended to the
        stored `rationale` separated by a space, a vertical bar and a space, so the full
        argument history is preserved on one field."
        PRD: "The evaluation's `feedback_status` deliberately stays `DISPUTED`: the
        information loop does not hand feedback back to the agent as fresh feedback."

        Design: Corner/validations/validation_dispute_state_rules_reject_every_out_of_turn_step
        """
        env = fx.under_review_dispute_env(api)
        answer = f.respond_payload("Minutes 04:10 to 05:00 of the recording.")
        validate_error(
            api.respond_dispute(
                env.dispute["id"], answer, fx.make_agent_headers(env.agent["id"])
            ),
            ApiErrorId.DISPUTE_NOT_RESPONDABLE.value,
            409,
        )

        asked = fx.resolve_dispute(
            api,
            env.dispute["id"],
            env.reviewer["id"],
            "NEEDS_MORE_INFO",
            outcome_note="Which part of the call are you referring to?",
        )
        assert asked["status"] == "NEEDS_MORE_INFO"
        assert asked["round_count"] == 1

        answered = validate_success(
            api.respond_dispute(
                env.dispute["id"], answer, fx.make_agent_headers(env.agent["id"])
            )
        )

        assert answered["status"] == "SUBMITTED"
        assert answered["reviewer_evaluator_id"] is None
        assert answered["round_count"] == 1
        assert answered["rationale"].endswith(
            " | Minutes 04:10 to 05:00 of the recording."
        )
        assert (
            fx.read_evaluation(api, env.evaluation["id"])["feedback_status"] == "DISPUTED"
        )


class TestSourceMixIsThreeNonNegativePartsOfOneHundred:
    """Four different ways to break one composite field, all answered by the
    same rule, and none of them creating a row."""

    SHORT_SUM = {"random_pct": 50, "targeted_pct": 25, "customer_flagged_pct": 20}
    OVER_SUM = {"random_pct": 50, "targeted_pct": 60, "customer_flagged_pct": 0}
    MISSING_KEY = {"random_pct": 100, "targeted_pct": 0}
    NEGATIVE_PART = {"random_pct": 110, "targeted_pct": -10, "customer_flagged_pct": 0}

    def test_short_over_missing_and_negative_all_answer_the_same_rule(self, api):
        """Even the mix that sums to exactly one hundred is refused.

        PRD: "`source_mix` is an object splitting that per-agent volume across the
        three sampling sources; it must carry exactly the three keys `random_pct`,
        `targeted_pct` and `customer_flagged_pct`, each a non-negative integer, and the
        three must sum to exactly `100`."
        PRD: "A missing key, a negative percentage, or a sum other than one hundred is
        rejected with `ERR_SOURCE_MIX_INVALID`."

        Design: Corner/validations/validation_source_mix_must_be_three_non_negative_parts_of_100
        """
        form = fx.create_active_form(api)
        headers = fx.make_quality_manager_headers()

        for mix in (self.SHORT_SUM, self.OVER_SUM, self.MISSING_KEY, self.NEGATIVE_PART):
            validate_error(
                api.create_plan(
                    f.sample_plan_payload(
                        form["id"], per_agent_target_volume=5, mix=mix
                    ),
                    headers,
                ),
                ApiErrorId.SOURCE_MIX_INVALID.value,
                422,
            )

        _, meta = validate_paginated(api.list_plans(headers, {"form_id": form["id"]}))
        assert meta["total_count"] == 0

    def test_the_well_formed_mix_is_stored_verbatim_on_a_draft_plan(self, api):
        """After four refusals the fifth payload creates the only row there is.

        PRD: "A drafted plan starts in `DRAFT` with `pinned_form_guidance_version`
        null, `selections_count` and `excluded_count` at `0`, `targeted_reserved_count` at
        `0`, and both `targeted_reserve_by_agent` and `agent_volume_attainment` as empty
        objects."

        Design: Corner/validations/validation_source_mix_must_be_three_non_negative_parts_of_100
        """
        form = fx.create_active_form(api)
        headers = fx.make_quality_manager_headers()
        for mix in (self.SHORT_SUM, self.OVER_SUM, self.MISSING_KEY, self.NEGATIVE_PART):
            validate_error(
                api.create_plan(
                    f.sample_plan_payload(
                        form["id"], per_agent_target_volume=5, mix=mix
                    ),
                    headers,
                ),
                ApiErrorId.SOURCE_MIX_INVALID.value,
                422,
            )

        plan = validate_success(
            api.create_plan(
                f.sample_plan_payload(
                    form["id"], per_agent_target_volume=5, mix=f.source_mix(50, 25, 25)
                ),
                headers,
            ),
            201,
        )

        assert plan["status"] == "DRAFT"
        assert plan["version"] == 1
        assert plan["source_mix"] == {
            "random_pct": 50,
            "targeted_pct": 25,
            "customer_flagged_pct": 25,
        }
        assert plan["pinned_form_guidance_version"] is None
        _, meta = validate_paginated(api.list_plans(headers, {"form_id": form["id"]}))
        assert meta["total_count"] == 1


class TestGuidanceBumpInAnotherEntityFreezesTheOpenPlan:
    """A calibration close is the only writer of the form's guidance revision,
    and the plan pinned that number when it opened."""

    NEW_GUIDANCE = "Confirm the agreed next step aloud before closing."
    ADJACENT_WINDOW = ("2026-08-05T11:00:00Z", "2026-08-05T13:00:00Z")

    @staticmethod
    def _open_plan_and_scoring_session_env(api):
        """An assigned selection inside an OPEN plan pinned at guidance 1, plus a
        calibration session in SCORING over a second contact benchmarked at 82.00."""
        env = fx.assigned_env(api)
        env.reviewer = fx.create_evaluator(api, full_name="Ravi Reviewer")
        env.specimen = fx.create_verified_interaction(
            api,
            env.agent["id"],
            started_at="2026-08-04T10:00:00Z",
            ended_at="2026-08-04T10:10:00Z",
            csat_score=3,
        )
        env.session = fx.create_session(api, env.form["id"], env.specimen["id"])
        env.session = fx.start_scoring(api, env.session["id"])
        assert env.plan["pinned_form_guidance_version"] == 1
        assert fx.read_form(api, env.form["id"])["guidance_version"] == 1
        assert env.session["status"] == "SCORING"
        return env

    def test_the_duplicate_rule_is_per_evaluator_and_scores_stay_unbanded(self, api):
        """One reading per evaluator, and no deviation until the close.

        PRD: "The session must be `SCORING`, else `ERR_SESSION_NOT_SCORING`, and an
        evaluator who has already submitted to this session is rejected with
        `ERR_SESSION_PARTICIPANT_DUPLICATE` — one reading per evaluator per session."
        PRD: "As noted in §2.4, a calibration submission is immutable: it carries no
        `version` and no `updated_at`, and there is no update endpoint for it."

        Design: Corner/validations/validation_guidance_bump_in_another_entity_freezes_the_open_plan
        """
        env = self._open_plan_and_scoring_session_env(api)

        first = fx.create_submission(
            api, env.session["id"], env.evaluator["id"], f.HIGH_ITEM_SCORES_89
        )
        assert first["deviation_pct"] is None
        assert first["alignment"] is None
        assert "version" not in first
        assert "updated_at" not in first

        validate_error(
            api.create_submission(
                f.calibration_submission_payload(
                    env.session["id"], f.HIGH_ITEM_SCORES_90
                ),
                fx.make_evaluator_headers(env.evaluator["id"]),
            ),
            ApiErrorId.SESSION_PARTICIPANT_DUPLICATE.value,
            409,
        )
        _, meta = validate_paginated(
            api.list_submissions(
                fx.make_quality_manager_headers(), {"session_id": env.session["id"]}
            )
        )
        assert meta["total_count"] == 1

        second = fx.create_submission(
            api, env.session["id"], env.reviewer["id"], f.PASSING_ITEM_SCORES
        )
        assert second["evaluator_id"] == env.reviewer["id"]
        assert fx.read_session(api, env.session["id"])["participant_count"] == 2

    def test_the_aligned_close_bands_both_readings_and_bumps_the_form_once(self, api):
        """89.00 against an 82.00 benchmark is a seven-point minor variance.

        PRD: "Each submission's `alignment` is then banded on the absolute value of
        that rounded deviation: `ALIGNED` when the absolute deviation is at most `3.00`,
        `MINOR_VARIANCE` when it is greater than `3.00` and at most `7.00`, and
        `MAJOR_VARIANCE` when it is greater than `7.00`."
        PRD: "At session level, `participant_count` is the number of submissions,
        `variance_pct` is the largest absolute deviation rounded half up to two decimals,
        and `mean_abs_deviation` is the sum of the absolute deviations divided by the number
        of submissions, rounded half up to two decimals."
        PRD: "**Step four:** for each entry of `guidance_updates`, the named behaviour's
        `guidance_text` is replaced with the supplied text and that behaviour's own
        `guidance_version` increases by one; `guidance_updates_applied` is set to the number
        of entries; and when the list is non-empty the **form-level** `guidance_version`
        increases by exactly one, no matter how many behaviours were rewritten."

        Design: Corner/validations/validation_guidance_bump_in_another_entity_freezes_the_open_plan
        """
        env = self._open_plan_and_scoring_session_env(api)
        harsh = fx.create_submission(
            api, env.session["id"], env.evaluator["id"], f.HIGH_ITEM_SCORES_89
        )
        exact = fx.create_submission(
            api, env.session["id"], env.reviewer["id"], f.PASSING_ITEM_SCORES
        )

        closed = fx.close_session(
            api,
            env.session["id"],
            [f.guidance_update("RESOLVE", self.NEW_GUIDANCE)],
        )

        assert closed["status"] == "CLOSED_ALIGNED"
        assert closed["participant_count"] == 2
        # 89.00 - 82.00 = 7.00 against 82.00 - 82.00 = 0.00.
        assert_money(closed["variance_pct"], 7.00)
        assert_money(closed["mean_abs_deviation"], 3.50)
        assert closed["guidance_updates_applied"] == 1
        banded = fx.read_submission(api, harsh["id"])
        assert_money(banded["deviation_pct"], 7.00)
        assert banded["alignment"] == "MINOR_VARIANCE"
        aligned = fx.read_submission(api, exact["id"])
        assert_money(aligned["deviation_pct"], 0.00)
        assert aligned["alignment"] == "ALIGNED"
        assert fx.read_form(api, env.form["id"])["guidance_version"] == 2
        behaviors = fx.list_data(
            api.list_form_behaviors(env.form["id"], fx.make_quality_manager_headers())
        )
        rewritten = [b for b in behaviors if b["code"] == "RESOLVE"][0]
        assert rewritten["guidance_text"] == self.NEW_GUIDANCE
        assert rewritten["guidance_version"] == 2
        # An aligned close can only restore probationary standing.
        for evaluator_id in (env.evaluator["id"], env.reviewer["id"]):
            assert (
                fx.read_evaluator(api, evaluator_id)["calibration_status"] == "CALIBRATED"
            )

    def test_the_bumped_form_freezes_the_pinned_plan_but_not_a_fresh_one(self, api):
        """The same evaluator, agent and contact pass once a plan pins guidance 2.

        PRD: "The session must be `SCORING`, else `ERR_SESSION_NOT_SCORING`."
        PRD: "The selection must be in status `ASSIGNED`, else
        `ERR_SELECTION_NOT_ASSIGNABLE`; its `assigned_evaluator_id` must equal the acting
        `X-User-ID`, else `ERR_NOT_RESOURCE_OWNER`; its interaction must satisfy the consent
        gate of §2.8; and the plan's pinned guidance revision must still equal the form's
        current `guidance_version`, else `ERR_GUIDANCE_VERSION_STALE`."
        PRD: "Opening the plan moves it `DRAFT → OPEN`, and the transition is where
        pinning happens: `pinned_form_guidance_version` captures the form's
        `guidance_version` at that instant, the overlap check is re-run against sibling
        plans, and the plan's `version` is incremented."

        Design: Corner/validations/validation_guidance_bump_in_another_entity_freezes_the_open_plan
        """
        env = self._open_plan_and_scoring_session_env(api)
        fx.create_submission(
            api, env.session["id"], env.evaluator["id"], f.HIGH_ITEM_SCORES_89
        )
        fx.create_submission(
            api, env.session["id"], env.reviewer["id"], f.PASSING_ITEM_SCORES
        )
        fx.close_session(
            api, env.session["id"], [f.guidance_update("RESOLVE", self.NEW_GUIDANCE)]
        )

        validate_error(
            api.create_submission(
                f.calibration_submission_payload(
                    env.session["id"], f.PASSING_ITEM_SCORES
                ),
                fx.make_evaluator_headers(env.reviewer["id"]),
            ),
            ApiErrorId.SESSION_NOT_SCORING.value,
            409,
        )
        validate_error(
            api.create_evaluation(
                f.evaluation_payload(env.selection["id"]),
                fx.make_evaluator_headers(env.evaluator["id"]),
            ),
            ApiErrorId.GUIDANCE_VERSION_STALE.value,
            409,
        )
        assert fx.read_selection(api, env.selection["id"])["status"] == "ASSIGNED"
        _, no_evaluations = validate_paginated(
            api.list_evaluations(fx.make_quality_manager_headers())
        )
        assert no_evaluations["total_count"] == 0

        fx.close_plan(api, env.plan["id"])
        fresh = fx.create_open_plan(api, env.form["id"])
        assert fresh["pinned_form_guidance_version"] == 2
        replacement = fx.assign_selection(
            api,
            fx.create_selection(api, fresh["id"], env.interaction["id"], "RANDOM")["id"],
            env.evaluator["id"],
            review_window_start=self.ADJACENT_WINDOW[0],
            review_window_end=self.ADJACENT_WINDOW[1],
        )
        evaluation = fx.open_evaluation(api, replacement["id"], env.evaluator["id"])

        assert evaluation["pinned_guidance_version"] == 2
        assert evaluation["review_status"] == "DRAFT"


class TestEscalationWaitsForTheDueDateToTheSecond:
    """A T1 plan with no standing findings has exactly one route to escalation,
    and it opens at the due instant itself."""

    ONE_SECOND_EARLY = "2026-09-04T08:59:59Z"
    DUE_AT = "2026-09-04T09:00:00Z"

    def test_neither_route_is_open_at_creation_or_one_second_before_due(self, api):
        """The comparison is the clock against the instant, not the calendar day.

        PRD: "Beyond the terminal-status check, escalation requires **either** that the
        logical clock has reached or passed the plan's `due_at`, **or** that the agent's
        `open_compliance_findings` is at least two — an agent with two or more standing
        findings may be escalated immediately, before the due date."
        PRD: "Fifth, `due_at` is the current logical-clock instant plus the tier's
        allowance: thirty days for `T1`, forty-five days for `T2`, sixty days for `T3`."

        Design: Corner/validations/validation_escalation_waits_for_the_due_date_to_the_second
        """
        env = fx.coaching_plan_env(api, target_score=85.00)
        plan = env.coaching_plan
        assert plan["status"] == "ASSIGNED"
        assert plan["escalation_tier"] == "T1"
        assert plan["required_session_count"] == 2
        assert_instant(plan["due_at"], self.DUE_AT)
        assert env.agent["open_compliance_findings"] == 0
        assert env.agent["coaching_state"] == "ACTIVE"

        validate_error(
            api.escalate_coaching_plan(
                plan["id"],
                f.escalate_payload("Escalating on day one."),
                fx.make_quality_manager_headers(),
            ),
            ApiErrorId.ESCALATION_NOT_DUE.value,
            422,
        )

        fx.set_clock(api, self.ONE_SECOND_EARLY)
        validate_error(
            api.escalate_coaching_plan(
                plan["id"],
                f.escalate_payload("One second early."),
                fx.make_quality_manager_headers(),
            ),
            ApiErrorId.ESCALATION_NOT_DUE.value,
            422,
        )
        assert fx.read_coaching_plan(api, plan["id"])["status"] == "ASSIGNED"

    def test_the_due_instant_escalates_to_tier_three_and_closes_the_plan(self, api):
        """The forced tier does not resize the plan, and nothing may follow it.

        PRD: "On success `status` becomes `ESCALATED`, `escalation_note` is stored, and
        `escalation_tier` is forced to `T3` regardless of what the original sizing computed."
        PRD: "The agent's `coaching_state` is deliberately left unchanged, because an
        escalated plan is still an active intervention rather than a resolved one."
        PRD: "The plan's `status` must be `ASSIGNED` or `IN_PROGRESS`, else
        `ERR_COACHING_PLAN_TERMINAL`."

        Design: Corner/validations/validation_escalation_waits_for_the_due_date_to_the_second
        """
        env = fx.coaching_plan_env(api, target_score=85.00)
        plan_id = env.coaching_plan["id"]
        agent_version_before = fx.read_agent(api, env.agent["id"])["version"]
        fx.set_clock(api, self.DUE_AT)

        escalated = validate_success(
            api.escalate_coaching_plan(
                plan_id,
                f.escalate_payload("Due date reached with no sessions logged."),
                fx.make_quality_manager_headers(),
            )
        )

        assert escalated["status"] == "ESCALATED"
        assert escalated["escalation_tier"] == "T3"
        assert escalated["escalation_note"] == "Due date reached with no sessions logged."
        # The sizing the calculation produced survives the forced tier.
        assert escalated["required_session_count"] == 2
        assert escalated["completed_session_count"] == 0
        assert_instant(escalated["due_at"], self.DUE_AT)
        agent = fx.read_agent(api, env.agent["id"])
        assert agent["coaching_state"] == "ACTIVE"
        assert agent["version"] == agent_version_before

        validate_error(
            api.escalate_coaching_plan(
                plan_id,
                f.escalate_payload("Escalating a second time."),
                fx.make_quality_manager_headers(),
            ),
            ApiErrorId.COACHING_PLAN_TERMINAL.value,
            409,
        )
        validate_error(
            api.log_coaching_session(
                plan_id,
                f.log_session_payload(
                    "2026-09-04T10:00:00Z", session_note="Too late to coach."
                ),
                fx.make_supervisor_headers(),
            ),
            ApiErrorId.COACHING_PLAN_TERMINAL.value,
            409,
        )
        assert fx.read_coaching_plan(api, plan_id)["completed_session_count"] == 0
