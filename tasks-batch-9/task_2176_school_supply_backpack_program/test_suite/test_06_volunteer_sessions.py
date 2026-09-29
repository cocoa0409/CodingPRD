"""Sorting and assembly sessions: throughput, child safety and floor occupation."""

from test_helpers import (
    ApiErrorId,
    assert_volunteer_event,
    create_active_school,
    create_active_site,
    create_collecting_cycle,
    create_event,
    create_scheduled_session,
    create_volunteer_event,
    move_volunteer_event,
    setup_site_with_scheduled_session,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

PD = TEST_USERS["program_director_headers"]


def _assembly_demand_scenario():
    """A COLLECTING cycle whose only open demand is one DRAFT 400-seat distribution
    event, plus an ACTIVE library site with 40 bins."""
    school = create_active_school(enrollment_count=900, max_concurrent_seats=500)
    cycle = create_collecting_cycle()
    create_event(school["id"], cycle["id"], grade_band="K_2", seat_capacity=400)
    site = create_active_site(
        cycle["id"], name="Civic Center", site_type="LIBRARY", bin_capacity=40
    )
    return {"school": school, "cycle": cycle, "site": site}


def test_assembly_capacity_takes_the_fatigue_discounted_volunteer_ceiling(api):
    """PRD §3.4: "An assembly session builds finished kits at a base rate of 6 kits per
    volunteer-hour; a sorting session triages stock rather than building kits, so its
    base rate is 0 and a `SORTING` session therefore always pins a
    `planned_kit_capacity` of 0."
    PRD §3.4: "A fatigue factor then discounts long shifts: a session lasting four
    hours or less carries a factor of exactly 1.0, and beyond that the factor is 1.0
    minus five hundredths for each whole hour, rounded up, by which the duration
    exceeds four hours, with a hard floor of 0.70 — that is, the factor is the larger
    of 0.70 and that computed value."
    PRD §3.4: "The volunteer ceiling is `volunteer_count` multiplied by the base rate,
    multiplied by the duration in hours, multiplied by the fatigue factor, and then
    floored to a whole number of kits; the floor is applied here, before any
    comparison, never afterwards."

    Design: Difficulty/combinatorial_formula/volunteer_capacity_nested_minima_with_fatigue_step_mode_a
    """
    scene = _assembly_demand_scenario()

    session = validate_success(
        create_volunteer_event(
            scene["site"]["id"],
            event_type="ASSEMBLY",
            window_start="2026-08-05T09:00:00Z",
            window_end="2026-08-05T15:30:00Z",
            volunteer_count=8,
            minor_volunteer_count=0,
            adult_supervisor_count=2,
        ),
        expected_status=201,
    )
    assert_volunteer_event(session)
    assert session["planned_kit_capacity"] == 265, (
        "floor(8 * 6 * 6.5 * 0.85) = 265 kits once the fatigue factor is applied"
    )
    assert session["status"] == "SCHEDULED"


def test_assembly_capacity_is_the_smallest_of_the_three_ceilings(api):
    """PRD §3.4: "The **station ceiling** is the site's `bin_capacity` multiplied by 12,
    on the accounting that each bin supports a dozen kit stations."
    PRD §3.4: "The **demand ceiling** is the total kit demand still open in the same
    drive cycle: the sum, over every distribution event of that cycle whose `status` is
    `DRAFT` or `PUBLISHED`, of that event's `seat_capacity` minus its
    `served_student_count`; events in `LOCKED`, `CLOSED` or `CANCELLED` are excluded
    entirely."
    PRD §3.4: "`planned_kit_capacity` is the smallest of the volunteer ceiling, the
    station ceiling and the demand ceiling."

    Design: Difficulty/combinatorial_formula/volunteer_capacity_nested_minima_with_fatigue_step_mode_a
    """
    scene = _assembly_demand_scenario()

    session = validate_success(
        create_volunteer_event(
            scene["site"]["id"],
            event_type="ASSEMBLY",
            window_start="2026-08-05T09:00:00Z",
            window_end="2026-08-05T15:30:00Z",
            volunteer_count=8,
            minor_volunteer_count=0,
            adult_supervisor_count=2,
        ),
        expected_status=201,
    )
    station_ceiling = 40 * 12
    demand_ceiling = 400
    assert session["planned_kit_capacity"] < station_ceiling, (
        "the 480-kit station ceiling must not be the binding minimum here"
    )
    assert session["planned_kit_capacity"] < demand_ceiling, (
        "the 400-kit demand ceiling must not be the binding minimum here"
    )
    assert session["planned_kit_capacity"] == 265
    assert session["planned_kit_capacity"] != 312, (
        "312 is the fatigue-free volunteer ceiling and is the wrong answer"
    )


def test_sorting_session_pins_a_zero_kit_capacity(api):
    """PRD §3.4: "An assembly session builds finished kits at a base rate of 6 kits per
    volunteer-hour; a sorting session triages stock rather than building kits, so its
    base rate is 0 and a `SORTING` session therefore always pins a
    `planned_kit_capacity` of 0."

    Design: Corner/calculations/sorting_session_rate_branch_yields_zero_kit_capacity
    """
    scene = _assembly_demand_scenario()

    session = validate_success(
        create_volunteer_event(
            scene["site"]["id"],
            event_type="SORTING",
            window_start="2026-08-05T09:00:00Z",
            window_end="2026-08-05T15:30:00Z",
            volunteer_count=8,
            minor_volunteer_count=0,
            adult_supervisor_count=1,
        ),
        expected_status=201,
    )
    assert session["event_type"] == "SORTING"
    assert session["planned_kit_capacity"] == 0


def test_completion_above_the_pinned_capacity_is_rejected(api):
    """PRD §3.4: "Completing it moves `IN_PROGRESS` to `COMPLETED` and takes an
    `assembled_kit_count` from the request recording the kits actually built; the
    session must be `IN_PROGRESS`, and the reported figure must be at least 0 and no
    greater than the pinned `planned_kit_capacity` — an overstated count is refused
    with `ERR_ASSEMBLY_OVER_CAPACITY`."
    PRD §3.4: "When the session survives those gates, the server pins its
    `planned_kit_capacity` once, at creation, and never recomputes it afterwards."

    Design: Corner/state_machines/volunteer_completion_above_planned_capacity_is_rejected
    """
    cycle = create_collecting_cycle()
    site = create_active_site(cycle["id"], bin_capacity=10)
    session = create_scheduled_session(
        site["id"],
        event_type="ASSEMBLY",
        window_start="2026-08-05T09:00:00Z",
        window_end="2026-08-05T12:00:00Z",
        volunteer_count=6,
        minor_volunteer_count=0,
        adult_supervisor_count=1,
    )
    assert session["planned_kit_capacity"] == 0, (
        "with no open distribution demand in the cycle the demand ceiling is 0"
    )
    validate_success(move_volunteer_event(site["id"], session["id"], "IN_PROGRESS"))

    response = move_volunteer_event(
        site["id"], session["id"], "COMPLETED", assembled_kit_count=5
    )
    validate_error(response, ApiErrorId.ERR_ASSEMBLY_OVER_CAPACITY.value, expected_status=422)

    rows, _ = validate_paginated(api.list_site_volunteer_events(site["id"], PD))
    assert rows[0]["status"] == "IN_PROGRESS"
    assert rows[0]["assembled_kit_count"] == 0


def test_session_starting_inside_the_turnover_buffer_collides(api):
    """PRD §3.4: "Concretely, a proposed session collides with an existing one when the
    proposed `window_start` is earlier than the existing `window_end` plus forty-five
    minutes **and** the existing `window_start` is earlier than the proposed
    `window_end` plus forty-five minutes."
    PRD §3.4: "A collision is reported as `ERR_SITE_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/volunteer_sessions_collide_under_buffered_half_open_intervals
    """
    scene = setup_site_with_scheduled_session()

    response = create_volunteer_event(
        scene.site_id,
        event_type="SORTING",
        window_start="2026-08-05T16:00:00Z",
        window_end="2026-08-05T17:00:00Z",
        volunteer_count=4,
        minor_volunteer_count=0,
        adult_supervisor_count=1,
    )
    validate_error(response, ApiErrorId.ERR_SITE_WINDOW_CONFLICT.value, expected_status=409)

    rows, _ = validate_paginated(api.list_site_volunteer_events(scene.site_id, PD))
    assert len(rows) == 1, "the colliding session must not be persisted"


def test_session_starting_exactly_at_the_buffer_edge_is_accepted(api):
    """PRD §3.4: "Concretely, a proposed session collides with an existing one when the
    proposed `window_start` is earlier than the existing `window_end` plus forty-five
    minutes **and** the existing `window_start` is earlier than the proposed
    `window_end` plus forty-five minutes."
    PRD §3.4: "Volunteer session intervals at one site are treated as half-open,
    including their `window_start` and excluding their `window_end`, and are then
    padded by a turnover buffer of forty-five minutes on **both** sides."

    Design: Difficulty/resource_temporal_overlap/volunteer_sessions_collide_under_buffered_half_open_intervals
    """
    scene = setup_site_with_scheduled_session()

    session = validate_success(
        create_volunteer_event(
            scene.site_id,
            event_type="SORTING",
            window_start="2026-08-05T16:15:00Z",
            window_end="2026-08-05T17:15:00Z",
            volunteer_count=4,
            minor_volunteer_count=0,
            adult_supervisor_count=1,
        ),
        expected_status=201,
    )
    assert session["status"] == "SCHEDULED", (
        "16:15 is exactly the existing end plus the 45-minute buffer, so it does not collide"
    )

    rows, meta = validate_paginated(api.list_site_volunteer_events(scene.site_id, PD))
    assert meta["total_count"] == 2
    assert len(rows) == 2


def test_supervision_ratio_is_reported_ahead_of_the_floor_collision(api):
    """PRD §3.4: "The program requires one designated adult supervisor for every eight
    minors or part thereof: `adult_supervisor_count` must be at least the number of
    minors divided by eight and rounded **up** to a whole number."
    PRD §3.4: "A session that cannot meet the ratio is refused with
    `ERR_SUPERVISION_RATIO_UNMET`."
    PRD §2.7: "12. Volunteer supervision ratio on session creation —
    `ERR_SUPERVISION_RATIO_UNMET`, 422."

    Design: Difficulty/priority_pair_validation_conflict/supervision_safety_beats_site_window_conflict
    """
    scene = setup_site_with_scheduled_session()

    response = create_volunteer_event(
        scene.site_id,
        event_type="SORTING",
        window_start="2026-08-05T15:00:00Z",
        window_end="2026-08-05T16:00:00Z",
        volunteer_count=20,
        minor_volunteer_count=17,
        adult_supervisor_count=2,
    )
    validate_error(response, ApiErrorId.ERR_SUPERVISION_RATIO_UNMET.value, expected_status=422)


def test_the_colliding_understaffed_session_is_never_persisted(api):
    """PRD §2.7: "20. Site occupation conflict on volunteer-session creation —
    `ERR_SITE_WINDOW_CONFLICT`, 409."
    PRD §2.7: "Every rule in this system has a fixed priority, the rules are evaluated
    in strictly ascending priority order, and **the first rule that fails decides the
    response** — no later rule can override or mask an earlier one, and no earlier rule
    may be skipped because a later one looks more specific."

    Design: Difficulty/priority_pair_validation_conflict/supervision_safety_beats_site_window_conflict
    """
    scene = setup_site_with_scheduled_session()

    response = create_volunteer_event(
        scene.site_id,
        event_type="SORTING",
        window_start="2026-08-05T15:00:00Z",
        window_end="2026-08-05T16:00:00Z",
        volunteer_count=20,
        minor_volunteer_count=17,
        adult_supervisor_count=2,
    )
    error = response.json()["data"]
    assert error["error_id"] != ApiErrorId.ERR_SITE_WINDOW_CONFLICT.value, (
        "the safety rule sits at a lower priority than the occupation conflict"
    )
    assert error["error_id"] == ApiErrorId.ERR_SUPERVISION_RATIO_UNMET.value

    rows, meta = validate_paginated(api.list_site_volunteer_events(scene.site_id, PD))
    assert meta["total_count"] == 1
    assert len(rows) == 1
