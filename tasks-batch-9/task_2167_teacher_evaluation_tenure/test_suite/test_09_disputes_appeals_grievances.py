"""Appeals, grievances, the independent dispute dimension and its cascades."""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    decide_appeal,
    decide_grievance,
    file_appeal,
    file_grievance,
    get_cycle,
    get_educator,
    get_grievance,
    get_observation,
    get_plan,
    make_teacher_headers,
    review_appeal,
    set_clock,
    setup_finalized_cycle,
    setup_ineffective_cycle_with_plan,
    setup_upheld_appeal,
    validate_error,
    validate_paginated,
    validate_success,
)

HR = TEST_USERS["hr_admin_headers"]
UNION = TEST_USERS["union_rep_headers"]

BLENDED_POLICY = {"required_formal_count": 1, "required_informal_count": 1}


class TestDisputeDimensionIsIndependent:
    """dispute_state walks four transitions while status stays FINALIZED."""

    @staticmethod
    def _finalized_effective_cycle():
        return setup_finalized_cycle(
            policy_overrides=dict(BLENDED_POLICY),
            formal_scores=(3, 3, 4, 3), informal_scores=(3, 3, 3, 3),
            artifacts=2, growth_index=3.00, growth_coverage=100,
            second_evaluator=True,
        )

    def test_dispute_state_walks_to_grievance_resolved_while_status_holds(self, api):
        """PRD §3.8: "A successful filing creates the appeal at `status` `FILED`
        with `panelist_evaluator_id`, `adjusted_composite` and `decided_at` all
        null, moves the cycle's `dispute_state` from `NONE` to `APPEALED`, and
        increments the cycle's `version`."
        PRD §3.8: "Every decision stamps `decided_at` with the logical clock
        instant, moves the cycle's `dispute_state` from `APPEALED` to
        `APPEAL_RESOLVED`, and increments the cycle's `version`."
        PRD §3.8: "A successful filing creates the grievance at `status` `FILED`
        with `remedy` of `NONE`, moves the cycle's `dispute_state` from
        `APPEAL_RESOLVED` to `GRIEVED`, and increments the cycle's `version`."
        PRD §3.8: "Every outcome moves the cycle's `dispute_state` from `GRIEVED`
        to `GRIEVANCE_RESOLVED` — the terminal state of that dimension — and
        increments the cycle's `version`."

        Design: Difficulty/non_linear_state_machine/cycle_status_and_dispute_state_advance_independently
        """
        ctx = self._finalized_effective_cycle()
        cycle_id = ctx["cycle"]["id"]

        appeal = file_appeal(cycle_id, ctx["educator"]["id"], grounds="SCORING",
                             statement="Domain 3 rating is not supported by the record")
        cycle = get_cycle(cycle_id)
        assert cycle["dispute_state"] == "APPEALED" and cycle["status"] == "FINALIZED"

        review_appeal(appeal["id"], ctx["evaluator2"]["id"])
        decide_appeal(appeal["id"], ctx["evaluator2"]["id"], "UPHELD")
        cycle = get_cycle(cycle_id)
        assert cycle["dispute_state"] == "APPEAL_RESOLVED" and cycle["status"] == "FINALIZED"

        grievance = file_grievance(appeal["id"], "ART_12_EVALUATION")
        cycle = get_cycle(cycle_id)
        assert cycle["dispute_state"] == "GRIEVED" and cycle["status"] == "FINALIZED"

        decide_grievance(grievance["id"], "DENY")
        cycle = get_cycle(cycle_id)
        assert cycle["dispute_state"] == "GRIEVANCE_RESOLVED"
        assert cycle["status"] == "FINALIZED", (
            "the status dimension never moves on dispute triggers"
        )

    def test_the_rating_survives_the_whole_dispute_walk_untouched(self, api):
        """PRD §3.8: "An **`UPHELD`** appeal upholds the district's original
        determination. Nothing about the rating changes: `composite_score`,
        `composite_rating`, `composite_variant` and the cycle's `status` all stand
        exactly as they were, and no improvement plan is disturbed."
        PRD §3.8: "A `DENY` moves the grievance to `DENIED` and leaves `remedy` at
        `NONE`; a `WITHDRAW` moves it to `WITHDRAWN` and likewise leaves `remedy`
        at `NONE`; in both cases the rating and any open plan stand untouched."

        Design: Difficulty/non_linear_state_machine/cycle_status_and_dispute_state_advance_independently
        """
        ctx = self._finalized_effective_cycle()
        cycle_id = ctx["cycle"]["id"]
        assert ctx["cycle"]["composite_score"] == pytest.approx(3.15)
        assert ctx["cycle"]["composite_rating"] == "EFFECTIVE"

        appeal = file_appeal(cycle_id, ctx["educator"]["id"], grounds="SCORING",
                             statement="Domain 3 rating is not supported by the record")
        assert get_cycle(cycle_id)["composite_score"] == pytest.approx(3.15)

        review_appeal(appeal["id"], ctx["evaluator2"]["id"])
        upheld = decide_appeal(appeal["id"], ctx["evaluator2"]["id"], "UPHELD")
        assert upheld["status"] == "UPHELD"
        assert get_cycle(cycle_id)["composite_rating"] == "EFFECTIVE"

        grievance = file_grievance(appeal["id"], "ART_12_EVALUATION")
        denied = decide_grievance(grievance["id"], "DENY")
        assert denied["status"] == "DENIED"
        assert denied["remedy"] == "NONE"

        cycle = get_cycle(cycle_id)
        assert cycle["composite_score"] == pytest.approx(3.15)
        assert cycle["composite_rating"] == "EFFECTIVE"


class TestAppealRemandCascade:
    """REMANDED reverts the cycle, voids the plan and releases the tenure hold."""

    @staticmethod
    def _ineffective_cycle_under_review():
        ctx = setup_ineffective_cycle_with_plan(second_evaluator=True)
        appeal = file_appeal(ctx["cycle"]["id"], ctx["educator"]["id"],
                             grounds="PROCEDURAL",
                             statement="The required pre-conference never happened")
        ctx["appeal"] = review_appeal(appeal["id"], ctx["evaluator2"]["id"])
        return ctx

    def test_remand_reverts_the_cycle_and_clears_every_composite_field(self, api):
        """PRD §3.8: "A **`REMANDED`** appeal sends the work back. The cycle takes
        its reversion from `FINALIZED` back to `SCORING`, and in doing so
        `composite_score`, `composite_rating`, `composite_variant`, `finalized_at`
        and `appeal_deadline` are all cleared to null and `evidence_adjustment` is
        reset to 0."
        PRD §3.8: "Every decision stamps `decided_at` with the logical clock
        instant, moves the cycle's `dispute_state` from `APPEALED` to
        `APPEAL_RESOLVED`, and increments the cycle's `version`."

        Design: Difficulty/transitive_cascade/appeal_remand_reverts_cycle_voids_plan_and_releases_tenure_hold
        """
        ctx = self._ineffective_cycle_under_review()
        before = get_cycle(ctx["cycle"]["id"])
        assert before["composite_score"] == pytest.approx(1.00)
        assert before["composite_rating"] == "INEFFECTIVE"

        remanded = decide_appeal(ctx["appeal"]["id"], ctx["evaluator2"]["id"], "REMANDED")
        assert remanded["status"] == "REMANDED"

        cycle = get_cycle(ctx["cycle"]["id"])
        assert cycle["status"] == "SCORING"
        assert cycle["dispute_state"] == "APPEAL_RESOLVED"
        assert cycle["composite_score"] is None
        assert cycle["composite_rating"] is None
        assert cycle["composite_variant"] is None
        assert cycle["finalized_at"] is None
        assert cycle["appeal_deadline"] is None
        assert cycle["evidence_adjustment"] == pytest.approx(0.00)

    def test_remand_voids_the_plan_and_releases_the_tenure_hold(self, api):
        """PRD §3.8: "Every improvement plan of that cycle sitting at `ACTIVE` or
        `EXTENDED` transitions to `VOIDED`; that plan voiding clears the educator's
        `tenure_track_hold` to false and recomputes the educator's
        `consecutive_effective_years` and `last_composite_rating`."
        PRD §3.9: "`consecutive_effective_years` is the length of the trailing run
        of that history whose `composite_rating` is `EFFECTIVE` or
        `HIGHLY_EFFECTIVE`, counted backwards from the most recent entry and
        stopping at the first entry that is neither."
        PRD §3.9: "`last_composite_rating` is the `composite_rating` of the most
        recent entry of that history, or null when the history is empty."

        Design: Difficulty/transitive_cascade/appeal_remand_reverts_cycle_voids_plan_and_releases_tenure_hold
        """
        ctx = self._ineffective_cycle_under_review()
        assert get_plan(ctx["plan"]["id"])["status"] == "ACTIVE"
        assert get_educator(ctx["educator"]["id"])["tenure_track_hold"] is True

        decide_appeal(ctx["appeal"]["id"], ctx["evaluator2"]["id"], "REMANDED")

        assert get_plan(ctx["plan"]["id"])["status"] == "VOIDED"
        educator = get_educator(ctx["educator"]["id"])
        assert educator["tenure_track_hold"] is False
        assert educator["consecutive_effective_years"] == 0
        assert educator["last_composite_rating"] is None, (
            "the reverted cycle leaves no FINALIZED or CLOSED history"
        )
        assert get_observation(ctx["formal_observation"]["id"])["status"] == "SUBMITTED", (
            "the remand does not touch the observation ledger"
        )


class TestGrievanceRequiresAnExhaustedRemedy:
    """A MODIFIED appeal resolves the dispute but does not exhaust the remedy."""

    @staticmethod
    def _modified_appeal():
        ctx = setup_ineffective_cycle_with_plan(second_evaluator=True)
        appeal = file_appeal(ctx["cycle"]["id"], ctx["educator"]["id"],
                             grounds="EVIDENTIARY",
                             statement="The artifact record was not considered")
        review_appeal(appeal["id"], ctx["evaluator2"]["id"])
        ctx["appeal"] = decide_appeal(appeal["id"], ctx["evaluator2"]["id"],
                                      "MODIFIED", adjusted_composite=3.00)
        return ctx

    def test_a_modified_decision_replaces_the_composite_and_voids_the_plan(self, api):
        """PRD §3.8: "A **`MODIFIED`** appeal replaces the number. The appeal's
        `adjusted_composite` is stored on the appeal, the cycle's `composite_score`
        is set to that value, and the cycle's `composite_rating` is reassigned from
        the band of that value under the policy thresholds."
        PRD §3.8: "And if the new `composite_rating` is anything other than
        `INEFFECTIVE`, every improvement plan of that cycle sitting at `ACTIVE` or
        `EXTENDED` transitions to `VOIDED`, and that voiding clears the educator's
        `tenure_track_hold` to false. The cycle's `status` remains `FINALIZED`."

        Design: Difficulty/cross_entity_state_dependency/grievance_blocked_until_appeal_is_upheld
        """
        ctx = self._modified_appeal()

        assert ctx["appeal"]["status"] == "MODIFIED"
        assert ctx["appeal"]["adjusted_composite"] == pytest.approx(3.00)

        cycle = get_cycle(ctx["cycle"]["id"])
        assert cycle["composite_score"] == pytest.approx(3.00)
        assert cycle["composite_rating"] == "EFFECTIVE"
        assert cycle["status"] == "FINALIZED"
        assert cycle["dispute_state"] == "APPEAL_RESOLVED"

        assert get_plan(ctx["plan"]["id"])["status"] == "VOIDED"
        assert get_educator(ctx["educator"]["id"])["tenure_track_hold"] is False

    def test_a_grievance_against_a_modified_appeal_is_refused(self, api):
        """PRD §3.8: "Once an appeal has been decided `UPHELD`, and only then, a
        `UnionRep` may escalate to a contractual grievance."
        PRD §3.8: "Filing against an appeal in any other status — `FILED`,
        `UNDER_REVIEW`, `MODIFIED` or `REMANDED` — is refused with
        `ERR_APPEAL_NOT_EXHAUSTED`."

        Design: Difficulty/cross_entity_state_dependency/grievance_blocked_until_appeal_is_upheld
        """
        ctx = self._modified_appeal()

        response = api.create_grievance(
            {"appeal_id": ctx["appeal"]["id"], "article_code": "ART_12_EVALUATION"},
            UNION)
        validate_error(response, ApiErrorId.ERR_APPEAL_NOT_EXHAUSTED.value, 422)

        assert get_cycle(ctx["cycle"]["id"])["dispute_state"] == "APPEAL_RESOLVED", (
            "the rejected filing must not advance the dispute dimension"
        )
        grievances, _meta = validate_paginated(
            api.list_grievances(HR, params={"appeal_id": ctx["appeal"]["id"]}))
        assert grievances == []


def test_a_sustained_grievance_voids_the_plan_and_then_becomes_terminal(api):
    """PRD §3.8: "A `SUSTAIN` moves the grievance to `SUSTAINED` and stores the
    requested `remedy`, which is either `RATING_VACATED` or `PLAN_VOIDED`, and the
    two remedies differ in reach."
    PRD §3.8: "`PLAN_VOIDED` reaches only as far as the remediation: every
    improvement plan of the cycle in `ACTIVE` or `EXTENDED` transitions to `VOIDED`
    and the educator's `tenure_track_hold` is cleared, but the rating itself stands
    and the cycle stays `FINALIZED`."
    PRD §3.8: "A grievance is decided from `FILED` only, and the decision carries
    an `outcome` of `SUSTAIN`, `DENY` or `WITHDRAW` plus an optional `remedy`."
    PRD §2.8: "The rejection is `ERR_OBSERVATION_STATE_INVALID`,
    `ERR_CYCLE_STATE_INVALID`, `ERR_PLAN_STATE_INVALID`, `ERR_APPEAL_STATE_INVALID`,
    `ERR_GRIEVANCE_STATE_INVALID` or `ERR_TENURE_STATE_INVALID` according to the
    entity whose state was wrong, each HTTP 409."

    Design: Corner/state_machines/grievance_sustained_with_plan_voided_remedy_then_second_decision_is_rejected
    """
    ctx = setup_ineffective_cycle_with_plan(second_evaluator=True)
    appeal = setup_upheld_appeal(ctx)
    grievance = file_grievance(appeal["id"], "ART_12_EVALUATION")

    assert grievance["status"] == "FILED"
    assert get_cycle(ctx["cycle"]["id"])["dispute_state"] == "GRIEVED"
    assert get_plan(ctx["plan"]["id"])["status"] == "ACTIVE"
    assert get_educator(ctx["educator"]["id"])["tenure_track_hold"] is True

    sustained = validate_success(
        api.decide_grievance(grievance["id"],
                             {"outcome": "SUSTAIN", "remedy": "PLAN_VOIDED"}, HR))
    assert sustained["status"] == "SUSTAINED"
    assert sustained["remedy"] == "PLAN_VOIDED"

    assert get_plan(ctx["plan"]["id"])["status"] == "VOIDED"
    assert get_educator(ctx["educator"]["id"])["tenure_track_hold"] is False

    cycle = get_cycle(ctx["cycle"]["id"])
    assert cycle["dispute_state"] == "GRIEVANCE_RESOLVED"
    assert cycle["status"] == "FINALIZED"
    assert cycle["composite_rating"] == "INEFFECTIVE", (
        "the PLAN_VOIDED remedy leaves the rating standing"
    )

    second = api.decide_grievance(grievance["id"], {"outcome": "DENY"}, HR)
    validate_error(second, ApiErrorId.ERR_GRIEVANCE_STATE_INVALID.value, 409)
    assert get_grievance(grievance["id"])["status"] == "SUSTAINED"


def test_the_appeal_window_closes_before_the_cycle_may_be_closed(api):
    """PRD §3.6: "The logical clock must be strictly after the cycle's
    `appeal_deadline` — closing on or before the deadline is refused with
    `ERR_CLOSE_BEFORE_APPEAL_DEADLINE` — and the cycle's `dispute_state` must be
    one of `NONE`, `APPEAL_RESOLVED` or `GRIEVANCE_RESOLVED`, so a live `APPEALED`
    or `GRIEVED` posture blocks closure."
    PRD §3.6: "Finalization recomputes the composite under the **`FINAL`** variant,
    applies the evidence-sufficiency adjustment on top of it, sets
    `composite_variant` to `FINAL`, assigns `composite_rating` from the band of the
    adjusted score, stamps `finalized_at` with the logical clock instant, sets
    `appeal_deadline` to `finalized_at` plus the policy's `appeal_window_days`, and
    increments the cycle's `version`."
    PRD §3.8: "Filing requires the cycle's `status` to read `FINALIZED` and the
    logical clock to be on or before the cycle's `appeal_deadline`; filing after
    the deadline has passed is refused with `ERR_APPEAL_WINDOW_CLOSED`."

    Design: Corner/validations/cycle_close_and_appeal_window_boundaries
    """
    ctx = setup_finalized_cycle(
        policy_overrides={"required_formal_count": 1, "required_informal_count": 0,
                          "appeal_window_days": 15, "evidence_min_artifacts": 2},
        formal_scores=(3, 3, 4, 3), artifacts=2,
        growth_index=3.00, growth_coverage=100,
    )
    cycle = ctx["cycle"]
    assert cycle["finalized_at"].startswith("2026-09-01")
    assert cycle["appeal_deadline"].startswith("2026-09-16")
    assert cycle["composite_score"] == pytest.approx(3.20)

    early = api.close_evaluation_cycle(cycle["id"], HR)
    validate_error(early, ApiErrorId.ERR_CLOSE_BEFORE_APPEAL_DEADLINE.value, 422)

    set_clock("2026-09-17T00:00:00Z")

    late_appeal = api.create_appeal(
        {"cycle_id": cycle["id"], "grounds": "SCORING",
         "statement": "Filed one day too late"},
        make_teacher_headers(ctx["educator"]["id"]),
    )
    validate_error(late_appeal, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED.value, 422)
    appeals, _meta = validate_paginated(
        api.list_appeals(HR, params={"cycle_id": cycle["id"]}))
    assert appeals == [], "the late filing must create no appeal"

    closed = validate_success(api.close_evaluation_cycle(cycle["id"], HR))
    assert closed["status"] == "CLOSED"
    assert closed["dispute_state"] == "NONE"
    assert closed["composite_score"] == pytest.approx(3.20), (
        "closure does not disturb the stored composite"
    )
