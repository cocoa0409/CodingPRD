"""The four computed figures of this domain — the screening risk score, the
scorecard weight total, the quota waterfall and the agent's quality
aggregates — pinned against inputs whose answers were worked out by hand."""
from test_helpers import (
    ApiErrorId,
    assert_agent_index,
    assert_attainment,
    assert_money,
    assert_plan_counters,
    assert_scores,
    assert_summary_figures,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)

NOW = "2026-08-05T09:00:00Z"


class TestScreeningRiskScoreOnKnownInputs:
    """One screening exercises every term of the formula at once."""

    @staticmethod
    def _voice_contact_with_a_disclosure_gap(api):
        """A recorded voice contact whose required disclosure has not yet been
        confirmed, so the gap bonus is live."""
        fx.set_clock(api, NOW)
        agent = fx.create_agent(api)
        interaction = fx.create_interaction(
            api, agent["id"], channel="VOICE", required_disclosures=["RECORDING"]
        )
        return fx.Env(agent=agent, interaction=interaction)

    def test_every_term_of_the_risk_formula_lands_on_eighty_four(self, api):
        """Silence, sentiment, a category hit, the channel and the gap bonus.

        PRD: "First an unrounded base figure is formed by adding three terms: the
        `silence_pct` multiplied by forty-five hundredths; the sentiment penalty, which is
        the negated `sentiment_delta` floored at zero — so a positive or zero
        `sentiment_delta` contributes nothing — multiplied by one hundred and then by
        thirty-five hundredths; and the sum of the category points of every entry in
        `flagged_categories`, where `PROFANITY` is worth twenty-five points,
        `NO_DISCLOSURE` thirty points, `ESCALATION_REQUEST` fifteen points and
        `CONSENT_OBJECTION` forty points."
        PRD: "Second, a disclosure-gap bonus of fifteen points applies when the
        interaction's `required_disclosures` is non-empty **and** at least one required
        code is missing from the interaction's `captured_disclosures`; otherwise the bonus
        is zero."
        PRD: "Third, the capped base is multiplied by the channel multiplier — one and
        twenty hundredths for `VOICE`, exactly one for `CHAT`, and eighty hundredths for
        `EMAIL` — the disclosure-gap bonus is added to that product, the result is capped
        at `100.00`, and only then is a single rounding to two decimals applied half up."
        PRD: "`priority_tier` then bands the result: `P1` when `risk_score` is at least
        `70.00`, `P2` when `risk_score` is at least `40.00` but below `70.00`, and `P3`
        when `risk_score` is below `40.00`."

        Design: Corner/calculations/calc_analytics_priority_score_known_inputs
        """
        env = self._voice_contact_with_a_disclosure_gap(api)

        scan = fx.create_scan(
            api,
            env.interaction["id"],
            env.interaction["version"],
            silence_pct=30.00,
            sentiment_delta=-0.40,
            flagged_categories=["NO_DISCLOSURE"],
        )

        # 13.50 + 14.00 + 30 = 57.50 base; 57.50 * 1.20 = 69.00; + 15 = 84.00.
        assert_money(scan["risk_score"], 84.00)
        assert scan["priority_tier"] == "P1"
        assert scan["status"] == "CURRENT"
        assert scan["interaction_id"] == env.interaction["id"]
        assert scan["flagged_categories"] == ["NO_DISCLOSURE"]

    def test_the_screening_echoes_its_inputs_and_never_reviews_consent(self, api):
        """A scan measures the contact; it does not adjudicate it.

        PRD: "The screening reads the interaction's `channel`, `required_disclosures`
        and `captured_disclosures` as they stand at the instant of the call and never
        re-reads them: a consent review that later fills in the captured disclosures does
        not retroactively lower an existing scan's `risk_score` or move its tier."
        PRD: "Consent adjudication belongs exclusively to the `ComplianceAuditor`, and
        it is the one place where `recording_consent_status` moves."

        Design: Corner/calculations/calc_analytics_priority_score_known_inputs
        """
        env = self._voice_contact_with_a_disclosure_gap(api)

        scan = fx.create_scan(
            api,
            env.interaction["id"],
            env.interaction["version"],
            silence_pct=30.00,
            sentiment_delta=-0.40,
            flagged_categories=["NO_DISCLOSURE"],
        )

        assert_money(scan["silence_pct"], 30.00)
        assert_money(scan["sentiment_delta"], -0.40)
        interaction = fx.read_interaction(api, env.interaction["id"])
        assert interaction["recording_consent_status"] == "PENDING"
        assert interaction["captured_disclosures"] == []
        # The screening moved the parent contact's version and nothing else.
        assert interaction["version"] == env.interaction["version"] + 1


class TestScreeningConstantsAndTheDoubleHundredCap:
    """The declared channel multipliers and the two separate clamps."""

    @staticmethod
    def _agent_and_three_contacts(api):
        """A chat, an email and a voice contact of the same agent."""
        fx.set_clock(api, NOW)
        agent = fx.create_agent(api)
        chat = fx.create_interaction(api, agent["id"], channel="CHAT")
        email = fx.create_interaction(api, agent["id"], channel="EMAIL")
        voice = fx.create_interaction(
            api, agent["id"], channel="VOICE", required_disclosures=["RECORDING"]
        )
        return fx.Env(agent=agent, chat=chat, email=email, voice=voice)

    def test_the_same_metrics_diverge_by_exactly_the_channel_multiplier(self, api):
        """One base figure, two channels, two declared constants.

        PRD: "Third, the capped base is multiplied by the channel multiplier — one and
        twenty hundredths for `VOICE`, exactly one for `CHAT`, and eighty hundredths for
        `EMAIL` — the disclosure-gap bonus is added to that product, the result is capped
        at `100.00`, and only then is a single rounding to two decimals applied half up."
        PRD: "`priority_tier` then bands the result: `P1` when `risk_score` is at least
        `70.00`, `P2` when `risk_score` is at least `40.00` but below `70.00`, and `P3`
        when `risk_score` is below `40.00`."

        Design: Corner/calculations/calc_constants_channel_multiplier_and_hundred_cap
        """
        env = self._agent_and_three_contacts(api)
        metrics = dict(
            silence_pct=20.00, sentiment_delta=-0.50, flagged_categories=["PROFANITY"]
        )

        chat_scan = fx.create_scan(
            api, env.chat["id"], env.chat["version"], **metrics
        )
        email_scan = fx.create_scan(
            api, env.email["id"], env.email["version"], **metrics
        )

        # Base 9.00 + 17.50 + 25 = 51.50 with no disclosure gap on either row.
        assert_money(chat_scan["risk_score"], 51.50)
        assert chat_scan["priority_tier"] == "P2"
        assert_money(email_scan["risk_score"], 41.20)
        assert email_scan["priority_tier"] == "P2"
        assert email_scan["risk_score"] < chat_scan["risk_score"]
        assert chat_scan["status"] == "CURRENT"
        assert email_scan["status"] == "CURRENT"

    def test_a_runaway_screening_is_clamped_before_and_after_the_multiplier(self, api):
        """One hundred and ten category points still land on one hundred.

        PRD: "That base figure is capped at one hundred, still unrounded."
        PRD: "Both the inner cap and the channel multiplication are performed on
        unrounded values; `risk_score` is the only rounded figure."
        PRD: "From those inputs the server computes `risk_score`, a number from `0.00`
        to `100.00`."

        Design: Corner/calculations/calc_constants_channel_multiplier_and_hundred_cap
        """
        env = self._agent_and_three_contacts(api)

        scan = fx.create_scan(
            api,
            env.voice["id"],
            env.voice["version"],
            silence_pct=100.00,
            sentiment_delta=-1.00,
            flagged_categories=[
                "PROFANITY",
                "NO_DISCLOSURE",
                "ESCALATION_REQUEST",
                "CONSENT_OBJECTION",
            ],
        )

        # 45.00 + 35.00 + 110 = 190.00 clamps to 100; 100 * 1.20 + 15 = 135.00
        # clamps again.
        assert_money(scan["risk_score"], 100.00)
        assert scan["priority_tier"] == "P1"
        assert scan["risk_score"] <= 100.00


class TestScorecardWeightTotalIsCheckedAtExactlyOneHundred:
    """Two-decimal arithmetic, and the declared order of the three set checks."""

    #: A cover that is one hundredth short of the required total.
    SHORT_BEHAVIORS = [
        f.behavior_payload(
            "DISCLOSE",
            30.00,
            compliance_critical=True,
            auto_fail_on_violation=True,
        ),
        f.behavior_payload("GREET", 20.00),
        f.behavior_payload("RESOLVE", 35.00),
        f.behavior_payload("SURVEY", 14.99, allows_not_applicable=True),
    ]

    def test_a_total_of_ninety_nine_ninety_nine_is_refused_and_the_fix_is_accepted(self, api):
        """One hundredth short is short.

        PRD: "The `weight_pct` values must sum to exactly `100.00`, or the form is
        rejected with `ERR_WEIGHTS_NOT_100`."
        PRD: "A freshly created form is born in `DRAFT` with `behavior_weight_total` set
        to the sum of its behaviours' `weight_pct` values carried to two decimals,
        `compliance_behavior_count` set to the number of behaviours flagged
        compliance-critical, a form-level `guidance_version` of `1`, and both
        `activated_at` and `retired_at` null."

        Design: Corner/calculations/calc_weighted_scoring_weights_must_total_one_hundred
        """
        fx.set_clock(api, NOW)

        response = api.create_form(
            f.evaluation_form_payload(behaviors=self.SHORT_BEHAVIORS),
            fx.make_quality_manager_headers(),
        )

        validate_error(response, ApiErrorId.WEIGHTS_NOT_100.value, 422)
        _, empty = validate_paginated(api.list_forms(fx.make_quality_manager_headers()))
        assert empty["total_count"] == 0

        corrected = validate_success(
            api.create_form(
                f.evaluation_form_payload(behaviors=f.CANONICAL_BEHAVIORS),
                fx.make_quality_manager_headers(),
            ),
            201,
        )

        assert_money(corrected["behavior_weight_total"], 100.00)
        assert corrected["compliance_behavior_count"] == 1
        assert corrected["status"] == "DRAFT"
        _, meta = validate_paginated(api.list_forms(fx.make_quality_manager_headers()))
        assert meta["total_count"] == 1

    def test_the_weight_check_runs_before_the_compliance_and_uniqueness_checks(self, api):
        """Two covers that total one hundred and still fail, each on its own rule.

        PRD: "At least one behaviour must have `compliance_critical` set to `true`, or
        the form is rejected with `ERR_NO_COMPLIANCE_BEHAVIOR` — a scorecard with no
        compliance-critical item cannot express a compliance verdict."
        PRD: "And behaviour codes must be unique within the form, compared
        case-sensitively, or the form is rejected with `ERR_DUPLICATE_BEHAVIOR_CODE`."

        Design: Corner/calculations/calc_weighted_scoring_weights_must_total_one_hundred
        """
        fx.set_clock(api, NOW)

        validate_error(
            api.create_form(
                f.evaluation_form_payload(
                    auto_fail_policy="ZERO_TOTAL",
                    behaviors=[
                        f.behavior_payload("GREET", 50.00),
                        f.behavior_payload("RESOLVE", 50.00),
                    ],
                ),
                fx.make_quality_manager_headers(),
            ),
            ApiErrorId.NO_COMPLIANCE_BEHAVIOR.value,
            422,
        )
        validate_error(
            api.create_form(
                f.evaluation_form_payload(
                    auto_fail_policy="ZERO_TOTAL",
                    behaviors=[
                        f.behavior_payload(
                            "DISCLOSE",
                            50.00,
                            compliance_critical=True,
                            auto_fail_on_violation=True,
                        ),
                        f.behavior_payload(
                            "DISCLOSE", 50.00, label="Second disclosure row"
                        ),
                    ],
                ),
                fx.make_quality_manager_headers(),
            ),
            ApiErrorId.DUPLICATE_BEHAVIOR_CODE.value,
            422,
        )

        _, meta = validate_paginated(api.list_forms(fx.make_quality_manager_headers()))
        assert meta["total_count"] == 0


class TestQuotaWaterfallRemainderLandsEntirelyOnRandom:
    """Five slots split 50/25/25 give floors of two, one and one, and the one
    leftover slot belongs to RANDOM alone."""

    @staticmethod
    def _five_slot_plan_env(api):
        """An OPEN plan of five per agent over a mix of 50/25/25, with four
        consent-cleared contacts of which the last is customer-flagged."""
        env = fx.program_env(
            api, per_agent_target_volume=5, mix=f.source_mix(50, 25, 25)
        )
        env.interaction2 = fx.create_verified_interaction(
            api,
            env.agent["id"],
            started_at="2026-08-03T11:00:00Z",
            ended_at="2026-08-03T11:10:00Z",
            csat_score=3,
        )
        env.interaction3 = fx.create_verified_interaction(
            api,
            env.agent["id"],
            started_at="2026-08-04T10:00:00Z",
            ended_at="2026-08-04T10:10:00Z",
            csat_score=5,
        )
        env.flagged = fx.create_verified_interaction(
            api,
            env.agent["id"],
            started_at="2026-08-04T14:00:00Z",
            ended_at="2026-08-04T14:10:00Z",
            csat_score=2,
            customer_flagged=True,
        )
        return env

    def test_random_takes_three_pulls_and_refuses_the_fourth_on_the_mix_gate(self, api):
        """Two from the floor plus the whole remainder, and no more.

        PRD: "A base cap per source is the plan's `per_agent_target_volume`
        multiplied by that source's percentage from `source_mix`, divided by one hundred
        and rounded **down** to a whole number."
        PRD: "Because three floors can lose units, a remainder is formed as the
        `per_agent_target_volume` minus the sum of the three base caps, and the whole
        remainder is added to the `RANDOM` cap — it is never split across sources and
        never lands on `TARGETED` or `CUSTOMER_FLAGGED`."
        PRD: "Finally the two quota gates fire in order: the agent's `consumed` count
        for this plan must be strictly below `per_agent_target_volume` plus their targeted
        reserve, else `ERR_AGENT_QUOTA_EXCEEDED`; and the consumed count for the requested
        source must be strictly below that source's effective cap, else
        `ERR_SOURCE_MIX_EXCEEDED`."

        Design: Corner/calculations/calc_waterfall_remainder_lands_entirely_on_random
        """
        env = self._five_slot_plan_env(api)

        for interaction in (env.interaction, env.interaction2, env.interaction3):
            fx.create_selection(api, env.plan["id"], interaction["id"], "RANDOM")

        overflow = api.create_selection(
            f.sample_selection_payload(
                env.plan["id"], env.flagged["id"], source="RANDOM"
            ),
            fx.make_quality_manager_headers(),
        )

        # Consumed is 3 against a per-agent target of 5, so the agent gate passes
        # and only the source gate can fire.
        validate_error(overflow, ApiErrorId.SOURCE_MIX_EXCEEDED.value, 422)
        assert_attainment(
            fx.read_plan(api, env.plan["id"]),
            env.agent["id"],
            consumed=3,
            remaining=2,
            by_source={"RANDOM": 3, "TARGETED": 0, "CUSTOMER_FLAGGED": 0},
        )

    def test_the_flagged_source_keeps_its_own_slot_through_the_random_overflow(self, api):
        """One source running out says nothing about another.

        PRD: "The effective `CUSTOMER_FLAGGED` cap is exactly its base cap."
        PRD: "Those three figures are published per agent inside
        `agent_volume_attainment` as an object with `consumed`, `remaining` and a
        `by_source` breakdown keyed by `RANDOM`, `TARGETED` and `CUSTOMER_FLAGGED`."
        PRD: "At plan level, `selections_count` is the number of selections of the plan
        in status `SELECTED`, `ASSIGNED` or `EVALUATED`; `excluded_count` is the number in
        status `EXCLUDED`; and `targeted_reserved_count` is the sum of all values in
        `targeted_reserve_by_agent`."

        Design: Corner/calculations/calc_waterfall_remainder_lands_entirely_on_random
        """
        env = self._five_slot_plan_env(api)
        for interaction in (env.interaction, env.interaction2, env.interaction3):
            fx.create_selection(api, env.plan["id"], interaction["id"], "RANDOM")
        validate_error(
            api.create_selection(
                f.sample_selection_payload(
                    env.plan["id"], env.flagged["id"], source="RANDOM"
                ),
                fx.make_quality_manager_headers(),
            ),
            ApiErrorId.SOURCE_MIX_EXCEEDED.value,
            422,
        )

        flagged_pull = fx.create_selection(
            api, env.plan["id"], env.flagged["id"], "CUSTOMER_FLAGGED"
        )

        assert flagged_pull["source"] == "CUSTOMER_FLAGGED"
        assert flagged_pull["status"] == "SELECTED"
        plan = fx.read_plan(api, env.plan["id"])
        assert_attainment(
            plan,
            env.agent["id"],
            consumed=4,
            remaining=1,
            by_source={"RANDOM": 3, "TARGETED": 0, "CUSTOMER_FLAGGED": 1},
        )
        assert_plan_counters(
            plan, selections_count=4, excluded_count=0, targeted_reserved_count=0
        )


class TestDraftEvaluationsStayOutOfTheIndexPopulation:
    """A scored row and a DRAFT row on the same agent, and only one of them is
    allowed to move a number."""

    @staticmethod
    def _one_scored_one_draft(api):
        """One submitted evaluation at 82.00 and a second evaluation left in
        DRAFT on a repeat contact."""
        env = fx.program_env(
            api, per_agent_target_volume=4, mix=dict(f.ALL_RANDOM_MIX)
        )
        env.interaction2 = fx.create_verified_interaction(
            api,
            env.agent["id"],
            started_at="2026-08-04T10:00:00Z",
            ended_at="2026-08-04T10:10:00Z",
            csat_score=3,
            repeat_contact_within_72h=True,
        )
        env.selection = fx.create_selection(
            api, env.plan["id"], env.interaction["id"], "RANDOM"
        )
        fx.assign_selection(api, env.selection["id"], env.evaluator["id"])
        env.evaluation = fx.open_evaluation(
            api, env.selection["id"], env.evaluator["id"]
        )
        env.evaluation = fx.submit_evaluation(
            api, env.evaluation["id"], env.evaluator["id"]
        )
        env.selection2 = fx.create_selection(
            api, env.plan["id"], env.interaction2["id"], "RANDOM"
        )
        fx.assign_selection(api, env.selection2["id"], env.evaluator["id"])
        env.draft = fx.open_evaluation(
            api, env.selection2["id"], env.evaluator["id"]
        )
        return env

    def test_the_summary_counts_one_evaluation_and_never_sees_the_draft(self, api):
        """A repeat contact scored nowhere is a repeat contact counted nowhere.

        PRD: "Both draw on the same population — every evaluation of that agent whose
        `review_status` is `SUBMITTED`, `FINALIZED` or `REOPENED` and whose
        `weighted_score` is not null."
        PRD: "`DRAFT` evaluations never contribute, and an excluded selection
        contributes nothing because it never produces an evaluation at all."
        PRD: "`repeat_contact_rate` is the count of evaluations whose interaction has
        `repeat_contact_within_72h` set to `true`, divided by the size of the population,
        multiplied by one hundred and rounded half up to two decimals."

        Design: Corner/calculations/calc_index_input_set_excludes_draft_evaluations
        """
        env = self._one_scored_one_draft(api)

        summary = fx.read_quality_summary(api, env.agent["id"])

        assert_summary_figures(
            summary,
            rolling=82.00,
            period=82.00,
            evaluations_considered=1,
            paired_sample_size=1,
            repeat_contact_rate=0.00,
        )
        draft = fx.read_evaluation(api, env.draft["id"])
        assert draft["review_status"] == "DRAFT"
        assert draft["weighted_score"] is None

    def test_a_lone_low_scorer_leaves_both_satisfaction_gaps_null(self, api):
        """With an empty high partition neither treatment has a subtraction.

        PRD: "`csat_gap_paired` is null whenever either side has no non-null
        `csat_score` at all."
        PRD: "Under the imputed treatment, reported as `csat_gap_all`, the identical
        computation is performed with every null `csat_score` replaced by the imputed value
        `3`, so no interaction is dropped; `csat_gap_all` is null only when the high group
        or the low group is empty."
        PRD: "It is the length of the trailing run of the agent's evaluations, ordered
        by `submitted_at` ascending with `created_at` ascending as the tie-break, whose
        `compliance_result` is `PASS` and whose effective score is at least `85.00`; any
        evaluation with a `FAIL` verdict or a score below `85.00` resets it to `0`."

        Design: Corner/calculations/calc_index_input_set_excludes_draft_evaluations
        """
        env = self._one_scored_one_draft(api)
        assert_scores(env.evaluation, weighted_score=82.00, compliance_result="PASS")

        summary = fx.read_quality_summary(api, env.agent["id"])

        assert_summary_figures(summary, csat_gap_paired=None, csat_gap_all=None)
        # 82.00 is a PASS but sits below the 85.00 floor, so the trailing run is empty.
        assert_agent_index(
            fx.read_agent(api, env.agent["id"]),
            rolling=82.00,
            consecutive_passing_evaluations=0,
        )


class TestCorrelationAggregatesOverThreeScoredEvaluations:
    """Seven aggregates read out of one summary over a pass, an auto-fail and a
    not-applicable row."""

    @staticmethod
    def _three_scored_evaluations(api):
        """Three ten-minute contacts of one agent scored 93.00, 52.00 and 78.82,
        carrying csat 5, csat 2 with a repeat contact, and no survey at all."""
        env = fx.program_env(
            api, per_agent_target_volume=4, mix=dict(f.ALL_RANDOM_MIX), csat_score=5
        )
        env.interaction2 = fx.create_verified_interaction(
            api,
            env.agent["id"],
            started_at="2026-08-03T11:00:00Z",
            ended_at="2026-08-03T11:10:00Z",
            csat_score=2,
            repeat_contact_within_72h=True,
        )
        env.interaction3 = fx.create_verified_interaction(
            api,
            env.agent["id"],
            started_at="2026-08-04T10:00:00Z",
            ended_at="2026-08-04T10:10:00Z",
            include_csat=False,
        )
        scored = []
        pairs = [
            (env.interaction, f.HIGH_ITEM_SCORES_93),
            (env.interaction2, f.AUTO_FAIL_ITEM_SCORES),
            (env.interaction3, f.NA_ITEM_SCORES),
        ]
        for interaction, item_scores in pairs:
            selection = fx.create_selection(
                api, env.plan["id"], interaction["id"], "RANDOM"
            )
            fx.assign_selection(api, selection["id"], env.evaluator["id"])
            evaluation = fx.open_evaluation(api, selection["id"], env.evaluator["id"])
            scored.append(
                fx.submit_evaluation(
                    api, evaluation["id"], env.evaluator["id"], item_scores
                )
            )
        env.evaluation1, env.evaluation2, env.evaluation3 = scored
        return env

    def test_the_three_scores_come_out_as_the_arithmetic_demands(self, api):
        """The population the aggregates run over, pinned row by row.

        PRD: "Within that population, an evaluation's **effective score** is its
        `adjusted_weighted_score` when that field is not null, and otherwise its
        `weighted_score` — an upheld dispute's adjustment always wins over the original."
        PRD: "**Step four:** the agent's `quality_index_rolling` and
        `quality_index_period` are recomputed as described in §3.9, and
        `consecutive_passing_evaluations` is recomputed."
        PRD: "It is the length of the trailing run of the agent's evaluations, ordered
        by `submitted_at` ascending with `created_at` ascending as the tie-break, whose
        `compliance_result` is `PASS` and whose effective score is at least `85.00`; any
        evaluation with a `FAIL` verdict or a score below `85.00` resets it to `0`."

        Design: Corner/calculations/calc_correlation_aggregates_over_three_scored_evaluations
        """
        env = self._three_scored_evaluations(api)

        assert_scores(
            env.evaluation1, weighted_score=93.00, compliance_result="PASS"
        )
        assert_scores(
            env.evaluation2,
            weighted_score=52.00,
            auto_fail_triggered=True,
            compliance_result="FAIL",
        )
        assert_scores(
            env.evaluation3, weighted_score=78.82, raw_weighted_score=82.00
        )
        # The final row scores below the 85.00 floor, so the trailing run is empty.
        assert_agent_index(
            fx.read_agent(api, env.agent["id"]),
            rolling=74.61,
            open_compliance_findings=1,
            consecutive_passing_evaluations=0,
            coaching_state="REQUIRED",
        )

    def test_one_supervisor_read_returns_all_seven_consistent_figures(self, api):
        """Rolling, period, both gaps, both counts and the repeat rate at once.

        PRD: "`quality_index_rolling` is the unweighted mean of the four most recent
        effective scores."
        PRD: "Otherwise it is the sum, over the subset, of each evaluation's effective
        score multiplied by its interaction's `duration_seconds`, divided by the total
        `duration_seconds` of the subset, rounded half up to two decimals."
        PRD: "Under the paired-only treatment, reported as `csat_gap_paired`, the mean
        `csat_score` of the high group is computed over only those high-group interactions
        whose `csat_score` is not null and rounded half up to two decimals; the same is done
        for the low group; and `csat_gap_paired` is the high mean minus the low mean,
        rounded half up to two decimals — each mean is rounded **before** the subtraction."
        PRD: "A per-agent quality summary is computed on demand for the
        `QualityManager`, `Supervisor` and `ComplianceAuditor`, and nothing it produces is
        persisted."

        Design: Corner/calculations/calc_correlation_aggregates_over_three_scored_evaluations
        """
        env = self._three_scored_evaluations(api)
        before = fx.read_agent(api, env.agent["id"])

        summary = validate_success(
            api.get_quality_summary(env.agent["id"], fx.make_supervisor_headers())
        )

        # (93.00 + 52.00 + 78.82) / 3 = 74.6066... on both indices, because all
        # three contacts ran for the same six hundred seconds.
        assert_summary_figures(
            summary,
            rolling=74.61,
            period=74.61,
            evaluations_considered=3,
            paired_sample_size=2,
            csat_gap_paired=3.00,
            csat_gap_all=2.50,
            repeat_contact_rate=33.33,
        )
        assert fx.read_agent(api, env.agent["id"])["version"] == before["version"]
