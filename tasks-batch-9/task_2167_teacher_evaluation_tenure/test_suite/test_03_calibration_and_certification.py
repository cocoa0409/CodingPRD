"""Evaluator calibration, the two drift variants and the certification cycle."""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_observation,
    create_calibration_review,
    create_evaluator,
    create_policy,
    decide_calibration_review,
    get_evaluator,
    get_observation,
    get_cycle,
    get_school,
    observation_payload,
    make_evaluator_headers,
    record_calibration,
    set_clock,
    setup_cycle,
    setup_district,
    validate_error,
    validate_paginated,
)

HR = TEST_USERS["hr_admin_headers"]


def _decided(evaluator_id, policy_id, evaluator_score, code):
    return record_calibration(evaluator_id, policy_id, evaluator_score,
                              anchor_lesson_code=code)


class TestCalibrationDriftVariants:
    """A failing 1.00 followed by a passing 0.10 against a tolerance of 0.50."""

    @staticmethod
    def _two_decided_reviews():
        set_up = setup_district(certify=False)
        evaluator = set_up["evaluator"]
        policy = set_up["policy"]
        first = _decided(evaluator["id"], policy["id"], 4.00, "ANCH-A")
        second_review = create_calibration_review(
            evaluator["id"], anchor_score=3.00, evaluator_score=3.10,
            anchor_lesson_code="ANCH-B")
        second = decide_calibration_review(second_review["id"], policy["id"])
        return set_up, first, second

    def test_rolling_drift_averages_the_window_while_anchor_reports_the_latest(self, api):
        """PRD §3.2: "At creation the review's `deviation` is computed as the
        absolute difference between `evaluator_score` and `anchor_score`, rounded
        half-up to two decimal places, and the review's `outcome` is left at
        `PENDING`."
        PRD §3.2: "The review resolves to `PASS` when its `deviation` is at or
        below that tolerance, and to `FAIL` when the deviation exceeds it — the
        comparison is inclusive on the passing side, so a deviation exactly equal
        to the tolerance passes."
        PRD §3.2: "The **rolling** figure, `calibration_drift_rolling`, is the
        arithmetic mean of the `deviation` values of the last three such decided
        reviews — or of all of them when the evaluator has fewer than three —
        rounded half-up to two decimal places."
        PRD §3.2: "The **anchor** figure, `calibration_drift_anchor`, is simply
        the `deviation` of the single most recent decided review, carried at its
        own two decimals."

        Design: Difficulty/dual_variant_calc/calibration_rolling_vs_anchor_drift_diverge_on_evaluator
        """
        set_up, first, second = self._two_decided_reviews()

        assert first["deviation"] == pytest.approx(1.00)
        assert first["outcome"] == "FAIL", "1.00 exceeds the 0.50 tolerance"
        assert second["deviation"] == pytest.approx(0.10)
        assert second["outcome"] == "PASS", "0.10 is inside the 0.50 tolerance"

        evaluator = get_evaluator(set_up["evaluator"]["id"])
        assert evaluator["calibration_drift_rolling"] == pytest.approx(0.55), (
            "the rolling figure is the mean of 1.00 and 0.10"
        )
        assert evaluator["calibration_drift_anchor"] == pytest.approx(0.10), (
            "the anchor figure is the deviation of the most recent decided review"
        )
        assert evaluator["calibration_drift_rolling"] != pytest.approx(
            evaluator["calibration_drift_anchor"]
        ), "the two drift variants must diverge on this history"

    def test_certification_consults_the_rolling_figure_only(self, api):
        """PRD §3.2: "The two variants are computed on every resolution and both
        are exposed on the evaluator, but certification consults the rolling
        figure only: an evaluator whose latest review was flawless but whose
        three-review window still averages above tolerance is not certified."
        PRD §3.2: "Consider deviations of 1.00 followed by 0.10 against a
        tolerance of 0.50 — the anchor figure reads 0.10 and is comfortably inside
        tolerance, while the rolling figure reads 0.55 and is not, and the
        evaluator stays uncertified."
        PRD §3.2: "A `PROVISIONAL` evaluator stays `PROVISIONAL` when a review
        resolves `PASS` while the rolling figure is still above tolerance, or when
        it resolves `FAIL` without reaching the suspension threshold; in that case
        the drift figures are recomputed and the failure counter is updated but
        `certification_status` does not move."
        PRD §3.1: "A new evaluator's `certification_status` is `PROVISIONAL`, their
        `certification_expires_on` is null, their `consecutive_failed_calibrations`
        and `passed_calibration_count` are both 0, and both drift figures —
        `calibration_drift_rolling` and `calibration_drift_anchor` — are 0."

        Design: Difficulty/dual_variant_calc/calibration_rolling_vs_anchor_drift_diverge_on_evaluator
        """
        set_up, _first, _second = self._two_decided_reviews()

        evaluator = get_evaluator(set_up["evaluator"]["id"])
        assert evaluator["certification_status"] == "PROVISIONAL", (
            "a rolling figure of 0.55 above the 0.50 tolerance leaves the evaluator uncertified"
        )
        assert evaluator["certification_expires_on"] is None, (
            "certification_expires_on is only set on entry to CERTIFIED"
        )


class TestCertificationCycle:
    """PROVISIONAL to CERTIFIED to SUSPENDED and back, driven by calibration."""

    @staticmethod
    def _five_reviews():
        set_clock("2026-09-01T00:00:00Z")
        policy = create_policy()
        evaluator = create_evaluator(full_name="Robin Vega")
        outcomes = []
        for score, code in ((3.10, "ANCH-A"), (3.80, "ANCH-B"), (3.90, "ANCH-C"),
                            (3.00, "ANCH-D"), (3.00, "ANCH-E")):
            _decided(evaluator["id"], policy["id"], score, code)
            outcomes.append(get_evaluator(evaluator["id"]))
        return evaluator, policy, outcomes

    def test_evaluator_walks_provisional_certified_suspended_and_back(self, api):
        """PRD §3.2: "A `PROVISIONAL` evaluator becomes `CERTIFIED` when a review
        resolves `PASS` *and* the recomputed `calibration_drift_rolling` is at or
        below the policy's `calibration_drift_tolerance`; on that transition
        `certification_expires_on` is set to the logical clock's current date plus
        a one-year certification term of 365 days,
        `consecutive_failed_calibrations` is reset to 0, and
        `passed_calibration_count` increases by 1."
        PRD §3.2: "A `CERTIFIED` evaluator is suspended when a review resolves
        `FAIL` and, counting that review, `consecutive_failed_calibrations`
        reaches the policy's `calibration_max_consecutive_failures` — two
        consecutive failures by default, with the comparison satisfied at or above
        that count."
        PRD §3.2: "A `SUSPENDED` evaluator is restored to `CERTIFIED` by a review
        that resolves `PASS` while the recomputed `calibration_drift_rolling` is
        at or below tolerance, which resets `consecutive_failed_calibrations` to
        0, increases `passed_calibration_count` by 1, and sets
        `certification_expires_on` to the clock date plus 365 days."

        Design: Difficulty/non_linear_state_machine/evaluator_certification_cycles_provisional_certified_suspended_certified
        """
        _evaluator, _policy, snapshots = self._five_reviews()

        assert snapshots[0]["certification_status"] == "CERTIFIED", (
            "the first passing review certifies a PROVISIONAL evaluator"
        )
        assert snapshots[1]["certification_status"] == "CERTIFIED"
        assert snapshots[1]["consecutive_failed_calibrations"] == 1
        assert snapshots[2]["certification_status"] == "SUSPENDED", (
            "the second consecutive failure reaches the suspension threshold"
        )
        assert snapshots[2]["consecutive_failed_calibrations"] == 2
        assert snapshots[2]["certification_expires_on"] is None, (
            "suspension clears certification_expires_on"
        )
        assert snapshots[4]["certification_status"] == "CERTIFIED", (
            "a passing review inside tolerance restores a SUSPENDED evaluator"
        )
        assert snapshots[4]["consecutive_failed_calibrations"] == 0
        assert snapshots[4]["certification_expires_on"] == "2027-09-01", (
            "the certification term is the clock date plus 365 days"
        )

    def test_a_passing_review_with_a_drifting_window_leaves_the_evaluator_suspended(self, api):
        """PRD §3.2: "A `SUSPENDED` evaluator stays `SUSPENDED` when a review
        resolves `FAIL`, or resolves `PASS` while the rolling figure remains above
        tolerance; the drift figures and failure counter are updated either way."
        PRD §3.2: "The **rolling** figure, `calibration_drift_rolling`, is the
        arithmetic mean of the `deviation` values of the last three such decided
        reviews — or of all of them when the evaluator has fewer than three —
        rounded half-up to two decimal places."
        PRD §3.2: "The **anchor** figure, `calibration_drift_anchor`, is simply
        the `deviation` of the single most recent decided review, carried at its
        own two decimals."

        Design: Difficulty/non_linear_state_machine/evaluator_certification_cycles_provisional_certified_suspended_certified
        """
        _evaluator, _policy, snapshots = self._five_reviews()

        fourth = snapshots[3]
        assert fourth["certification_status"] == "SUSPENDED", (
            "a flawless review cannot restore certification while the window drifts"
        )
        assert fourth["calibration_drift_rolling"] == pytest.approx(0.57), (
            "the mean of 0.80, 0.90 and 0.00 rounds half-up to 0.57"
        )
        assert fourth["calibration_drift_anchor"] == pytest.approx(0.00)

        fifth = snapshots[4]
        assert fifth["calibration_drift_rolling"] == pytest.approx(0.30), (
            "the mean of 0.90, 0.00 and 0.00 is 0.30"
        )
        assert fifth["calibration_drift_anchor"] == pytest.approx(0.00)


class TestCertificationGatesObservationScheduling:

    def test_suspended_evaluator_may_not_be_named_on_a_new_observation(self, api):
        """PRD §3.3: "The named evaluator's `certification_status` must read
        `CERTIFIED` — a `PROVISIONAL` or `SUSPENDED` evaluator yields
        `ERR_EVALUATOR_NOT_CERTIFIED`."
        PRD §3.2: "A `CERTIFIED` evaluator is suspended when a review resolves
        `FAIL` and, counting that review, `consecutive_failed_calibrations`
        reaches the policy's `calibration_max_consecutive_failures` — two
        consecutive failures by default, with the comparison satisfied at or above
        that count."

        Design: Difficulty/cross_entity_state_dependency/observation_scheduling_blocked_by_suspended_evaluator
        """
        ctx = setup_cycle()
        evaluator_id = ctx["evaluator"]["id"]
        _decided(evaluator_id, ctx["policy"]["id"], 3.80, "ANCH-B")
        _decided(evaluator_id, ctx["policy"]["id"], 3.90, "ANCH-C")
        assert get_evaluator(evaluator_id)["certification_status"] == "SUSPENDED"

        response = api.create_observation(
            observation_payload(ctx["cycle"]["id"], evaluator_id),
            make_evaluator_headers(evaluator_id),
        )
        validate_error(response, ApiErrorId.ERR_EVALUATOR_NOT_CERTIFIED.value, 422)

        assert get_cycle(ctx["cycle"]["id"])["status"] == "SCHEDULING"
        observations, _meta = validate_paginated(
            api.list_observations(HR, params={"cycle_id": ctx["cycle"]["id"]})
        )
        assert observations == [], "the rejected scheduling must create no observation"

    def test_provisional_evaluator_may_not_be_named_on_a_new_observation(self, api):
        """PRD §3.1: "A `PROVISIONAL` evaluator can neither be named on a new
        observation nor mark one conducted; they must be certified first."
        PRD §3.3: "The named evaluator's `certification_status` must read
        `CERTIFIED` — a `PROVISIONAL` or `SUSPENDED` evaluator yields
        `ERR_EVALUATOR_NOT_CERTIFIED`."

        Design: Difficulty/cross_entity_state_dependency/observation_scheduling_blocked_by_suspended_evaluator
        """
        ctx = setup_cycle(certify=False)
        evaluator_id = ctx["evaluator"]["id"]
        assert get_evaluator(evaluator_id)["certification_status"] == "PROVISIONAL"

        response = api.create_observation(
            observation_payload(ctx["cycle"]["id"], evaluator_id),
            make_evaluator_headers(evaluator_id),
        )
        validate_error(response, ApiErrorId.ERR_EVALUATOR_NOT_CERTIFIED.value, 422)

        observations, _meta = validate_paginated(
            api.list_observations(HR, params={"cycle_id": ctx["cycle"]["id"]})
        )
        assert observations == [], "an uncertified evaluator schedules nothing"


class TestSuspensionCascade:
    """The second consecutive failure voids the evaluator's live observations."""

    @staticmethod
    def _cycle_with_conducted_observation():
        ctx = setup_cycle()
        ctx["observation"] = add_observation(ctx, stop_at="CONDUCTED")
        _decided(ctx["evaluator"]["id"], ctx["policy"]["id"], 3.80, "ANCH-B")
        return ctx

    def test_suspension_voids_the_evaluators_live_observation(self, api):
        """PRD §3.2: "Suspension clears `certification_expires_on` to null and
        triggers the system's widest cascade: every observation of that evaluator
        whose `status` is `SCHEDULED`, `CONDUCTED`, `SCORED` or `RETURNED`
        transitions to `VOIDED` with `void_reason` set to the literal string
        `EVALUATOR_SUSPENDED`, and each such voiding then bubbles its cycle from
        `SCORING` back to `SCHEDULING` whenever no observation of that cycle
        remains in `CONDUCTED`, `SCORED`, `SUBMITTED`, `RETURNED` or `ACCEPTED`."

        Design: Difficulty/transitive_cascade/calibration_failure_suspends_evaluator_voids_observations_and_reverts_cycle
        """
        ctx = self._cycle_with_conducted_observation()
        before = get_evaluator(ctx["evaluator"]["id"])
        assert before["certification_status"] == "CERTIFIED"
        assert before["consecutive_failed_calibrations"] == 1
        assert get_observation(ctx["observation"]["id"])["status"] == "CONDUCTED"

        third = _decided(ctx["evaluator"]["id"], ctx["policy"]["id"], 3.90, "ANCH-C")
        assert third["outcome"] == "FAIL"
        assert third["deviation"] == pytest.approx(0.90)

        evaluator = get_evaluator(ctx["evaluator"]["id"])
        assert evaluator["certification_status"] == "SUSPENDED"
        assert evaluator["consecutive_failed_calibrations"] == 2
        assert evaluator["certification_expires_on"] is None

        observation = get_observation(ctx["observation"]["id"])
        assert observation["status"] == "VOIDED"
        assert observation["void_reason"] == "EVALUATOR_SUSPENDED", (
            "a cascaded void stores the literal EVALUATOR_SUSPENDED"
        )

    def test_the_cascade_bubbles_the_cycle_from_scoring_back_to_scheduling(self, api):
        """PRD §3.2: "Suspension clears `certification_expires_on` to null and
        triggers the system's widest cascade: every observation of that evaluator
        whose `status` is `SCHEDULED`, `CONDUCTED`, `SCORED` or `RETURNED`
        transitions to `VOIDED` with `void_reason` set to the literal string
        `EVALUATOR_SUSPENDED`, and each such voiding then bubbles its cycle from
        `SCORING` back to `SCHEDULING` whenever no observation of that cycle
        remains in `CONDUCTED`, `SCORED`, `SUBMITTED`, `RETURNED` or `ACCEPTED`."
        PRD §3.3: "The first observation of a cycle to reach `CONDUCTED` pulls its
        cycle from `SCHEDULING` up to `SCORING`, which increments the cycle's
        `version`; subsequent conducted observations find the cycle already at
        `SCORING` and leave it alone."

        Design: Difficulty/transitive_cascade/calibration_failure_suspends_evaluator_voids_observations_and_reverts_cycle
        """
        ctx = self._cycle_with_conducted_observation()
        assert get_cycle(ctx["cycle"]["id"])["status"] == "SCORING", (
            "the conducted observation had pulled the cycle up to SCORING"
        )

        _decided(ctx["evaluator"]["id"], ctx["policy"]["id"], 3.90, "ANCH-C")

        cycle = get_cycle(ctx["cycle"]["id"])
        assert cycle["status"] == "SCHEDULING", (
            "with no live observation left the cycle bubbles back to SCHEDULING"
        )
        assert cycle["observation_component"] is None
        school = get_school(ctx["school"]["id"])
        assert school["evaluation_budget_committed_cents"] == 0, (
            "a never-submitted observation had committed no stipend"
        )
