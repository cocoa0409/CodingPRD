"""Therapeutic goals, progress notes and the staleness sweep."""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_millisecond_instant_format,
    assert_same_instant,
    book_session,
    complete_session,
    confirm_session,
    draft_progress_note,
    finalize_period_report,
    finalize_progress_note,
    make_goal,
    make_instructor,
    make_instructor_headers,
    make_period_report,
    make_rider,
    read_goal,
    read_period_report,
    read_progress_note,
    read_rider,
    set_clock,
    setup_active_rider,
    setup_completed_session,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN


def test_goal_defaults_and_stale_after_from_created_at(api):
    """PRD 3.7: "A new goal is `ACTIVE`, with `current_rating` and
    `last_rated_at` null, `consecutive_target_hits` 0, `discontinue_reason` null,
    and `stale_after` set to 90 days after the goal's `created_at`."
    PRD 2.5: "Timestamps the **server itself mints** are rendered as
    `YYYY-MM-DDTHH:MM:SS.mmmZ` — an ISO 8601 UTC instant with exactly three
    fractional-second digits and a trailing `Z`."

    Design: Corner/entities/goal_create_defaults_status_active_and_stale_after_from_created_at
    """
    set_clock("2026-05-11T00:00:00Z")
    instructor = make_instructor()
    rider = make_rider(
        household_income_band="BAND_B", demographic_group="YOUTH", condition_codes=[]
    )

    goal = validate_success(
        api.create_goal(
            rider["id"],
            {
                "domain": "SOCIAL_EMOTIONAL",
                "objective": "Greet the horse unprompted",
                "baseline_rating": 1,
                "target_rating": 3,
            },
            make_instructor_headers(instructor["id"]),
        ),
        expected_status=201,
    )

    assert goal["status"] == "ACTIVE"
    assert goal["consecutive_target_hits"] == 0
    assert goal["current_rating"] is None
    assert goal["last_rated_at"] is None
    assert_same_instant(goal["stale_after"], "2026-08-09T00:00:00.000Z")
    assert_millisecond_instant_format(goal["created_at"], "Goal.created_at")
    assert_same_instant(goal["created_at"], "2026-05-11T00:00:00.000Z")

    _, meta = validate_paginated(api.list_goals(ADMIN, params={"rider_id": rider["id"]}))
    assert meta["total_count"] == 1


def test_goal_target_must_exceed_baseline(api):
    """PRD 3.7: "Both ratings run from 1 to 5 inclusive and `target_rating` must
    be strictly greater than `baseline_rating`."
    PRD 2.7 rung 7: "`baseline_rating` and `target_rating` are each at least 1
    and at most 5, and `target_rating` is strictly greater than
    `baseline_rating`"

    Design: Corner/entities/goal_create_with_target_not_above_baseline_returns_400
    """
    set_clock("2026-05-01T00:00:00Z")
    instructor = make_instructor()
    rider = make_rider(
        household_income_band="BAND_B", demographic_group="YOUTH", condition_codes=[]
    )

    response = api.create_goal(
        rider["id"],
        {
            "domain": "PHYSICAL",
            "objective": "Hold reins",
            "baseline_rating": 3,
            "target_rating": 3,
        },
        make_instructor_headers(instructor["id"]),
    )
    validate_error(response, ApiErrorId.ERR_VALIDATION.value)

    _, meta = validate_paginated(api.list_goals(ADMIN, params={"rider_id": rider["id"]}))
    assert meta["total_count"] == 0


def _goal_rated_twice_at_target():
    """A LEVEL_4 rider whose PHYSICAL goal has been rated 4 on two completed rides."""
    scenario = setup_active_rider()
    goal = make_goal(
        scenario["rider_id"],
        scenario["instructor_id"],
        domain="PHYSICAL",
        objective="Maintain independent posture for 10 minutes",
        baseline_rating=2,
        target_rating=4,
    )

    notes = []
    for start, narrative in (
        ("2026-05-11T10:00:00Z", "Steady posture"),
        ("2026-05-12T10:00:00Z", "Steady posture again"),
    ):
        session = book_session(
            scenario["rider_id"],
            scenario["horse_id"],
            scenario["instructor_id"],
            scheduled_start=start,
            duration_minutes=60,
        )
        confirm_session(session["id"], scenario["instructor_id"])
        complete_session(session["id"], scenario["instructor_id"], 60)
        notes.append(
            draft_progress_note(
                session["id"],
                scenario["instructor_id"],
                narrative=narrative,
                goal_ratings=[{"goal_id": goal["id"], "rating": 4}],
            )
        )

    scenario.update({"goal": goal, "notes": notes})
    return scenario


def test_two_target_hits_meet_the_goal(api):
    """PRD 3.7: "A rating at or above the goal's `target_rating` increases
    `consecutive_target_hits` by 1; a rating below it resets
    `consecutive_target_hits` to 0. A goal that was `STALE` returns to `ACTIVE`
    on being rated at all, regardless of the value. A goal whose
    `consecutive_target_hits` reaches 2 moves to `MET`."
    PRD 3.7: "Both actions bump the goal's `version` and both re-derive the
    rider's `goals_met_count`, which is simply the number of that rider's goals
    whose `status` is `MET`."

    Design: Difficulty/non_linear_state_machine/goal_met_then_reopened_returns_to_active
    """
    scenario = _goal_rated_twice_at_target()
    goal_id = scenario["goal"]["id"]

    finalize_progress_note(scenario["notes"][0]["id"], scenario["instructor_id"])
    after_first = read_goal(goal_id)
    assert after_first["consecutive_target_hits"] == 1
    assert after_first["status"] == "ACTIVE"

    finalize_progress_note(scenario["notes"][1]["id"], scenario["instructor_id"])
    after_second = read_goal(goal_id)
    assert after_second["status"] == "MET"
    assert after_second["consecutive_target_hits"] == 2
    assert read_rider(scenario["rider_id"])["goals_met_count"] == 1


def test_reopening_a_met_goal_clears_the_hit_counter(api):
    """PRD 3.7: "Reopening is available from `MET` only — reopening a goal in any
    other state is `ERR_INVALID_STATE` — and returns it to `ACTIVE` while
    resetting `consecutive_target_hits` to 0."
    PRD 3.7: "Both actions bump the goal's `version` and both re-derive the
    rider's `goals_met_count`, which is simply the number of that rider's goals
    whose `status` is `MET`."

    Design: Difficulty/non_linear_state_machine/goal_met_then_reopened_returns_to_active
    """
    scenario = _goal_rated_twice_at_target()
    goal_id = scenario["goal"]["id"]
    finalize_progress_note(scenario["notes"][0]["id"], scenario["instructor_id"])
    finalize_progress_note(scenario["notes"][1]["id"], scenario["instructor_id"])
    assert read_goal(goal_id)["status"] == "MET"

    reopened = validate_success(
        api.reopen_goal(
            goal_id,
            {"reason": "Regression observed off-horse"},
            make_instructor_headers(scenario["instructor_id"]),
        )
    )
    assert reopened["status"] == "ACTIVE"
    assert reopened["consecutive_target_hits"] == 0
    assert reopened["current_rating"] == 4
    assert read_rider(scenario["rider_id"])["goals_met_count"] == 0


def test_staleness_sweep_moves_only_the_due_active_goal(api):
    """PRD 3.7: "A `ProgramAdmin` runs a periodic sweep that moves every goal
    whose `status` is `ACTIVE` and whose `stale_after` the logical clock has
    reached — the boundary is inclusive, so a goal exactly at `stale_after` is
    swept — into `STALE`, incrementing each swept goal's `version`. The sweep
    answers with a `swept_count`, the array of `stale_goal_ids` in `created_at`
    ascending order, and the `evaluated_at` instant it ran at."
    PRD 3.7: "The sweep is deliberately **one-directional**: it only ever moves
    goals from `ACTIVE` to `STALE`, it never moves one back, and it never touches
    goals in `MET`, `STALE` or `DISCONTINUED`."

    Design: Corner/state_machines/goal_staleness_sweep_only_moves_due_active_goals
    """
    set_clock("2026-05-11T00:00:00Z")
    instructor = make_instructor()
    rider = make_rider(household_income_band="BAND_B", condition_codes=[])
    first = make_goal(
        rider["id"],
        instructor["id"],
        domain="PHYSICAL",
        objective="Independent posting trot",
        baseline_rating=1,
        target_rating=3,
    )

    set_clock("2026-08-01T00:00:00Z")
    second = make_goal(
        rider["id"],
        instructor["id"],
        domain="COGNITIVE",
        objective="Sequence three grooming steps",
        baseline_rating=1,
        target_rating=3,
    )

    set_clock("2026-08-09T00:00:00Z")
    swept = validate_success(api.run_goal_staleness_sweep(ADMIN))
    assert swept["swept_count"] == 1
    assert swept["stale_goal_ids"] == [first["id"]]
    assert_same_instant(swept["evaluated_at"], "2026-08-09T00:00:00.000Z")

    assert read_goal(first["id"])["status"] == "STALE"
    untouched = read_goal(second["id"])
    assert untouched["status"] == "ACTIVE"
    assert_same_instant(untouched["stale_after"], "2026-10-30T00:00:00.000Z")

    again = validate_success(api.run_goal_staleness_sweep(ADMIN))
    assert again["swept_count"] == 0


def test_a_rating_returns_a_stale_goal_to_active(api):
    """PRD 3.7: "A goal that was `STALE` returns to `ACTIVE` on being rated at
    all, regardless of the value."
    PRD 3.7: "Its `stale_after` is 90 days after `last_rated_at` when it has ever
    been rated, and 90 days after `created_at` when it has not."
    PRD 3.7: "It stamps `finalized_at` with the logical clock and copies the
    parent session's `service_hours` into `recorded_service_hours`, freezing the
    hours the note is evidence for."

    Design: Corner/state_machines/stale_goal_returns_to_active_when_a_finalized_note_rates_it
    """
    scenario = setup_active_rider(clock="2026-05-11T00:00:00Z")
    goal = make_goal(
        scenario["rider_id"],
        scenario["instructor_id"],
        domain="PHYSICAL",
        objective="Independent posting trot",
        baseline_rating=1,
        target_rating=3,
    )

    set_clock("2026-08-09T00:00:00Z")
    validate_success(api.run_goal_staleness_sweep(ADMIN))
    assert read_goal(goal["id"])["status"] == "STALE"

    session = book_session(
        scenario["rider_id"],
        scenario["horse_id"],
        scenario["instructor_id"],
        scheduled_start="2026-08-10T10:00:00Z",
        duration_minutes=60,
    )
    confirm_session(session["id"], scenario["instructor_id"])
    set_clock("2026-08-10T11:30:00Z")
    complete_session(session["id"], scenario["instructor_id"], 60)

    note = validate_success(
        api.create_progress_note(
            session["id"],
            {
                "narrative": "Some regression noted",
                "goal_ratings": [{"goal_id": goal["id"], "rating": 2}],
            },
            scenario["instructor_headers"],
        ),
        expected_status=201,
    )
    finalized = validate_success(
        api.finalize_progress_note(note["id"], scenario["instructor_headers"])
    )
    assert finalized["status"] == "FINALIZED"

    rated = read_goal(goal["id"])
    assert rated["status"] == "ACTIVE"
    assert rated["current_rating"] == 2
    assert rated["consecutive_target_hits"] == 0
    assert_same_instant(rated["last_rated_at"], "2026-08-10T11:30:00.000Z")
    assert_same_instant(rated["stale_after"], "2026-11-08T11:30:00.000Z")

    assert read_progress_note(note["id"])["recorded_service_hours"] == pytest.approx(
        1.0, abs=0.001
    )


def test_note_finalize_routes_to_amended_inside_a_finalized_period(api):
    """PRD 3.7: "When no period report covering the session date is `FINALIZED`,
    the note moves `DRAFT → FINALIZED`. When one is, the note moves `DRAFT →
    AMENDED` instead: the goal side effects fire identically, `finalized_at` is
    stamped identically, the covering report's `amendment_count` increases by 1,
    its `amendment_net_cents` is unchanged because a note carries no money, and
    the report's frozen aggregates are not touched."

    Design: Corner/state_machines/progress_note_finalize_routes_to_amended_inside_a_finalized_period
    """
    scenario = setup_completed_session(mounted_minutes=60)
    goal = make_goal(
        scenario["rider_id"],
        scenario["instructor_id"],
        domain="BEHAVIORAL",
        objective="Follow two-step cues",
        baseline_rating=1,
        target_rating=3,
    )
    note = validate_success(
        api.create_progress_note(
            scenario["session_id"],
            {
                "narrative": "Good session",
                "goal_ratings": [{"goal_id": goal["id"], "rating": 3}],
            },
            scenario["instructor_headers"],
        ),
        expected_status=201,
    )

    report = make_period_report(period_start="2026-05-01", period_end="2026-05-31")
    frozen = finalize_period_report(report["id"])
    assert frozen["total_service_hours"] == pytest.approx(1.0, abs=0.001)

    amended = validate_success(
        api.finalize_progress_note(note["id"], scenario["instructor_headers"])
    )
    assert amended["status"] == "AMENDED"

    report_after = read_period_report(report["id"])
    assert report_after["amendment_count"] == 1
    assert report_after["amendment_net_cents"] == 0
    assert report_after["total_service_hours"] == pytest.approx(1.0, abs=0.001)
    assert report_after["status"] == "FINALIZED"

    rated = read_goal(goal["id"])
    assert rated["current_rating"] == 3
    assert rated["consecutive_target_hits"] == 1
    assert rated["status"] == "ACTIVE"
