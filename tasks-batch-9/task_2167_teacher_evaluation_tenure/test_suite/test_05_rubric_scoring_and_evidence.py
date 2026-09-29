"""Rubric scoring, the revision loop, evidence artifacts and reverse listings."""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_observation,
    attach_artifact,
    conduct_observation,
    get_cycle,
    get_observation,
    get_school,
    make_evaluator_headers,
    make_teacher_headers,
    report_growth_measure,
    return_observation,
    rubric_score_payload,
    schedule_observation,
    score_domain,
    setup_cycle,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_artifact,
)

HR = TEST_USERS["hr_admin_headers"]


class TestWeightedScoreRoundingOrder:
    """Round each domain contribution first, then sum the four."""

    @staticmethod
    def _unannounced_formal_scored_3_2_4_3():
        ctx = setup_cycle()
        ctx["observation"] = add_observation(
            ctx, observation_type="FORMAL", announced=False,
            scores=(3, 2, 4, 3), stop_at="SCORED",
        )
        return ctx

    def test_unannounced_formal_sums_the_rounded_contributions_to_3_42(self, api):
        """PRD §3.4: "Each of the four domain contributions is rounded to two
        decimal places *first*, and the observation's `weighted_score` is then the
        sum of those four already-rounded contributions, in the fixed evaluation
        order `PLANNING`, `ENVIRONMENT`, `INSTRUCTION`, `PROFESSIONALISM`, with no
        further rounding applied to the sum."
        PRD §3.4: "To make the difference concrete: raw scores of 3, 2, 4 and 3
        across the four domains on an unannounced formal observation, under domain
        weights of 22, 23, 33 and 22 and a multiplier of 1.10, give per-domain
        contributions of 0.73, 0.51, 1.45 and 0.73, which sum to 3.42 — whereas
        summing first to 3.10, applying the multiplier and rounding once would give
        3.41."
        PRD §3.4: "The observation reaches `SCORED` at the moment the fourth
        distinct `domain_code` is present, and that is a system transition rather
        than an operator action: from `CONDUCTED` to `SCORED` when the fourth
        domain is first recorded, and from `RETURNED` back to `SCORED` when a
        returned observation — which already carries all four domains — receives a
        replacement score for any one of them."

        Design: Difficulty/combinatorial_formula/observation_weighted_score_rounds_per_domain_then_sums
        """
        ctx = self._unannounced_formal_scored_3_2_4_3()
        observation = get_observation(ctx["observation"]["id"])

        assert observation["status"] == "SCORED"
        assert observation["scored_domain_count"] == 4
        assert observation["weighted_score"] == pytest.approx(3.42), (
            "the pinned per-domain rounding order yields 3.42"
        )
        assert observation["weighted_score"] != pytest.approx(3.41), (
            "summing first and rounding once is the wrong order"
        )

    def test_each_rubric_row_stores_its_own_rounded_contribution(self, api):
        """PRD §3.4: "A domain's `weighted_contribution` is the domain's
        `raw_score` multiplied by that domain's policy weight in percent,
        multiplied by a factor, divided by 100, and rounded half-up to two decimal
        places."
        PRD §3.4: "The factor is the policy's `unannounced_multiplier` when the
        observation's `observation_type` is `FORMAL` and its `announced` flag is
        false, and is exactly 1.00 in every other case — an unannounced `INFORMAL`
        visit earns no multiplier."
        PRD §3.4: "To make the difference concrete: raw scores of 3, 2, 4 and 3
        across the four domains on an unannounced formal observation, under domain
        weights of 22, 23, 33 and 22 and a multiplier of 1.10, give per-domain
        contributions of 0.73, 0.51, 1.45 and 0.73, which sum to 3.42 — whereas
        summing first to 3.10, applying the multiplier and rounding once would give
        3.41."

        Design: Difficulty/combinatorial_formula/observation_weighted_score_rounds_per_domain_then_sums
        """
        ctx = self._unannounced_formal_scored_3_2_4_3()

        rows, _meta = validate_paginated(
            api.list_rubric_scores(ctx["observation"]["id"], HR)
        )
        live = {row["domain_code"]: row for row in rows if not row["superseded"]}
        assert live["PLANNING"]["weighted_contribution"] == pytest.approx(0.73)
        assert live["ENVIRONMENT"]["weighted_contribution"] == pytest.approx(0.51)
        assert live["INSTRUCTION"]["weighted_contribution"] == pytest.approx(1.45)
        assert live["PROFESSIONALISM"]["weighted_contribution"] == pytest.approx(0.73)


class TestRevisionLoop:
    """SCORED to SUBMITTED to RETURNED and back to SCORED on the same row."""

    @staticmethod
    def _submitted_formal():
        ctx = setup_cycle()
        ctx["observation"] = add_observation(
            ctx, observation_type="FORMAL", scores=(3, 3, 4, 3), stop_at="SUBMITTED")
        return ctx

    def test_returning_a_submitted_observation_releases_its_stipend(self, api):
        """PRD §3.5: "**Returning** an observation for rescoring moves it from
        `SUBMITTED` to `RETURNED`, requires a `return_reason` in the payload which
        is stored on the observation, increases `return_count` by 1, and releases
        the money: the building's `evaluation_budget_committed_cents` decreases by
        the observation's `stipend_cents` and that `stipend_cents` is reset to 0."
        PRD §3.5: "The cycle's completed counts and `observation_component` are
        recomputed and the cycle's `version` increments."

        Design: Difficulty/non_linear_state_machine/observation_submitted_returned_rescored_revision_loop
        """
        ctx = self._submitted_formal()
        assert get_school(ctx["school"]["id"])["evaluation_budget_committed_cents"] == 12500

        returned = return_observation(
            ctx["observation"]["id"], "Domain 4 evidence does not support the score")

        assert returned["status"] == "RETURNED"
        assert returned["stipend_cents"] == 0
        assert returned["return_count"] == 1
        school = get_school(ctx["school"]["id"])
        assert school["evaluation_budget_committed_cents"] == 0, (
            "the return releases the committed stipend exactly"
        )
        cycle = get_cycle(ctx["cycle"]["id"])
        assert cycle["completed_formal_count"] == 0

    def test_rescoring_a_returned_observation_returns_it_to_scored(self, api):
        """PRD §3.4: "The `RETURNED` to `SCORED` leg is the return path of the
        revision loop; it supersedes the prior row for the replaced domain,
        recomputes `weighted_score`, increments the observation's `version`, and
        deliberately preserves `return_count` so that the history of how many
        times the work came back is never erased."
        PRD §3.4: "Each of the four domain contributions is rounded to two decimal
        places *first*, and the observation's `weighted_score` is then the sum of
        those four already-rounded contributions, in the fixed evaluation order
        `PLANNING`, `ENVIRONMENT`, `INSTRUCTION`, `PROFESSIONALISM`, with no
        further rounding applied to the sum."

        Design: Difficulty/non_linear_state_machine/observation_submitted_returned_rescored_revision_loop
        """
        ctx = self._submitted_formal()
        returned = return_observation(ctx["observation"]["id"], "Rescore domain four")

        score_domain(ctx["observation"]["id"], ctx["evaluator"]["id"],
                     "PROFESSIONALISM", 4, returned["version"])

        observation = get_observation(ctx["observation"]["id"])
        assert observation["status"] == "SCORED", "the revision loop re-enters SCORED"
        assert observation["return_count"] == 1, "return_count is deliberately preserved"
        assert observation["scored_domain_count"] == 4
        assert observation["weighted_score"] == pytest.approx(3.55), (
            "0.66 + 0.69 + 1.32 + 0.88 with the replaced PROFESSIONALISM row"
        )
        assert get_cycle(ctx["cycle"]["id"])["status"] == "SCORING"


class TestEvidenceLedger:
    """Attach and withdraw are exact compensating actions on two counters."""

    @staticmethod
    def _conducted_observation():
        ctx = setup_cycle()
        ctx["observation"] = add_observation(ctx, stop_at="CONDUCTED")
        return ctx

    def test_attaching_artifacts_raises_both_evidence_counters(self, api):
        """PRD §3.4: "Its `status` begins at `ATTACHED`, and its
        `submitted_by_role` is recorded from the `X-User-Role` header at attach
        time as either `EVALUATOR` or `TEACHER`."
        PRD §3.4: "Attaching increases the owning observation's `evidence_count`
        by 1, recomputes the cycle's `evidence_artifact_count`, and increments the
        cycle's `version` by 1."
        PRD §2.10: "An observation's `evidence_count` is the number of its
        evidence artifacts whose `status` is `ATTACHED`; withdrawal is the exact
        compensating action for attachment and decreases the count by one."

        Design: Difficulty/compensating_invariant/attach_then_withdraw_restores_evidence_ledger_exactly
        """
        ctx = self._conducted_observation()
        assert get_observation(ctx["observation"]["id"])["evidence_count"] == 0
        assert get_cycle(ctx["cycle"]["id"])["evidence_artifact_count"] == 0

        by_evaluator = attach_artifact(
            ctx["observation"]["id"], make_evaluator_headers(ctx["evaluator"]["id"]),
            artifact_type="LESSON_PLAN", title="Unit 3 plan")
        by_teacher = attach_artifact(
            ctx["observation"]["id"], make_teacher_headers(ctx["educator"]["id"]),
            artifact_type="STUDENT_WORK", title="Exit tickets")

        assert by_evaluator["status"] == "ATTACHED"
        assert by_evaluator["submitted_by_role"] == "EVALUATOR"
        assert by_teacher["submitted_by_role"] == "TEACHER"
        assert get_observation(ctx["observation"]["id"])["evidence_count"] == 2
        assert get_cycle(ctx["cycle"]["id"])["evidence_artifact_count"] == 2

    def test_withdrawing_every_artifact_restores_both_counters_to_zero(self, api):
        """PRD §3.4: "Withdrawal is the exact compensating action. It moves the
        artifact from `ATTACHED` to `WITHDRAWN`, decreases the observation's
        `evidence_count` by 1, recomputes the cycle's `evidence_artifact_count`,
        and increments the cycle's `version` by 1."
        PRD §2.10: "A cycle's `evidence_artifact_count` is the sum of
        `evidence_count` across the cycle's observations whose `status` is not
        `VOIDED` — so voiding an observation removes its artifacts from the cycle's
        tally without touching the artifacts themselves."

        Design: Difficulty/compensating_invariant/attach_then_withdraw_restores_evidence_ledger_exactly
        """
        ctx = self._conducted_observation()
        evaluator_headers = make_evaluator_headers(ctx["evaluator"]["id"])
        teacher_headers = make_teacher_headers(ctx["educator"]["id"])
        first = attach_artifact(ctx["observation"]["id"], evaluator_headers,
                                artifact_type="LESSON_PLAN", title="Unit 3 plan")
        second = attach_artifact(ctx["observation"]["id"], teacher_headers,
                                 artifact_type="STUDENT_WORK", title="Exit tickets")

        withdrawn_first = withdraw_artifact(first["id"], evaluator_headers)
        assert withdrawn_first["status"] == "WITHDRAWN"
        assert get_observation(ctx["observation"]["id"])["evidence_count"] == 1
        assert get_cycle(ctx["cycle"]["id"])["evidence_artifact_count"] == 1

        withdrawn_second = withdraw_artifact(second["id"], teacher_headers)
        assert withdrawn_second["status"] == "WITHDRAWN"
        assert get_observation(ctx["observation"]["id"])["evidence_count"] == 0
        assert get_cycle(ctx["cycle"]["id"])["evidence_artifact_count"] == 0
        assert get_observation(ctx["observation"]["id"])["status"] == "CONDUCTED", (
            "evidence movement does not change the observation state"
        )


def test_stale_observation_version_is_rejected_then_supersede_succeeds(api):
    """PRD §2.7: "Recording a rubric domain score against an observation requires
    `expected_observation_version` in the request body. It is not optional. The
    value must equal that observation's current `version`; if the observation's
    version has advanced since the client last read it, the write is rejected with
    `ERR_STALE_OBSERVATION_VERSION` (HTTP 412)."
    PRD §3.4: "Posting a domain that already carries a score is a legitimate
    correction rather than an error: the earlier row for that observation and that
    `domain_code` has its `superseded` flag flipped to true, and a superseded row
    never enters any arithmetic again."

    Design: Corner/cross_cutting_layers/rubric_score_with_stale_observation_version_is_rejected_then_supersede_succeeds
    """
    ctx = setup_cycle()
    observation = schedule_observation(ctx["cycle"]["id"], ctx["evaluator"]["id"])
    conducted = conduct_observation(observation["id"], ctx["evaluator"]["id"])
    first_row = score_domain(observation["id"], ctx["evaluator"]["id"],
                             "PLANNING", 2, conducted["version"])
    current_version = first_row["observation_version_after"]

    stale = api.create_rubric_score(
        observation["id"],
        rubric_score_payload("PLANNING", 4, conducted["version"]),
        make_evaluator_headers(ctx["evaluator"]["id"]),
    )
    validate_error(stale, ApiErrorId.ERR_STALE_OBSERVATION_VERSION.value, 412)

    rows, _meta = validate_paginated(api.list_rubric_scores(observation["id"], HR))
    unchanged = [row for row in rows if row["id"] == first_row["id"]][0]
    assert unchanged["raw_score"] == 2 and unchanged["superseded"] is False
    assert get_observation(observation["id"])["scored_domain_count"] == 1

    replacement = validate_success(
        api.create_rubric_score(
            observation["id"],
            rubric_score_payload("PLANNING", 4, current_version),
            make_evaluator_headers(ctx["evaluator"]["id"]),
        ),
        201,
    )
    assert replacement["raw_score"] == 4
    assert replacement["weighted_contribution"] == pytest.approx(0.88)
    assert replacement["superseded"] is False

    rows, _meta = validate_paginated(api.list_rubric_scores(observation["id"], HR))
    superseded = [row for row in rows if row["id"] == first_row["id"]][0]
    assert superseded["superseded"] is True, "the earlier row for the domain is superseded"

    observation = get_observation(observation["id"])
    assert observation["scored_domain_count"] == 1, "a supersede adds no new domain"
    assert observation["status"] == "CONDUCTED"
    assert observation["weighted_score"] is None


def test_every_reverse_reachability_listing_returns_an_array(api):
    """PRD §2.9: "Because foreign keys are never exposed as separately addressable
    sub-paths, each relationship in the model has a listing that makes it reachable
    in the reverse direction."
    PRD §3.4: "A domain's `weighted_contribution` is the domain's `raw_score`
    multiplied by that domain's policy weight in percent, multiplied by a factor,
    divided by 100, and rounded half-up to two decimal places."
    PRD §3.4: "Its `status` begins at `ATTACHED`, and its `submitted_by_role` is
    recorded from the `X-User-Role` header at attach time as either `EVALUATOR` or
    `TEACHER`."
    PRD §3.6: "A new measure begins at `status` `REPORTED` and records
    `cycle_version_after`, the cycle's `version` immediately after the write, so a
    client can chain further guarded writes without re-reading."
    PRD §3.2: "Resolution assigns the review a `sequence_index`, the 1-based
    position of this review among the evaluator's decided reviews ordered by
    `created_at` ascending, and only a review whose `outcome` is still `PENDING`
    may be resolved — a review that already reads `PASS` or `FAIL` is terminal and
    cannot be decided again."

    Design: Corner/endpoints/every_fk_reverse_channel_returns_an_array
    """
    ctx = setup_cycle()
    measure = report_growth_measure(ctx["cycle"]["id"], index_value=2.50,
                                    coverage_pct=40, measure_code="SLO")
    observation = schedule_observation(ctx["cycle"]["id"], ctx["evaluator"]["id"])
    conducted = conduct_observation(observation["id"], ctx["evaluator"]["id"])
    rubric_row = score_domain(observation["id"], ctx["evaluator"]["id"],
                              "PLANNING", 3, conducted["version"])
    artifact = attach_artifact(observation["id"],
                               make_teacher_headers(ctx["educator"]["id"]),
                               artifact_type="VIDEO", title="Lesson recording")

    rubric_rows, _m1 = validate_paginated(api.list_rubric_scores(observation["id"], HR))
    assert [row["id"] for row in rubric_rows] == [rubric_row["id"]]
    assert rubric_rows[0]["weighted_contribution"] == pytest.approx(0.66)
    assert rubric_rows[0]["superseded"] is False

    artifacts, _m2 = validate_paginated(api.list_evidence_artifacts(observation["id"], HR))
    assert [row["id"] for row in artifacts] == [artifact["id"]]
    assert artifacts[0]["status"] == "ATTACHED"
    assert artifacts[0]["submitted_by_role"] == "TEACHER"

    measures, _m3 = validate_paginated(api.list_growth_measures(ctx["cycle"]["id"], HR))
    assert [row["id"] for row in measures] == [measure["id"]]
    assert measures[0]["status"] == "REPORTED"

    reviews, _m4 = validate_paginated(
        api.list_calibration_reviews(ctx["evaluator"]["id"], HR))
    assert len(reviews) == 1, "the evaluator was certified by exactly one review"
    assert reviews[0]["outcome"] == "PASS"
    assert reviews[0]["sequence_index"] == 1

    assert get_observation(observation["id"])["scored_domain_count"] == 1
    assert get_observation(observation["id"])["status"] == "CONDUCTED"


def test_conducting_an_already_conducted_observation_is_a_state_violation(api):
    """PRD §3.3: "Marking the visit as having happened advances the observation
    from `SCHEDULED` to `CONDUCTED`, and only the assigned evaluator may do it —
    the acting `X-User-ID` must equal the observation's `evaluator_id`."
    PRD §2.8: "The target resource must be in a state from which the requested
    transition is declared, including the guards the parent cycle's `status` and
    `dispute_state` impose."
    PRD §2.8: "The rejection is `ERR_OBSERVATION_STATE_INVALID`,
    `ERR_CYCLE_STATE_INVALID`, `ERR_PLAN_STATE_INVALID`,
    `ERR_APPEAL_STATE_INVALID`, `ERR_GRIEVANCE_STATE_INVALID` or
    `ERR_TENURE_STATE_INVALID` according to the entity whose state was wrong, each
    HTTP 409."

    Design: Corner/state_machines/conduct_twice_returns_observation_state_invalid
    """
    ctx = setup_cycle()
    observation = add_observation(ctx, stop_at="CONDUCTED")

    response = api.conduct_observation(
        observation["id"], make_evaluator_headers(ctx["evaluator"]["id"]))
    validate_error(response, ApiErrorId.ERR_OBSERVATION_STATE_INVALID.value, 409)

    assert get_observation(observation["id"])["status"] == "CONDUCTED"
    assert get_cycle(ctx["cycle"]["id"])["status"] == "SCORING", (
        "no second bubble-up may fire"
    )


def test_raw_score_outside_the_four_point_scale_is_rejected(api):
    """PRD §3.4: "Recording a domain score is an evaluator-only act guarded by the
    observation's version: the payload carries a `domain_code` drawn from
    `PLANNING`, `ENVIRONMENT`, `INSTRUCTION` and `PROFESSIONALISM`, a `raw_score`
    that is a whole number from 1 through 4 inclusive on the district four-point
    scale, and the `expected_observation_version` described in §2.7."
    PRD §2.8: "This is where a `raw_score` outside the integers 1 through 4, an
    `index_value` outside 1.00 to 4.00, a `coverage_pct` that is not greater than 0
    or is greater than 100, a `scheduled_end` that is not strictly after its
    `scheduled_start`, an `adjusted_composite` outside 1.00 to 4.00, a rubric
    domain weight set that does not total 100, or an `observation_weight_pct` and
    `growth_weight_pct` pair that does not total 100 is caught."

    Design: Corner/entities/rubric_score_above_scale_maximum_is_rejected_as_invalid_request
    """
    ctx = setup_cycle(cycle_overrides={"cycle_type": "FOCUSED"})
    observation = schedule_observation(ctx["cycle"]["id"], ctx["evaluator"]["id"])
    conducted = conduct_observation(observation["id"], ctx["evaluator"]["id"])

    response = api.create_rubric_score(
        observation["id"],
        rubric_score_payload("PLANNING", 5, conducted["version"]),
        make_evaluator_headers(ctx["evaluator"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    reread = get_observation(observation["id"])
    assert reread["scored_domain_count"] == 0
    assert reread["status"] == "CONDUCTED"
    assert get_cycle(ctx["cycle"]["id"])["cycle_type"] == "FOCUSED"
