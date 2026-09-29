"""Improvement plans: extension guards, escalation and the tenure-track hold."""

from test_helpers import (
    ApiErrorId,
    HR_RECOMMENDER_HEADERS,
    TEST_USERS,
    get_educator,
    get_plan,
    list_plans,
    set_clock,
    setup_ineffective_cycle_with_plan,
    validate_error,
    validate_success,
)

HR = TEST_USERS["hr_admin_headers"]

REMEDIATION_POLICY = {"required_formal_count": 1, "required_informal_count": 0,
                      "remediation_days": 90, "max_plan_extension_days": 45}

TENURE_HOLD_POLICY = {"required_formal_count": 1, "required_informal_count": 0,
                      "tenure_required_years": 3, "tenure_min_consecutive_effective": 0}


def test_plan_extension_respects_the_cap_the_due_date_and_the_plan_state(api):
    """PRD §3.7: "Either way the new plan records the `cycle_id` of the cycle whose
    rating triggered it and the `educator_id` of the educator under remediation,
    begins at `status` `ACTIVE` with `extension_days_used` at 0, stamps
    `started_at` with the logical clock instant at creation, and sets `due_at` to
    `started_at` plus the policy's `remediation_days`, which is ninety calendar
    days by default."
    PRD §3.7: "And `extension_days_used` plus the requested `additional_days` must
    not exceed the policy's `max_plan_extension_days` — forty-five days cumulative
    by default — with an exact hit on the cap permitted and only an overshoot
    rejected, with `ERR_PLAN_EXTENSION_LIMIT`."
    PRD §3.7: "The logical clock must be on or before the plan's current `due_at`;
    a plan already past its date cannot be extended and yields `ERR_PLAN_PAST_DUE`."
    PRD §3.7: "An accepted extension advances `due_at` by `additional_days`,
    increases `extension_days_used` by the same amount, and increments the plan's
    `version` by 1."
    PRD §3.7: "A `SUCCESS` outcome moves the plan to `COMPLETED_SUCCESS` and clears
    the educator's `tenure_track_hold` to false, provided no other plan of that
    educator remains in `ACTIVE` or `EXTENDED`."
    PRD §3.7: "`COMPLETED_SUCCESS`, `COMPLETED_FAIL` and `VOIDED` are all terminal
    for a plan."

    Design: Corner/validations/improvement_plan_extension_cap_past_due_and_closed_plan_guards
    """
    ctx = setup_ineffective_cycle_with_plan(policy_overrides=dict(REMEDIATION_POLICY))
    plan = ctx["plan"]
    assert plan["due_at"].startswith("2026-11-30"), (
        f"90 days from 2026-09-01 is 2026-11-30, got {plan['due_at']}"
    )

    over_cap = api.extend_improvement_plan(
        plan["id"], {"additional_days": 50, "expected_plan_version": plan["version"]}, HR)
    validate_error(over_cap, ApiErrorId.ERR_PLAN_EXTENSION_LIMIT.value, 422)
    assert get_plan(plan["id"])["extension_days_used"] == 0

    extended = validate_success(
        api.extend_improvement_plan(
            plan["id"],
            {"additional_days": 30, "expected_plan_version": plan["version"]}, HR)
    )
    assert extended["status"] == "EXTENDED"
    assert extended["extension_days_used"] == 30
    assert extended["due_at"].startswith("2026-12-30")

    set_clock("2026-12-31T00:00:00Z")
    past_due = api.extend_improvement_plan(
        plan["id"], {"additional_days": 10, "expected_plan_version": extended["version"]}, HR)
    validate_error(past_due, ApiErrorId.ERR_PLAN_PAST_DUE.value, 422)

    set_clock("2026-10-01T00:00:00Z")
    closed = validate_success(
        api.close_improvement_plan(plan["id"], {"outcome": "SUCCESS"}, HR))
    assert closed["status"] == "COMPLETED_SUCCESS"
    assert get_educator(ctx["educator"]["id"])["tenure_track_hold"] is False

    on_closed = api.extend_improvement_plan(
        plan["id"], {"additional_days": 5, "expected_plan_version": closed["version"]}, HR)
    validate_error(on_closed, ApiErrorId.ERR_PLAN_STATE_INVALID.value, 409)


def test_a_failed_first_plan_escalates_and_a_failed_successor_non_renews(api):
    """PRD §3.7: "A plan created by a finalized `INEFFECTIVE` rating carries
    `trigger_reason` of `INEFFECTIVE_RATING`, `escalation_level` of 1, and a null
    `prior_plan_id`."
    PRD §3.7: "At level 1 the district escalates rather than dismisses: a successor
    plan is created immediately, with `prior_plan_id` set to the plan that just
    failed, `escalation_level` of 2, `trigger_reason` of `PRIOR_PLAN_FAILED`,
    `status` `ACTIVE`, `started_at` at the current logical clock and `due_at` at
    `started_at` plus the policy's `remediation_days`; because a plan of the
    educator is again open, `tenure_track_hold` stays true."
    PRD §3.7: "At level 2 the remedy is exhausted: the educator's `tenure_status`
    is set to `NON_RENEWED` and their `tenure_track_hold` is cleared to false."

    Design: Corner/state_machines/improvement_plan_fail_escalates_then_second_fail_non_renews_educator
    """
    ctx = setup_ineffective_cycle_with_plan(policy_overrides=dict(REMEDIATION_POLICY))
    first_plan = ctx["plan"]
    assert first_plan["escalation_level"] == 1
    assert first_plan["trigger_reason"] == "INEFFECTIVE_RATING"
    assert first_plan["prior_plan_id"] is None
    assert first_plan["due_at"].startswith("2026-11-30")

    failed = validate_success(
        api.close_improvement_plan(first_plan["id"], {"outcome": "FAIL"}, HR))
    assert failed["status"] == "COMPLETED_FAIL"
    assert get_educator(ctx["educator"]["id"])["tenure_track_hold"] is True, (
        "the successor plan keeps the educator on hold"
    )

    successors = list_plans(prior_plan_id=first_plan["id"])
    assert len(successors) == 1, "a failed level-1 plan spawns exactly one successor"
    successor = successors[0]
    assert successor["prior_plan_id"] == first_plan["id"]
    assert successor["escalation_level"] == 2
    assert successor["trigger_reason"] == "PRIOR_PLAN_FAILED"
    assert successor["status"] == "ACTIVE"

    second_failure = validate_success(
        api.close_improvement_plan(successor["id"], {"outcome": "FAIL"}, HR))
    assert second_failure["status"] == "COMPLETED_FAIL"

    educator = get_educator(ctx["educator"]["id"])
    assert educator["tenure_status"] == "NON_RENEWED"
    assert educator["tenure_track_hold"] is False


def test_plan_extension_carrying_a_superseded_plan_version_is_rejected(api):
    """PRD §2.7: "Extending an improvement plan's remediation deadline requires
    `expected_plan_version` in the request body, non-optional. The value must equal
    that plan's current `version`; a mismatch is rejected with
    `ERR_STALE_PLAN_VERSION` (HTTP 412)."
    PRD §3.7: "An accepted extension advances `due_at` by `additional_days`,
    increases `extension_days_used` by the same amount, and increments the plan's
    `version` by 1."

    Design: Corner/cross_cutting_layers/improvement_plan_extension_with_stale_plan_version_is_rejected
    """
    ctx = setup_ineffective_cycle_with_plan(policy_overrides=dict(REMEDIATION_POLICY))
    plan = ctx["plan"]

    extended = validate_success(
        api.extend_improvement_plan(
            plan["id"],
            {"additional_days": 10, "expected_plan_version": plan["version"]}, HR)
    )
    assert extended["status"] == "EXTENDED"
    assert extended["extension_days_used"] == 10
    assert extended["due_at"].startswith("2026-12-10")

    stale = api.extend_improvement_plan(
        plan["id"], {"additional_days": 5, "expected_plan_version": plan["version"]}, HR)
    validate_error(stale, ApiErrorId.ERR_STALE_PLAN_VERSION.value, 412)

    reread = get_plan(plan["id"])
    assert reread["extension_days_used"] == 10, "the rejected extension adds no days"
    assert reread["due_at"].startswith("2026-12-10")
    assert reread["status"] == "EXTENDED"


class TestTenureHoldFromAnOpenPlan:
    """Both numeric gates are met; the live plan is the only obstacle."""

    @staticmethod
    def _educator_with_an_open_plan():
        return setup_ineffective_cycle_with_plan(
            clock="2026-08-01T00:00:00Z",
            policy_overrides=dict(TENURE_HOLD_POLICY),
            educator_overrides={"employee_number": "E-A301",
                                "service_start_date": "2023-08-02"},
        )

    def test_recommendation_is_refused_while_an_improvement_plan_holds_the_educator(self, api):
        """PRD §3.7: "While any plan of an educator sits at `ACTIVE` or `EXTENDED`,
        that educator's `tenure_track_hold` reads true, and tenure progression is
        frozen."
        PRD §3.9: "An educator is eligible for a tenure recommendation when
        `completed_service_years` is at or above the policy's
        `tenure_required_years`, `consecutive_effective_years` is at or above the
        policy's `tenure_min_consecutive_effective`, and `tenure_track_hold` is
        false."
        PRD §3.9: "it is refused with `ERR_TENURE_NOT_ELIGIBLE` when any of the
        three eligibility conditions fails — insufficient service years, an
        insufficient run of effective ratings, or a live improvement-plan hold."

        Design: Difficulty/cross_entity_state_dependency/tenure_recommendation_blocked_by_active_improvement_plan
        """
        ctx = self._educator_with_an_open_plan()
        educator = get_educator(ctx["educator"]["id"])
        assert educator["completed_service_years"] == 3, (
            "1095 days of service is exactly three completed years"
        )
        assert educator["tenure_track_hold"] is True

        response = api.tenure_recommendation(
            ctx["educator"]["id"], {"recommendation": "RECOMMEND"},
            HR_RECOMMENDER_HEADERS)
        validate_error(response, ApiErrorId.ERR_TENURE_NOT_ELIGIBLE.value, 422)

    def test_the_refused_recommendation_leaves_the_educator_probationary(self, api):
        """PRD §3.9: "A `RECOMMEND` moves `tenure_status` from `PROBATIONARY` to
        `RECOMMENDED` and stamps the acting operator's `X-User-ID` onto
        `tenure_recommended_by_user_id`; it is refused with
        `ERR_TENURE_NOT_ELIGIBLE` when any of the three eligibility conditions
        fails — insufficient service years, an insufficient run of effective
        ratings, or a live improvement-plan hold."
        PRD §3.7: "A plan created by a finalized `INEFFECTIVE` rating carries
        `trigger_reason` of `INEFFECTIVE_RATING`, `escalation_level` of 1, and a
        null `prior_plan_id`."

        Design: Difficulty/cross_entity_state_dependency/tenure_recommendation_blocked_by_active_improvement_plan
        """
        ctx = self._educator_with_an_open_plan()
        api.tenure_recommendation(ctx["educator"]["id"], {"recommendation": "RECOMMEND"},
                                  HR_RECOMMENDER_HEADERS)

        educator = get_educator(ctx["educator"]["id"])
        assert educator["tenure_status"] == "PROBATIONARY"
        assert educator["tenure_recommended_by_user_id"] is None

        plan = get_plan(ctx["plan"]["id"])
        assert plan["status"] == "ACTIVE"
        assert plan["escalation_level"] == 1
        assert plan["trigger_reason"] == "INEFFECTIVE_RATING"
