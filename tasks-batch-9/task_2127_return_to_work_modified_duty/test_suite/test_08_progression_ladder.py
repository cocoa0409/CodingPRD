"""The progression ladder: opening reviews, the four decision branches, the
deferral cycle and the step ceiling."""
from test_helpers import (
    ApiErrorId,
    assert_progression_review,
    fixtures,
    validate_error,
    validate_success,
)


def test_an_advance_propagates_the_capped_targets_and_forks_the_next_rung(api):
    """PRD §3.7: "`target_hours_per_day` is the least of three quantities: the placement's current `scheduled_hours_per_day` plus the one-hour progression step; the `max_hours_per_day` published by the claim's currently `ACTIVE` restriction set; and the worker's `pre_injury_weekly_hours` divided by the five workdays in a week. `target_lift_lbs` is the lesser of two quantities: the job's `demand_lift_lbs` increased by 25 percent — that is, multiplied by 1.25 and rounded half up to two decimal places — and the same active set's `max_lift_lbs`. Both targets are expressed to two decimal places, rounded half up. The placement's `scheduled_hours_per_day` is then set to `target_hours_per_day`, its `progression_step` rises by 1, and its `match_score` and `projected_weekly_cost_cents` are recomputed against the new schedule. Finally the next rung is forked: a new review is created with `step_index` one greater than the review just decided, `review_status` `SCHEDULED`, and a `due_date` 30 days after the logical clock's calendar date."

    Design: Corner/calculations/progression_advance_target_capped_by_active_restriction
    """
    ctx = fixtures.setup_active_placement()
    fixtures.open_progression_review(ctx)

    decided = validate_success(
        api.decide_progression_review(
            ctx["progression_review_id"],
            {"decision": "ADVANCE", "outcome_note": "Tolerating four hours well"},
            fixtures.COORD,
        )
    )

    assert_progression_review(decided)
    assert decided["review_status"] == "ADVANCED"
    assert decided["target_hours_per_day"] == 5, (
        f"min(4 + 1, restriction 6, pre-injury 40 / 5) is 5, got "
        f"{decided['target_hours_per_day']}"
    )
    assert decided["target_lift_lbs"] == 12.50, (
        f"min(round(10 * 1.25, 2), 20) is 12.50, got {decided['target_lift_lbs']}"
    )

    placement = validate_success(api.get_placement(ctx["placement_id"], fixtures.COORD))
    assert placement["scheduled_hours_per_day"] == 5
    assert placement["progression_step"] == 1
    next_review = validate_success(
        api.get_progression_review(placement["current_progression_review_id"], fixtures.COORD)
    )
    assert next_review["step_index"] == 2
    assert next_review["review_status"] == "SCHEDULED"
    assert next_review["due_date"] == "2026-08-31", (
        "30 days after the logical clock's 2026-08-01 calendar date"
    )


def test_the_deferral_cycle_stops_at_the_second_deferral(api):
    """PRD §3.7: "A **`DEFER`** is the one branch that is not terminal: it moves the review `IN_REVIEW → SCHEDULED`, raising `deferral_count` by 1, pushing `due_date` out by a further 14 days, and clearing `reviewed_by_user_id` so the next opener is recorded afresh. The `IN_REVIEW → SCHEDULED → IN_REVIEW` cycle is bounded: at priority 33 a deferral is refused with `ERR_MAX_DEFERRALS_REACHED` and HTTP 422 once the review's `deferral_count` has reached the ceiling of two."
    PRD §3.7: "The first review is created automatically at activation with `step_index` 1 and a `due_date` 30 days after the placement's `start_date`."

    Design: Corner/state_machines/progression_review_defer_cycle_stops_at_max_deferrals
    """
    ctx = fixtures.setup_active_placement()
    review_id = ctx["progression_review_id"]

    fixtures.open_progression_review(ctx, review_id)
    first = validate_success(
        api.decide_progression_review(
            review_id, {"decision": "DEFER", "outcome_note": "Provider unavailable"},
            fixtures.COORD,
        )
    )
    fixtures.open_progression_review(ctx, review_id)
    second = validate_success(
        api.decide_progression_review(
            review_id, {"decision": "DEFER", "outcome_note": "Still unavailable"},
            fixtures.COORD,
        )
    )
    fixtures.open_progression_review(ctx, review_id)
    third = api.decide_progression_review(
        review_id, {"decision": "DEFER", "outcome_note": "Third attempt"}, fixtures.COORD
    )

    assert first["review_status"] == "SCHEDULED"
    assert first["deferral_count"] == 1
    assert first["due_date"] == "2026-09-16", "2026-09-02 pushed out by a further 14 days"
    assert second["review_status"] == "SCHEDULED"
    assert second["deferral_count"] == 2
    assert second["due_date"] == "2026-09-30"
    validate_error(third, ApiErrorId.ERR_MAX_DEFERRALS_REACHED, 422)
    final = validate_success(api.get_progression_review(review_id, fixtures.COORD))
    assert final["deferral_count"] == 2


def test_a_fifth_advance_is_refused_at_the_step_ceiling(api):
    """PRD §3.7: "It additionally requires that the placement's `progression_step` be strictly below the ceiling of four steps, or the request answers `ERR_MAX_PROGRESSION_STEPS` with HTTP 422 at priority 32."

    Design: Corner/validations/fifth_progression_advance_is_rejected_at_max_steps
    """
    ctx = fixtures.setup_active_placement()
    placement = fixtures.advance_progression_steps(ctx, 4)
    assert placement["progression_step"] == 4
    fifth_review_id = ctx["progression_review_id"]
    fixtures.open_progression_review(ctx, fifth_review_id)

    resp = api.decide_progression_review(
        fifth_review_id, {"decision": "ADVANCE", "outcome_note": "Fifth step"}, fixtures.COORD
    )

    validate_error(resp, ApiErrorId.ERR_MAX_PROGRESSION_STEPS, 422)
    still = validate_success(api.get_progression_review(fifth_review_id, fixtures.COORD))
    assert still["review_status"] == "IN_REVIEW"
    unchanged = validate_success(api.get_placement(ctx["placement_id"], fixtures.COORD))
    assert unchanged["scheduled_hours_per_day"] == 6, (
        "the schedule saturated at the restriction ceiling of 6 hours"
    )


def test_an_advance_is_refused_while_a_panel_is_deliberating(api):
    """PRD §3.7: "Two of them share a common bar: at priority 43, an `ADVANCE` or an `EXTEND` is refused with `ERR_CASE_REVIEW_IN_PROGRESS` and HTTP 409 whenever any case-review panel of that placement sits in `OPEN` or `VOTING` — the ladder does not move while a panel is deliberating."

    Design: Difficulty/cross_entity_state_dependency/progression_advance_gated_on_open_case_review
    """
    ctx = fixtures.setup_active_placement()
    fixtures.open_progression_review(ctx)
    fixtures.convene_panel(ctx, trigger_reason="DURATION_CAP", quorum_required=3)

    resp = api.decide_progression_review(
        ctx["progression_review_id"],
        {"decision": "ADVANCE", "outcome_note": "Worker tolerating four hours"},
        fixtures.COORD,
    )

    validate_error(resp, ApiErrorId.ERR_CASE_REVIEW_IN_PROGRESS, 409)


def test_the_refused_advance_leaves_the_review_and_the_ladder_untouched(api):
    """PRD §3.7: "An **`ADVANCE`** moves the review `IN_REVIEW → ADVANCED` and steps the worker up."
    PRD §3.7: "at priority 43, an `ADVANCE` or an `EXTEND` is refused with `ERR_CASE_REVIEW_IN_PROGRESS` and HTTP 409 whenever any case-review panel of that placement sits in `OPEN` or `VOTING`"

    Design: Difficulty/cross_entity_state_dependency/progression_advance_gated_on_open_case_review
    """
    ctx = fixtures.setup_active_placement()
    fixtures.open_progression_review(ctx)
    panel = fixtures.convene_panel(ctx, trigger_reason="DURATION_CAP", quorum_required=3)
    api.decide_progression_review(
        ctx["progression_review_id"],
        {"decision": "ADVANCE", "outcome_note": "Worker tolerating four hours"},
        fixtures.COORD,
    )

    review = validate_success(
        api.get_progression_review(ctx["progression_review_id"], fixtures.COORD)
    )
    assert review["review_status"] == "IN_REVIEW", (
        "the review sits in a perfectly legal IN_REVIEW state and stays there"
    )
    placement = validate_success(api.get_placement(ctx["placement_id"], fixtures.COORD))
    assert placement["progression_step"] == 0
    still_open = validate_success(api.get_case_review(panel["id"], fixtures.NURSE))
    assert still_open["review_status"] == "OPEN"
