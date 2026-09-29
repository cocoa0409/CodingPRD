"""Two boundaries of different kinds: a numeric threshold reached exactly, and
a population that is first empty and then one-sided."""
from test_helpers import (
    assert_money,
    assert_summary_figures,
    factories as f,
    fixtures as fx,
    validate_paginated,
    validate_success,
)

#: The two phrase-spotting categories worth thirty and fifteen points.
FLAGGED = ["NO_DISCLOSURE", "ESCALATION_REQUEST"]


class TestPriorityTierAtTheBoundary:
    """One point of dead air is worth forty-five hundredths of risk, which is
    exactly the step that crosses the P1 floor."""

    @staticmethod
    def _chat_contact_env(api):
        """A CHAT contact whose disclosures were captured, so no gap bonus
        applies and the channel multiplier is exactly one."""
        fx.set_clock(api, "2026-08-05T09:00:00Z")
        agent = fx.create_agent(api)
        interaction = fx.create_verified_interaction(
            api,
            agent["id"],
            channel="CHAT",
            started_at="2026-08-04T09:00:00Z",
            ended_at="2026-08-04T09:20:00Z",
            required_disclosures=["RECORDING"],
            captured_disclosures=["RECORDING"],
            csat_score=3,
        )
        return fx.Env(agent=agent, interaction=interaction)

    def test_one_point_of_dead_air_below_the_floor_stays_in_the_second_band(self, api):
        """69.55 is one 0.45 step short of the P1 floor.

        PRD: "First an unrounded base figure is formed by adding three terms: the
        `silence_pct` multiplied by forty-five hundredths; the sentiment penalty,
        which is the negated `sentiment_delta` floored at zero — so a positive or
        zero `sentiment_delta` contributes nothing — multiplied by one hundred and
        then by thirty-five hundredths; and the sum of the category points of every
        entry in `flagged_categories`, where `PROFANITY` is worth twenty-five
        points, `NO_DISCLOSURE` thirty points, `ESCALATION_REQUEST` fifteen points
        and `CONSENT_OBJECTION` forty points."
        PRD: "`priority_tier` then bands the result: `P1` when `risk_score` is at
        least `70.00`, `P2` when `risk_score` is at least `40.00` but below `70.00`,
        and `P3` when `risk_score` is below `40.00`."

        Design: Difficulty/boundary_precision_check/boundary_analytics_priority_tier_exactly_at_seventy
        """
        env = self._chat_contact_env(api)

        # 17.55 + 7.00 + 45 = 69.55, times the CHAT multiplier of exactly one.
        scan = fx.create_scan(
            api,
            env.interaction["id"],
            env.interaction["version"],
            silence_pct=39.00,
            sentiment_delta=-0.20,
            flagged_categories=FLAGGED,
        )

        assert_money(scan["risk_score"], 69.55)
        assert scan["priority_tier"] == "P2"
        assert scan["status"] == "CURRENT"

    def test_the_boundary_value_itself_lands_in_the_top_band(self, api):
        """Exactly 70.00 is P1, because the comparison is at-least.

        PRD: "`priority_tier` then bands the result: `P1` when `risk_score` is at
        least `70.00`, `P2` when `risk_score` is at least `40.00` but below `70.00`,
        and `P3` when `risk_score` is below `40.00`."
        PRD: "Both the inner cap and the channel multiplication are performed on
        unrounded values; `risk_score` is the only rounded figure."

        Design: Difficulty/boundary_precision_check/boundary_analytics_priority_tier_exactly_at_seventy
        """
        env = self._chat_contact_env(api)

        # 18.00 + 7.00 + 45 = 70.00 exactly.
        scan = fx.create_scan(
            api,
            env.interaction["id"],
            env.interaction["version"],
            silence_pct=40.00,
            sentiment_delta=-0.20,
            flagged_categories=FLAGGED,
        )

        assert_money(scan["risk_score"], 70.00)
        assert scan["priority_tier"] == "P1"

    def test_the_second_screening_supersedes_the_first_and_leads_the_queue(self, api):
        """Both readings persist, and the riskier one sits at the top.

        PRD: "A new scan is stored with `status` of `CURRENT`, and every earlier
        scan of the same interaction whose `status` was `CURRENT` moves to
        `SUPERSEDED` with its `version` incremented; a successful create also
        increments the parent interaction's `version`, which is why a second
        screening of the same contact must re-read the interaction first."
        PRD: "the analytics-scan listing is ordered by `risk_score` descending with
        `created_at` ascending as the tie-break, so that the highest-risk unscreened
        contacts sit at the top of the manual-review work queue."

        Design: Difficulty/boundary_precision_check/boundary_analytics_priority_tier_exactly_at_seventy
        """
        env = self._chat_contact_env(api)
        version_before = env.interaction["version"]

        low = fx.create_scan(
            api,
            env.interaction["id"],
            version_before,
            silence_pct=39.00,
            sentiment_delta=-0.20,
            flagged_categories=FLAGGED,
        )
        refreshed = fx.read_interaction(api, env.interaction["id"])
        high = fx.create_scan(
            api,
            env.interaction["id"],
            refreshed["version"],
            silence_pct=40.00,
            sentiment_delta=-0.20,
            flagged_categories=FLAGGED,
        )

        assert fx.read_scan(api, low["id"])["status"] == "SUPERSEDED"
        assert fx.read_scan(api, high["id"])["status"] == "CURRENT"
        assert (
            fx.read_interaction(api, env.interaction["id"])["version"] == version_before + 2
        )
        rows, meta = validate_paginated(
            api.list_scans(
                fx.make_quality_manager_headers(), {"interaction_id": env.interaction["id"]}
            )
        )
        assert meta["total_count"] == 2
        assert [row["id"] for row in rows] == [high["id"], low["id"]]


class TestQualitySummaryAtItsCardinalityBoundaries:
    """An empty population and a one-sided one produce nulls for two entirely
    different reasons."""

    def test_a_draft_only_population_reads_as_empty_without_failing(self, api):
        """The status filter, not an empty table, is what yields zero.

        PRD: "Both draw on the same population — every evaluation of that agent
        whose `review_status` is `SUBMITTED`, `FINALIZED` or `REOPENED` and whose
        `weighted_score` is not null. `DRAFT` evaluations never contribute, and an
        excluded selection contributes nothing because it never produces an
        evaluation at all."
        PRD: "One edge governs the whole summary: when the evaluation population is
        empty, `evaluations_considered` and `paired_sample_size` are both `0`, and
        `csat_gap_paired`, `csat_gap_all` and `repeat_contact_rate` are all null. The
        summary still answers `200 OK` and never divides by zero."

        Design: Difficulty/boundary_precision_check/boundary_quality_summary_empty_then_single_sided_partitions
        """
        env = fx.draft_evaluation_env(api)
        assert env.evaluation["review_status"] == "DRAFT"

        summary = validate_success(
            api.get_quality_summary(env.agent["id"], fx.make_supervisor_headers()), 200
        )

        assert_summary_figures(
            summary,
            rolling=None,
            period=None,
            evaluations_considered=0,
            paired_sample_size=0,
            csat_gap_paired=None,
            csat_gap_all=None,
            repeat_contact_rate=None,
        )

    def test_one_scored_evaluation_gives_the_repeat_rate_a_denominator(self, api):
        """A rate of zero and a null are different answers.

        PRD: "`repeat_contact_rate` is the count of evaluations whose interaction
        has `repeat_contact_within_72h` set to `true`, divided by the size of the
        population, multiplied by one hundred and rounded half up to two decimals."
        PRD: "`evaluations_considered` is the size of that population.
        `paired_sample_size` is the number of those evaluations whose interaction
        carries a non-null `csat_score`."

        Design: Difficulty/boundary_precision_check/boundary_quality_summary_empty_then_single_sided_partitions
        """
        env = fx.draft_evaluation_env(api)
        fx.submit_evaluation(
            api, env.evaluation["id"], env.evaluator["id"], f.PASSING_ITEM_SCORES
        )

        summary = validate_success(
            api.get_quality_summary(env.agent["id"], fx.make_supervisor_headers()), 200
        )

        assert_summary_figures(
            summary,
            rolling=82.00,
            period=82.00,
            evaluations_considered=1,
            paired_sample_size=1,
            repeat_contact_rate=0.00,
        )
        assert summary["repeat_contact_rate"] is not None

    def test_a_single_low_scorer_leaves_the_high_partition_empty(self, api):
        """Both satisfaction gaps stay null when one side has no members.

        PRD: "The population is first split at a floor of `85.00` on effective
        score: an evaluation whose effective score is at least `85.00` is a high
        scorer, and one below `85.00` is a low scorer."
        PRD: "`csat_gap_all` is null only when the high group or the low group is
        empty."

        Design: Difficulty/boundary_precision_check/boundary_quality_summary_empty_then_single_sided_partitions
        """
        env = fx.draft_evaluation_env(api)
        scored = fx.submit_evaluation(
            api, env.evaluation["id"], env.evaluator["id"], f.PASSING_ITEM_SCORES
        )
        assert_money(scored["weighted_score"], 82.00)

        summary = validate_success(
            api.get_quality_summary(env.agent["id"], fx.make_supervisor_headers()), 200
        )

        assert_summary_figures(summary, csat_gap_paired=None, csat_gap_all=None)

    def test_reading_the_summary_writes_nothing_on_the_agent(self, api):
        """Nothing the summary produces is persisted.

        PRD: "A per-agent quality summary is computed on demand for the
        `QualityManager`, `Supervisor` and `ComplianceAuditor`, and nothing it
        produces is persisted."

        Design: Difficulty/boundary_precision_check/boundary_quality_summary_empty_then_single_sided_partitions
        """
        env = fx.draft_evaluation_env(api)
        before = fx.read_agent(api, env.agent["id"])

        validate_success(
            api.get_quality_summary(env.agent["id"], fx.make_supervisor_headers()), 200
        )
        fx.submit_evaluation(
            api, env.evaluation["id"], env.evaluator["id"], f.PASSING_ITEM_SCORES
        )
        after_submit = fx.read_agent(api, env.agent["id"])
        validate_success(
            api.get_quality_summary(env.agent["id"], fx.make_supervisor_headers()), 200
        )

        after_read = fx.read_agent(api, env.agent["id"])
        assert after_submit["version"] == before["version"] + 1
        assert after_read == after_submit
