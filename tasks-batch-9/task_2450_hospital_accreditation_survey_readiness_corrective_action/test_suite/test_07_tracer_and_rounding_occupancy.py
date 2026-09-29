"""Temporal occupancy on two different resources: the exclusive half-open tracer
window with its sixty-minute trailing turnaround, and the aggregate capacity of
two closed-interval rounding sessions per unit and round type."""

from test_helpers import (
    ApiErrorId,
    assign_owner,
    close_rounding_session,
    create_chapter,
    create_standard,
    create_unit,
    open_rounding_session,
    read_unit,
    schedule_tracer,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Private setup chains — each test rebuilds its own world from scratch.
# ---------------------------------------------------------------------------

def _setup_unit_with_one_scheduled_tracer():
    """Chapter EC with one mapped standard (so the mapped-standard guard never
    fires) and unit ICU-8 in posture OPEN occupied by one SCHEDULED tracer over
    2026-08-05T08:00:00Z to 2026-08-05T12:00:00Z."""
    chapter = create_chapter("EC", "Environment of Care", 100, 1)
    standard = create_standard(chapter["id"], "EC.02.06.01", "Safe environment", "DIRECT_IMPACT")
    assign_owner(standard["id"], "owner-1", "PRIMARY")
    unit = create_unit("ICU-8", "ICU", 18)
    tracer = schedule_tracer(
        unit["id"],
        chapter["id"],
        "2026-08-05T08:00:00Z",
        "2026-08-05T12:00:00Z",
        tracer_type="SYSTEM",
        expected_unit_version=unit["version"],
    )
    unit_after = read_unit(unit["id"])
    return {
        "chapter": chapter,
        "standard": standard,
        "unit": unit_after,
        "tracer": tracer,
    }


def _setup_unit_with_two_open_environment_of_care_sessions():
    """Unit OR-5 carrying two intersecting OPEN ENVIRONMENT_OF_CARE sessions,
    08:00Z-12:00Z and 10:00Z-14:00Z on 2026-08-10, at clock 2026-08-10."""
    unit = create_unit("OR-5", "OR", 4)
    set_clock("2026-08-10T00:00:00Z")
    first = open_rounding_session(
        unit["id"], "ENVIRONMENT_OF_CARE", "2026-08-10T08:00:00Z", "2026-08-10T12:00:00Z"
    )
    second = open_rounding_session(
        unit["id"], "ENVIRONMENT_OF_CARE", "2026-08-10T10:00:00Z", "2026-08-10T14:00:00Z"
    )
    return {"unit": unit, "first": first, "second": second}


# ---------------------------------------------------------------------------
# resource_temporal_overlap / tracer_half_open_interval_with_sixty_minute_turnaround_buffer
# ---------------------------------------------------------------------------

def test_schedule_tracer_inside_sixty_minute_turnaround_buffer_is_rejected(
    api, tracer_surveyor_headers
):
    """PRD §3.4: "Occupation of a unit by a tracer is exclusive — capacity one — and it is measured on the **half-open** interval running from `window_start` up to but not including `window_end`, with a mandatory sixty-minute trailing turnaround after each existing tracer."
    PRD §3.4: "Concretely, a proposed tracer conflicts with an existing one when the proposed `window_start` falls strictly before the existing `window_end` extended by sixty minutes, **and** the proposed `window_end` falls strictly after the existing `window_start`."
    PRD §3.4: "Only tracers of the same unit whose `state` is `SCHEDULED` or `IN_PROGRESS` occupy anything; a tracer that has reached `COMPLETED` or `ABORTED` releases the unit immediately."
    PRD §3.4: "It also increments the unit's `scheduled_tracer_count` by one and advances the unit's `version` — which is precisely why a client scheduling two tracers back to back must re-read the unit between them."

    Design: Difficulty/resource_temporal_overlap/tracer_half_open_interval_with_sixty_minute_turnaround_buffer
    """
    built = _setup_unit_with_one_scheduled_tracer()
    assert built["tracer"]["state"] == "SCHEDULED"
    assert built["unit"]["scheduled_tracer_count"] == 1

    # 12:30Z falls strictly before 12:00Z extended by the sixty-minute buffer (13:00Z).
    response = api.create_mock_tracer(
        {
            "unit_id": built["unit"]["id"],
            "chapter_id": built["chapter"]["id"],
            "tracer_type": "PATIENT",
            "window_start": "2026-08-05T12:30:00Z",
            "window_end": "2026-08-05T14:00:00Z",
            "expected_unit_version": built["unit"]["version"],
        },
        tracer_surveyor_headers,
    )
    validate_error(response, ApiErrorId.ERR_TRACER_WINDOW_CONFLICT)

    unit = read_unit(built["unit"]["id"])
    assert unit["scheduled_tracer_count"] == 1


def test_schedule_tracer_exactly_sixty_minutes_after_existing_window_end_is_accepted(
    api, tracer_surveyor_headers
):
    """PRD §3.4: "Concretely, a proposed tracer conflicts with an existing one when the proposed `window_start` falls strictly before the existing `window_end` extended by sixty minutes, **and** the proposed `window_end` falls strictly after the existing `window_start`."
    PRD §3.4: "A new tracer beginning exactly sixty minutes after an existing tracer's `window_end` is therefore accepted."
    PRD §3.4: "A successfully scheduled tracer begins at `state` `SCHEDULED` with `started_at`, `completed_at` and `abort_reason` all null, `scored_weight`, `earned_weight` and `tracer_score` at zero and `contributes_to_readiness` false."
    PRD §3.4: "It also increments the unit's `scheduled_tracer_count` by one and advances the unit's `version` — which is precisely why a client scheduling two tracers back to back must re-read the unit between them."

    Design: Difficulty/resource_temporal_overlap/tracer_half_open_interval_with_sixty_minute_turnaround_buffer
    """
    built = _setup_unit_with_one_scheduled_tracer()
    assert built["unit"]["scheduled_tracer_count"] == 1

    # 13:00Z is exactly 12:00Z plus the sixty-minute turnaround, so it is buffer-clear.
    second = validate_success(
        api.create_mock_tracer(
            {
                "unit_id": built["unit"]["id"],
                "chapter_id": built["chapter"]["id"],
                "tracer_type": "PATIENT",
                "window_start": "2026-08-05T13:00:00Z",
                "window_end": "2026-08-05T14:00:00Z",
                "expected_unit_version": built["unit"]["version"],
            },
            tracer_surveyor_headers,
        ),
        201,
    )

    assert second["state"] == "SCHEDULED"
    assert second["started_at"] is None
    assert second["completed_at"] is None
    assert second["contributes_to_readiness"] is False

    unit = read_unit(built["unit"]["id"])
    assert unit["scheduled_tracer_count"] == 2


# ---------------------------------------------------------------------------
# resource_temporal_overlap / rounding_session_aggregate_capacity_two_closed_intervals
# ---------------------------------------------------------------------------

def test_third_intersecting_rounding_session_of_same_round_type_is_rejected(
    api, safety_officer_headers
):
    """PRD §3.5: "Capacity is aggregate two per unit per `round_type`, measured on the closed interval with touching endpoints counting as an intersection and no turnaround buffer at all."
    PRD §3.5: "The server counts the sessions on the same unit with the same `round_type` whose `state` is `OPEN` and whose interval intersects the proposed one, an intersection holding when the existing `window_start` is at or before the proposed `window_end` **and** the existing `window_end` is at or after the proposed `window_start`."
    PRD §3.5: "If that count is already two or more, the request is rejected with `ERR_ROUNDING_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/rounding_session_aggregate_capacity_two_closed_intervals
    """
    built = _setup_unit_with_two_open_environment_of_care_sessions()

    # Two intersecting sessions are still below the aggregate limit of two.
    assert built["first"]["state"] == "OPEN"
    assert built["second"]["state"] == "OPEN"

    # 12:00Z merely touches the first session's window_end, which still counts.
    response = api.create_rounding_session(
        {
            "unit_id": built["unit"]["id"],
            "round_type": "ENVIRONMENT_OF_CARE",
            "window_start": "2026-08-10T12:00:00Z",
            "window_end": "2026-08-10T13:00:00Z",
        },
        safety_officer_headers,
    )
    validate_error(response, ApiErrorId.ERR_ROUNDING_CAPACITY_EXCEEDED)


def test_rounding_capacity_is_scoped_per_round_type_and_released_by_closing(
    api, safety_officer_headers, director_headers
):
    """PRD §3.5: "Capacity is aggregate two per unit per `round_type`, measured on the closed interval with touching endpoints counting as an intersection and no turnaround buffer at all."
    PRD §3.5: "A session in `CLOSED` releases its capacity, and a `LIFE_SAFETY` session never competes with an `ENVIRONMENT_OF_CARE` session."
    PRD §3.5: "The `SafetyOfficer` closes it, the server requires that no ticket of that session sits in `ESCALATED` — otherwise the request is rejected with `ERR_ESCALATED_TICKET_BLOCKS_CLOSE` — and on success the session moves `OPEN → CLOSED` with `closed_at` stamped from the logical clock and its `version` advanced."
    PRD §2.3: "The `meta` object of every collection response carries `limit`, `offset`, `total_count` and `has_more`, where `total_count` is the size of the filtered result set before pagination is applied and `has_more` indicates whether rows remain beyond the current page."

    Design: Difficulty/resource_temporal_overlap/rounding_session_aggregate_capacity_two_closed_intervals
    """
    built = _setup_unit_with_two_open_environment_of_care_sessions()

    # The same rejected window is legal under a different round_type.
    life_safety = validate_success(
        api.create_rounding_session(
            {
                "unit_id": built["unit"]["id"],
                "round_type": "LIFE_SAFETY",
                "window_start": "2026-08-10T12:00:00Z",
                "window_end": "2026-08-10T13:00:00Z",
            },
            safety_officer_headers,
        ),
        201,
    )
    assert life_safety["state"] == "OPEN"
    assert life_safety["round_type"] == "LIFE_SAFETY"

    closed = close_rounding_session(built["first"]["id"])
    assert closed["state"] == "CLOSED"

    # With the first session CLOSED only one OPEN session still intersects.
    fourth = validate_success(
        api.create_rounding_session(
            {
                "unit_id": built["unit"]["id"],
                "round_type": "ENVIRONMENT_OF_CARE",
                "window_start": "2026-08-10T12:00:00Z",
                "window_end": "2026-08-10T13:00:00Z",
            },
            safety_officer_headers,
        ),
        201,
    )
    assert fourth["state"] == "OPEN"

    sessions, meta = validate_paginated(
        api.list_rounding_sessions(director_headers, {"unit_id": built["unit"]["id"]})
    )
    assert meta["total_count"] == 4
    assert len(sessions) == 4
