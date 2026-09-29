"""Student growth, the two composite variants, banding and the evidence adjustment."""

import pytest

from test_helpers import (
    ApiErrorId,
    MISSING_UUID,
    TEST_USERS,
    add_observation,
    certify_growth_measure,
    finalize_cycle,
    get_cycle,
    get_educator,
    growth_measure_payload,
    list_plans,
    report_growth_measure,
    setup_cycle,
    setup_submitted_cycle,
    validate_error,
    validate_paginated,
    validate_success,
)

HR = TEST_USERS["hr_admin_headers"]

DUAL_VARIANT_POLICY = {"required_formal_count": 2, "required_informal_count": 1}


class TestGrowthComponent:
    """Coverage-weighted index, capped coverage and the reliability floor."""

    @staticmethod
    def _cycle_with_two_measures():
        ctx = setup_cycle()
        ctx["measure_one"] = report_growth_measure(
            ctx["cycle"]["id"], index_value=3.2, coverage_pct=50,
            measure_code="STATE_ASSESSMENT")
        ctx["measure_two"] = report_growth_measure(
            ctx["cycle"]["id"], index_value=2.4, coverage_pct=30, measure_code="SLO")
        return ctx

    def test_two_certified_measures_blend_into_a_reliability_adjusted_component(self, api):
        """PRD §3.6: "Otherwise, let the coverage total be the sum of
        `coverage_pct` across the certified measures."
        PRD §3.6: "The `growth_component` is then 1.00 plus the reliability factor
        multiplied by the amount by which the weighted index exceeds 1.00, rounded
        half-up to four decimal places."
        PRD §3.6: "For example, certified measures of index 3.2 at 50 percent
        coverage and index 2.4 at 30 percent coverage give a coverage total of 80,
        a weighted index of 2.9, a reliability of 0.80, and a growth component of
        2.5200."

        Design: Difficulty/combinatorial_formula/growth_component_blends_coverage_cap_and_reliability_floor
        """
        ctx = self._cycle_with_two_measures()
        certify_growth_measure(ctx["measure_one"]["id"])
        certify_growth_measure(ctx["measure_two"]["id"])

        cycle = get_cycle(ctx["cycle"]["id"])
        assert cycle["growth_component"] == pytest.approx(2.5200), (
            "the coverage-weighted index of 2.9 at reliability 0.80 gives 2.5200"
        )
        assert cycle["growth_component"] != pytest.approx(2.8000), (
            "the unweighted mean of the two indices is not the component"
        )
        assert cycle["growth_component"] != pytest.approx(2.9000), (
            "the raw weighted index is not the component"
        )
        assert cycle["status"] == "SCHEDULING"

        measures, _meta = validate_paginated(
            api.list_growth_measures(ctx["cycle"]["id"], HR))
        assert {row["status"] for row in measures} == {"CERTIFIED"}

    def test_thin_coverage_receives_the_reliability_floor(self, api):
        """PRD §3.6: "The reliability factor is the coverage total capped at 100
        and then divided by 100, further capped at 1.00, and then floored at 0.60 —
        so a cycle whose certified measures cover only a fifth of the roster still
        receives a reliability of 0.60, and one covering the whole roster or more
        receives 1.00."
        PRD §3.6: "The **growth component** is computed from the cycle's measures
        whose `status` is `CERTIFIED`; `REPORTED` and `EXCLUDED` measures never
        enter it."
        PRD §3.6: "The `growth_component` is then 1.00 plus the reliability factor
        multiplied by the amount by which the weighted index exceeds 1.00, rounded
        half-up to four decimal places."

        Design: Difficulty/combinatorial_formula/growth_component_blends_coverage_cap_and_reliability_floor
        """
        ctx = self._cycle_with_two_measures()
        certify_growth_measure(ctx["measure_one"]["id"])

        cycle = get_cycle(ctx["cycle"]["id"])
        assert cycle["growth_component"] == pytest.approx(2.3200), (
            "coverage of 50 is floored to a reliability of 0.60, giving 1 + 0.60 * 2.2"
        )
        assert cycle["growth_component"] != pytest.approx(3.2000), (
            "the still-REPORTED measure must not enter the component"
        )


class TestCompositeVariants:
    """The same stored rows score differently under PROVISIONAL and FINAL."""

    @staticmethod
    def _cycle_one_formal_short():
        return setup_submitted_cycle(
            policy_overrides=dict(DUAL_VARIANT_POLICY),
            formal_scores=(3, 3, 4, 3), informal_scores=(3, 3, 3, 3),
            artifacts=2, growth_index=3.00, growth_coverage=100,
        )

    def test_submit_scores_the_cycle_on_the_observations_it_actually_has(self, api):
        """PRD §3.6: "Submission recomputes the growth component, then computes the
        composite under the **`PROVISIONAL`** variant, sets `composite_variant` to
        `PROVISIONAL`, leaves `evidence_adjustment` at 0.00, assigns
        `composite_rating` from the band of the resulting `composite_score`, and
        increments the cycle's `version`."
        PRD §3.6: "Under `PROVISIONAL`, the observation component runs **without**
        floor padding — a cycle short of its required observation counts is scored
        on what it actually has — and no evidence adjustment is applied, so
        `evidence_adjustment` stays 0.00 and the `composite_score` is simply the
        pre-adjustment composite."
        PRD §3.6: "Consider a policy requiring two formals and one informal, a
        cycle carrying one formal weighted 3.33 and one informal weighted 3.00, one
        certified growth measure of index 3.00 at 100 percent coverage giving a
        growth component of 3.0000, and a 60/40 split: under `PROVISIONAL` the
        formal average is 3.3300 and the informal 3.0000, giving an observation
        component of 3.2475 and a composite of 3.15; under `FINAL` the formal pool
        becomes 3.33 and 1.00, averaging 2.1650, giving an observation component of
        2.3738 and a pre-adjustment composite of 2.62."

        Design: Difficulty/dual_variant_calc/composite_provisional_vs_final_diverge_on_same_cycle
        """
        ctx = self._cycle_one_formal_short()
        cycle = ctx["cycle"]

        assert cycle["status"] == "SUBMITTED"
        assert cycle["composite_variant"] == "PROVISIONAL"
        assert cycle["observation_component"] == pytest.approx(3.2475)
        assert cycle["growth_component"] == pytest.approx(3.0000)
        assert cycle["composite_score"] == pytest.approx(3.15)
        assert cycle["evidence_adjustment"] == pytest.approx(0.00)

    def test_finalize_pads_the_short_pool_and_produces_a_different_composite(self, api):
        """PRD §3.6: "Finalization recomputes the composite under the **`FINAL`**
        variant, applies the evidence-sufficiency adjustment on top of it, sets
        `composite_variant` to `FINAL`, assigns `composite_rating` from the band of
        the adjusted score, stamps `finalized_at` with the logical clock instant,
        sets `appeal_deadline` to `finalized_at` plus the policy's
        `appeal_window_days`, and increments the cycle's `version`."
        PRD §3.6: "Under `FINAL`, each observation pool is first padded up to its
        required count with a floor value of 1.00 for every missing observation,
        and the evidence-sufficiency adjustment is then applied on top of the
        pre-adjustment composite."
        PRD §3.6: "Consider a policy requiring two formals and one informal, a
        cycle carrying one formal weighted 3.33 and one informal weighted 3.00, one
        certified growth measure of index 3.00 at 100 percent coverage giving a
        growth component of 3.0000, and a 60/40 split: under `PROVISIONAL` the
        formal average is 3.3300 and the informal 3.0000, giving an observation
        component of 3.2475 and a composite of 3.15; under `FINAL` the formal pool
        becomes 3.33 and 1.00, averaging 2.1650, giving an observation component of
        2.3738 and a pre-adjustment composite of 2.62."
        PRD §3.6: "A score at or above the policy's `highly_effective_threshold`
        bands as `HIGHLY_EFFECTIVE`; otherwise a score at or above
        `effective_threshold` bands as `EFFECTIVE`; otherwise a score at or above
        `developing_threshold` bands as `DEVELOPING`; anything below that bands as
        `INEFFECTIVE`."

        Design: Difficulty/dual_variant_calc/composite_provisional_vs_final_diverge_on_same_cycle
        """
        ctx = self._cycle_one_formal_short()
        assert ctx["cycle"]["composite_score"] == pytest.approx(3.15)

        finalized = finalize_cycle(ctx["cycle"]["id"])

        assert finalized["status"] == "FINALIZED"
        assert finalized["composite_variant"] == "FINAL"
        assert finalized["observation_component"] == pytest.approx(2.3738)
        assert finalized["growth_component"] == pytest.approx(3.0000)
        assert finalized["evidence_adjustment"] == pytest.approx(0.00), (
            "two artifacts meet the minimum, and a strong band earns no bonus"
        )
        assert finalized["composite_score"] == pytest.approx(2.62)
        assert finalized["composite_rating"] == "EFFECTIVE"


class TestEvidenceSufficiencyAdjustment:
    """The adjustment is keyed on the pre-adjustment band, the rating on the post."""

    @staticmethod
    def _under_evidenced_cycle():
        return setup_submitted_cycle(
            policy_overrides={"required_formal_count": 1, "required_informal_count": 1,
                              "evidence_min_artifacts": 2},
            formal_scores=(3, 3, 4, 3), informal_scores=(3, 3, 3, 3),
            artifacts=1, growth_index=1.51, growth_coverage=100,
        )

    def test_penalty_selected_by_the_pre_band_moves_the_stored_rating_down(self, api):
        """PRD §3.6: "The adjustment is keyed on the band of the *pre-adjustment*
        composite; the stored `composite_rating` is keyed on the band of the
        *post-adjustment* composite."
        PRD §3.6: "If the count falls short of `evidence_min_artifacts`, the cycle
        takes a penalty of 0.10 subtracted from its score when its pre-adjustment
        band is `EFFECTIVE` or `HIGHLY_EFFECTIVE`, and 0.00 otherwise."
        PRD §3.6: "A pre-adjustment composite of 2.55 with one attached artifact
        against a minimum of two bands `EFFECTIVE` before adjustment, takes the
        0.10 penalty, lands at 2.45 and is therefore stored as `DEVELOPING`; the
        same cycle with two attached artifacts takes no adjustment, stays at 2.55,
        and is stored as `EFFECTIVE`."

        Design: Difficulty/combinatorial_formula/evidence_adjustment_keyed_on_pre_band_not_final_band
        """
        ctx = self._under_evidenced_cycle()
        assert ctx["cycle"]["evidence_artifact_count"] == 1

        finalized = finalize_cycle(ctx["cycle"]["id"])

        assert finalized["evidence_adjustment"] == pytest.approx(-0.10), (
            "a pre-adjustment band of EFFECTIVE with thin evidence takes the penalty"
        )
        assert finalized["composite_score"] == pytest.approx(2.45)
        assert finalized["composite_rating"] == "DEVELOPING", (
            "the stored rating is the band of the post-adjustment score"
        )
        assert finalized["composite_variant"] == "FINAL"

    def test_a_developing_stored_rating_triggers_no_remediation(self, api):
        """PRD §3.6: "And if the stored `composite_rating` is `INEFFECTIVE`, the
        district's remediation obligation is triggered immediately: an improvement
        plan is created for that cycle and educator with `status` `ACTIVE`,
        `trigger_reason` of `INEFFECTIVE_RATING` and `escalation_level` of 1, and
        the creation of that plan sets the educator's `tenure_track_hold` to true."
        PRD §3.6: "The two bands may legitimately differ, and the adjustment is
        never recomputed against the post-adjustment band."

        Design: Difficulty/combinatorial_formula/evidence_adjustment_keyed_on_pre_band_not_final_band
        """
        ctx = self._under_evidenced_cycle()
        finalized = finalize_cycle(ctx["cycle"]["id"])
        assert finalized["composite_rating"] == "DEVELOPING"

        plans = list_plans(cycle_id=ctx["cycle"]["id"])
        assert plans == [], "only an INEFFECTIVE stored rating creates a plan"
        assert get_educator(ctx["educator"]["id"])["tenure_track_hold"] is False


class TestBandingBoundary:
    """A composite of exactly the effective threshold bands EFFECTIVE."""

    @staticmethod
    def _cycle_landing_on_the_threshold():
        return setup_submitted_cycle(
            policy_overrides={"required_formal_count": 1, "required_informal_count": 0,
                              "evidence_min_artifacts": 2},
            formal_scores=(2, 3, 3, 2), artifacts=2,
            growth_index=2.41, growth_coverage=100,
        )

    def test_composite_exactly_at_the_effective_threshold_bands_effective(self, api):
        """PRD §3.6: "A score at or above the policy's `highly_effective_threshold`
        bands as `HIGHLY_EFFECTIVE`; otherwise a score at or above
        `effective_threshold` bands as `EFFECTIVE`; otherwise a score at or above
        `developing_threshold` bands as `DEVELOPING`; anything below that bands as
        `INEFFECTIVE`. Every comparison is inclusive at the threshold."
        PRD §2.5: "The three banding cut points default to 3.50 for
        `highly_effective_threshold`, 2.50 for `effective_threshold` and 1.50 for
        `developing_threshold`."

        Design: Difficulty/boundary_precision_check/composite_exactly_at_effective_threshold_bands_effective
        """
        ctx = self._cycle_landing_on_the_threshold()
        finalized = finalize_cycle(ctx["cycle"]["id"])

        assert finalized["composite_score"] == pytest.approx(2.50)
        assert finalized["composite_rating"] == "EFFECTIVE", (
            "the banding comparison is inclusive at the threshold"
        )
        assert finalized["composite_rating"] != "DEVELOPING"

    def test_the_threshold_cycle_takes_no_evidence_adjustment_and_no_plan(self, api):
        """PRD §3.6: "If the cycle's `evidence_artifact_count` is at or above the
        policy's `evidence_min_artifacts`, the cycle earns a bonus of 0.05 when its
        pre-adjustment band is `DEVELOPING` or `INEFFECTIVE`, and 0.00 otherwise —
        a well-evidenced strong performance receives nothing extra."
        PRD §3.6: "And if the stored `composite_rating` is `INEFFECTIVE`, the
        district's remediation obligation is triggered immediately: an improvement
        plan is created for that cycle and educator with `status` `ACTIVE`,
        `trigger_reason` of `INEFFECTIVE_RATING` and `escalation_level` of 1, and
        the creation of that plan sets the educator's `tenure_track_hold` to true."

        Design: Difficulty/boundary_precision_check/composite_exactly_at_effective_threshold_bands_effective
        """
        ctx = self._cycle_landing_on_the_threshold()
        formal = ctx["formal_observation"]
        assert formal["weighted_score"] == pytest.approx(2.56)

        finalized = finalize_cycle(ctx["cycle"]["id"])
        assert finalized["growth_component"] == pytest.approx(2.4100)
        assert finalized["evidence_adjustment"] == pytest.approx(0.00)
        assert list_plans(cycle_id=ctx["cycle"]["id"]) == []


class TestGrowthExemptCycle:
    """With no CERTIFIED measure the composite renormalises onto observations."""

    @staticmethod
    def _cycle_with_an_uncertified_measure():
        return setup_submitted_cycle(
            policy_overrides={"required_formal_count": 1, "required_informal_count": 0},
            formal_scores=(3, 3, 4, 3), artifacts=0,
            growth_index=4.00, growth_coverage=100, certify_growth=False,
        )

    def test_uncertified_growth_leaves_the_observation_component_as_the_composite(self, api):
        """PRD §3.6: "When no certified measure exists the component is null and
        the cycle is treated as growth-exempt — it is emphatically not scored as
        zero."
        PRD §3.6: "When one component is null it is **removed rather than scored as
        zero**, and the surviving component becomes the raw composite in its
        entirety, unmultiplied."
        PRD §3.6: "That raw figure is then rounded half-up to two decimal places
        exactly once, yielding the pre-adjustment composite."

        Design: Difficulty/boundary_precision_check/cycle_with_no_certified_growth_measure_renormalizes_to_observation_only
        """
        ctx = self._cycle_with_an_uncertified_measure()
        cycle = ctx["cycle"]

        assert cycle["growth_component"] is None
        assert cycle["observation_component"] == pytest.approx(3.3300)
        assert cycle["composite_score"] == pytest.approx(3.33)
        assert cycle["composite_score"] != pytest.approx(1.998), (
            "the null growth component must not be scored as a zero"
        )
        assert cycle["composite_rating"] == "EFFECTIVE"

    def test_a_reported_measure_never_enters_the_growth_component(self, api):
        """PRD §3.6: "The **growth component** is computed from the cycle's
        measures whose `status` is `CERTIFIED`; `REPORTED` and `EXCLUDED` measures
        never enter it."
        PRD §3.6: "Under `PROVISIONAL`, the observation component runs **without**
        floor padding — a cycle short of its required observation counts is scored
        on what it actually has — and no evidence adjustment is applied, so
        `evidence_adjustment` stays 0.00 and the `composite_score` is simply the
        pre-adjustment composite."

        Design: Difficulty/boundary_precision_check/cycle_with_no_certified_growth_measure_renormalizes_to_observation_only
        """
        ctx = self._cycle_with_an_uncertified_measure()

        measures, _meta = validate_paginated(
            api.list_growth_measures(ctx["cycle"]["id"], HR))
        assert [row["status"] for row in measures] == ["REPORTED"]

        cycle = get_cycle(ctx["cycle"]["id"])
        assert cycle["composite_variant"] == "PROVISIONAL"
        assert cycle["evidence_adjustment"] == pytest.approx(0.00)


class TestExistenceBeatsStaleVersion:
    """A request naming a missing cycle and carrying a stale version."""

    @staticmethod
    def _cycle_with_captured_version():
        ctx = setup_cycle(certify=False)
        ctx["captured_version"] = ctx["cycle"]["version"]
        return ctx

    def test_unknown_cycle_is_reported_before_the_stale_version_check(self, api):
        """PRD §2.8: "Every resource named in the path and every foreign key in the
        body must exist."
        PRD §2.8: "**Stale version.** The supplied `expected_observation_version`,
        `expected_cycle_version` or `expected_plan_version` must equal the parent's
        current `version`, else the corresponding 412 from §2.7. This check guards
        exactly three operations: recording a rubric score, reporting a growth
        measure, and extending an improvement plan."
        PRD §2.8: "Checks are applied in this sequence, and the first one that
        fails determines the response:"

        Design: Difficulty/priority_pair_validation_conflict/growth_measure_cycle_existence_beats_stale_version_returns_not_found
        """
        ctx = self._cycle_with_captured_version()

        response = api.create_growth_measure(
            growth_measure_payload(MISSING_UUID, ctx["captured_version"] - 1,
                                   measure_code="SLO", index_value=2.00,
                                   coverage_pct=60),
            HR,
        )
        error_data = validate_error(response, ApiErrorId.ERR_CYCLE_NOT_FOUND.value, 404)
        assert error_data["error_id"] != ApiErrorId.ERR_STALE_CYCLE_VERSION.value

    def test_the_rejected_growth_measure_leaves_the_real_cycle_untouched(self, api):
        """PRD §2.7: "Reporting a student-growth measure against a cycle requires
        `expected_cycle_version` in the request body, again non-optional. The value
        must equal that cycle's current `version`; a mismatch is rejected with
        `ERR_STALE_CYCLE_VERSION` (HTTP 412)."
        PRD §2.8: "The rejection is the most specific 404 available:
        `ERR_EDUCATOR_NOT_FOUND`, `ERR_EVALUATOR_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`,
        `ERR_OBSERVATION_NOT_FOUND`, `ERR_PLAN_NOT_FOUND` or
        `ERR_APPEAL_NOT_FOUND` for those six kinds, and `ERR_RESOURCE_NOT_FOUND`
        for a missing school, policy, growth measure, evidence artifact, grievance
        or calibration review."

        Design: Difficulty/priority_pair_validation_conflict/growth_measure_cycle_existence_beats_stale_version_returns_not_found
        """
        ctx = self._cycle_with_captured_version()

        api.create_growth_measure(
            growth_measure_payload(MISSING_UUID, ctx["captured_version"] - 1,
                                   measure_code="SLO", index_value=2.00,
                                   coverage_pct=60),
            HR,
        )

        measures, _meta = validate_paginated(
            api.list_growth_measures(ctx["cycle"]["id"], HR))
        assert measures == [], "the real cycle gained no growth measure"
        assert get_cycle(ctx["cycle"]["id"])["version"] == ctx["captured_version"], (
            "a rejected write may not move the cycle's version"
        )


def test_growth_measure_carrying_a_superseded_cycle_version_is_rejected(api):
    """PRD §2.7: "Reporting a student-growth measure against a cycle requires
    `expected_cycle_version` in the request body, again non-optional. The value
    must equal that cycle's current `version`; a mismatch is rejected with
    `ERR_STALE_CYCLE_VERSION` (HTTP 412)."
    PRD §3.6: "Reporting a measure also increments the cycle's `version`."

    Design: Corner/cross_cutting_layers/growth_measure_with_stale_cycle_version_is_rejected
    """
    ctx = setup_cycle(certify=False)
    captured = ctx["cycle"]["version"]
    first = report_growth_measure(ctx["cycle"]["id"], index_value=2.50,
                                  coverage_pct=40, measure_code="SLO",
                                  expected_cycle_version=captured)

    response = api.create_growth_measure(
        growth_measure_payload(ctx["cycle"]["id"], captured,
                               measure_code="SCHOOLWIDE", index_value=3.00,
                               coverage_pct=20),
        HR,
    )
    validate_error(response, ApiErrorId.ERR_STALE_CYCLE_VERSION.value, 412)

    measures, _meta = validate_paginated(api.list_growth_measures(ctx["cycle"]["id"], HR))
    assert [row["id"] for row in measures] == [first["id"]]
    assert measures[0]["status"] == "REPORTED"
    assert get_cycle(ctx["cycle"]["id"])["growth_component"] is None


def test_a_repeated_measure_code_excludes_the_earlier_measure(api):
    """PRD §3.6: "When a new measure is created for a cycle that already holds a
    measure with the same `measure_code`, that existing measure — whether it was
    `REPORTED` or `CERTIFIED` — transitions to `EXCLUDED`, and the cycle's growth
    component is recomputed."
    PRD §3.6: "The **growth component** is computed from the cycle's measures whose
    `status` is `CERTIFIED`; `REPORTED` and `EXCLUDED` measures never enter it."

    Design: Corner/state_machines/growth_measure_with_repeated_code_supersedes_prior_to_excluded
    """
    ctx = setup_cycle(certify=False)
    first = report_growth_measure(ctx["cycle"]["id"], index_value=3.00,
                                  coverage_pct=100, measure_code="STATE_ASSESSMENT")
    certify_growth_measure(first["id"])
    assert get_cycle(ctx["cycle"]["id"])["growth_component"] == pytest.approx(3.0000)

    response = api.create_growth_measure(
        growth_measure_payload(ctx["cycle"]["id"], get_cycle(ctx["cycle"]["id"])["version"],
                               measure_code="STATE_ASSESSMENT", index_value=2.00,
                               coverage_pct=80),
        HR,
    )
    second = validate_success(response, 201)

    measures, _meta = validate_paginated(api.list_growth_measures(ctx["cycle"]["id"], HR))
    by_id = {row["id"]: row for row in measures}
    assert len(measures) == 2, "both rows remain readable"
    assert by_id[first["id"]]["status"] == "EXCLUDED"
    assert by_id[second["id"]]["status"] == "REPORTED"
    assert get_cycle(ctx["cycle"]["id"])["growth_component"] is None, (
        "the survivor is only REPORTED, so no certified measure remains"
    )


def test_cycle_submission_is_refused_while_an_observation_is_still_scheduled(api):
    """PRD §3.6: "Two completeness conditions apply together:
    `completed_formal_count` must be at least 1, and no observation of the cycle
    may still be sitting in `SCHEDULED`, `CONDUCTED`, `SCORED` or `RETURNED`; a
    failure of either is `ERR_CYCLE_OBSERVATIONS_PENDING`."

    Design: Corner/state_machines/cycle_submit_with_a_scheduled_observation_returns_observations_pending
    """
    ctx = setup_cycle()
    add_observation(ctx, observation_type="FORMAL", stop_at="CONDUCTED")
    pending = add_observation(
        ctx, observation_type="INFORMAL", stop_at="SCHEDULED",
        scheduled_start="2026-09-12T09:00:00Z", scheduled_end="2026-09-12T09:30:00Z")

    response = api.submit_evaluation_cycle(ctx["cycle"]["id"], HR)
    validate_error(response, ApiErrorId.ERR_CYCLE_OBSERVATIONS_PENDING.value, 422)

    cycle = get_cycle(ctx["cycle"]["id"])
    assert cycle["status"] == "SCORING"
    assert cycle["composite_score"] is None
    assert cycle["composite_variant"] is None
    assert validate_success(api.get_observation(pending["id"], HR))["status"] == "SCHEDULED"


def test_finalizing_a_cycle_still_in_scheduling_is_a_state_violation(api):
    """PRD §3.6: "**Finalizing the cycle** advances it from `SUBMITTED` to
    `FINALIZED` and is an `HrAdmin` act."
    PRD §2.8: "The rejection is `ERR_OBSERVATION_STATE_INVALID`,
    `ERR_CYCLE_STATE_INVALID`, `ERR_PLAN_STATE_INVALID`, `ERR_APPEAL_STATE_INVALID`,
    `ERR_GRIEVANCE_STATE_INVALID` or `ERR_TENURE_STATE_INVALID` according to the
    entity whose state was wrong, each HTTP 409."

    Design: Corner/state_machines/finalize_from_scheduling_returns_cycle_state_invalid
    """
    ctx = setup_cycle(certify=False)

    response = api.finalize_evaluation_cycle(ctx["cycle"]["id"], HR)
    validate_error(response, ApiErrorId.ERR_CYCLE_STATE_INVALID.value, 409)

    cycle = get_cycle(ctx["cycle"]["id"])
    assert cycle["status"] == "SCHEDULING"
    assert cycle["composite_score"] is None
    assert cycle["finalized_at"] is None
