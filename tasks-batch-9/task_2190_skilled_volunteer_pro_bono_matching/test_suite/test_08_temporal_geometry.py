"""Temporal geometry: the half-open availability interval, the closed 72-hour check-in
buffer and the closed rolling fortnight, each probed one second either side of its edge."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    milestone_payload,
    read_cycle,
    set_clock,
    setup_in_progress_engagement,
    setup_roster,
    validate_error,
    validate_paginated,
    validate_success,
)

LEASE_SCHEDULE = [
    {
        "title": "Lease schedule",
        "sequence_no": 1,
        "weight_pct": 100.00,
        "hours_estimate": 40.00,
        "acceptance_criteria": "Schedule signed off by counsel",
    }
]

WINDOW_LOWER_EDGE = "2026-08-05T00:00:00Z"
WINDOW_UPPER_EDGE = "2026-10-01T00:00:00Z"
CYCLE_LOWER_EDGE = "2026-08-01T00:00:00Z"
CYCLE_UPPER_EDGE = "2026-11-01T00:00:00Z"


def _boundary_roster():
    """One cycle spanning [2026-08-01, 2026-11-01) and one vetted volunteer holding a single
    HARD window [2026-08-05, 2026-10-01) of 300.00 hours."""
    return setup_roster(
        skill_code="LEGAL_CONTRACTS",
        cycle_starts_at=CYCLE_LOWER_EDGE,
        cycle_ends_at=CYCLE_UPPER_EDGE,
        window_starts_at=WINDOW_LOWER_EDGE,
        window_ends_at=WINDOW_UPPER_EDGE,
        window_hours=300.00,
    )


def _publish(world, starts_at, ends_at, *, hours=10.00, kind="SOFT"):
    return api_client.create_availability_window(
        world["volunteer"]["id"],
        {
            "starts_at": starts_at,
            "ends_at": ends_at,
            "window_kind": kind,
            "hours_offered": hours,
        },
        world["volunteer_headers"],
    )


def _published_windows(world):
    rows, _meta = validate_paginated(
        api_client.list_availability_windows(
            world["volunteer"]["id"], world["pm_headers"]
        )
    )
    return rows


# ---------------------------------------------------------------------------
# Availability windows: touching is legal, one second of intersection is not
# ---------------------------------------------------------------------------
def test_01_windows_may_touch_an_existing_window_on_either_side(api):
    """PRD §3.2: "Exact adjacency — a new window starting at the precise instant an existing
    one ends — is permitted, and no buffer and no aggregate cap on total offered hours
    participate in this check."

    Design: Difficulty/resource_temporal_overlap/availability_window_half_open_adjacency_versus_one_second_overlap
    """
    world = _boundary_roster()

    after = validate_success(
        _publish(world, WINDOW_UPPER_EDGE, "2026-10-15T00:00:00Z", hours=20.00), 201
    )
    assert after["starts_at"].startswith("2026-10-01T00:00:00"), (
        f"Expected the new window to start at 2026-10-01T00:00:00Z, got "
        f"{after['starts_at']}"
    )
    assert after["starts_at"][:19] == world["window"]["ends_at"][:19], (
        f"The new window must start at the exact instant the existing one ends, got "
        f"{after['starts_at']} against {world['window']['ends_at']}"
    )

    before = validate_success(
        _publish(world, "2026-08-02T00:00:00Z", WINDOW_LOWER_EDGE, hours=10.00), 201
    )
    assert before["ends_at"].startswith("2026-08-05T00:00:00"), (
        f"Expected the new window to end at 2026-08-05T00:00:00Z, got "
        f"{before['ends_at']}"
    )
    assert before["ends_at"][:19] == world["window"]["starts_at"][:19], (
        f"The new window must end at the exact instant the existing one begins, got "
        f"{before['ends_at']} against {world['window']['starts_at']}"
    )
    assert len(_published_windows(world)) == 3, (
        f"Expected three published windows, got {len(_published_windows(world))}"
    )


def test_02_a_single_second_of_intersection_is_refused_on_either_side(api):
    """PRD §3.2: "And no two windows of the same volunteer whose `status` is not `EXPIRED`
    may overlap: overlap is judged on half-open geometry, so a new window is refused with
    `ERR_AVAILABILITY_WINDOW_OVERLAP` when its `starts_at` falls before an existing window's
    `ends_at` while that existing window's `starts_at` falls before the new one's `ends_at`."

    Design: Difficulty/resource_temporal_overlap/availability_window_half_open_adjacency_versus_one_second_overlap
    """
    world = _boundary_roster()

    tail = _publish(world, "2026-09-30T23:59:59Z", WINDOW_UPPER_EDGE, hours=1.00)
    validate_error(tail, ApiErrorId.ERR_AVAILABILITY_WINDOW_OVERLAP)
    assert tail.json()["data"]["error_id"] != ApiErrorId.ERR_WINDOW_OUTSIDE_CYCLE.value, (
        "The probe sits well inside the cycle, so containment is not the complaint"
    )

    head = _publish(world, WINDOW_LOWER_EDGE, "2026-08-05T00:00:01Z", hours=1.00)
    validate_error(head, ApiErrorId.ERR_AVAILABILITY_WINDOW_OVERLAP)

    assert len(_published_windows(world)) == 1, (
        f"Expected only the seeded window to survive, got "
        f"{len(_published_windows(world))}"
    )


# ---------------------------------------------------------------------------
# The check-in buffer: a closed 72-hour distance between siblings
# ---------------------------------------------------------------------------
ANCHOR_DUE_AT = "2026-08-20T00:00:00Z"


def _anchored_engagement():
    """A live engagement carrying exactly one SCHEDULED check-in due 2026-08-20."""
    world = setup_in_progress_engagement(
        skill_code="LEGAL_CONTRACTS",
        deliverables=LEASE_SCHEDULE,
        title="Lease portfolio diligence",
    )
    world["anchor"] = _schedule_checkin(world, ANCHOR_DUE_AT, expect=201)
    return world


def _schedule_checkin(world, due_at, *, expect=None):
    response = api_client.create_milestone(
        world["engagement"]["id"],
        milestone_payload(due_at=due_at),
        world["pm_headers"],
    )
    if expect is not None:
        return validate_success(response, expect)
    return response


def _scheduled_due_ats(world):
    rows, _meta = validate_paginated(
        api_client.list_milestones(world["engagement"]["id"], world["pm_headers"])
    )
    return sorted(
        row["due_at"] for row in rows if row["checkin_status"] == "SCHEDULED"
    )


def test_03_a_separation_one_second_short_of_the_buffer_is_refused_both_ways(api):
    """PRD §3.7: "It must sit at least three days away from the `due_at` of every sibling
    milestone whose `checkin_status` is `SCHEDULED` or `HELD` — the buffer is 72 hours and
    its geometry is closed, so a separation of exactly 72 hours is accepted while anything
    strictly closer is refused with `ERR_MILESTONE_SPACING_VIOLATION`."

    Design: Difficulty/resource_temporal_overlap/milestone_checkin_buffer_closed_72h_boundary
    """
    world = _anchored_engagement()

    late = _schedule_checkin(world, "2026-08-22T23:59:59Z")
    validate_error(late, ApiErrorId.ERR_MILESTONE_SPACING_VIOLATION)
    assert late.json()["data"]["error_id"] != ApiErrorId.ERR_VOLUNTEER_CHECKIN_SATURATED.value, (
        "One sibling is not saturation, so the distance rule must be the complaint"
    )

    early = _schedule_checkin(world, "2026-08-17T00:00:01Z")
    validate_error(early, ApiErrorId.ERR_MILESTONE_SPACING_VIOLATION)

    assert _scheduled_due_ats(world) == [world["anchor"]["due_at"]], (
        f"Expected only the anchor check-in to survive, got "
        f"{_scheduled_due_ats(world)}"
    )


def test_04_a_separation_of_exactly_seventy_two_hours_is_accepted(api):
    """PRD §2.5: "The milestone spacing buffer, by contrast, is **closed**: two check-ins
    exactly the buffer apart are acceptable, and only a strictly smaller separation is
    refused."

    Design: Difficulty/resource_temporal_overlap/milestone_checkin_buffer_closed_72h_boundary
    """
    world = _anchored_engagement()

    sibling = _schedule_checkin(world, "2026-08-23T00:00:00Z", expect=201)

    assert sibling["due_at"].startswith("2026-08-23T00:00:00"), (
        f"Expected due_at 2026-08-23T00:00:00Z, got {sibling['due_at']}"
    )
    assert sibling["checkin_status"] == "SCHEDULED", (
        f"Expected checkin_status SCHEDULED, got {sibling['checkin_status']}"
    )
    assert len(_scheduled_due_ats(world)) == 2, (
        f"Expected two scheduled check-ins, got {_scheduled_due_ats(world)}"
    )


def test_05_the_buffer_is_measured_the_same_way_around_an_isolated_anchor(api):
    """PRD §3.7: "It must sit at least three days away from the `due_at` of every sibling
    milestone whose `checkin_status` is `SCHEDULED` or `HELD` — the buffer is 72 hours and
    its geometry is closed, so a separation of exactly 72 hours is accepted while anything
    strictly closer is refused with `ERR_MILESTONE_SPACING_VIOLATION`."
    PRD §3.7: "Check-ins are scheduled by a `ProgramManager`, who supplies only a `due_at`;
    the milestone is created in `checkin_status` `SCHEDULED` with a `sequence_no` one greater
    than the highest among its siblings, and with null `held_at`,
    `reported_cumulative_hours`, `variance_hours` and `waiver_reason` and
    `escalation_raised` false."

    Design: Difficulty/resource_temporal_overlap/milestone_checkin_buffer_closed_72h_boundary
    """
    world = _anchored_engagement()
    isolated = _schedule_checkin(world, "2026-09-15T00:00:00Z", expect=201)
    assert isolated["due_at"].startswith("2026-09-15T00:00:00"), (
        f"Expected the isolated anchor at 2026-09-15T00:00:00Z, got {isolated['due_at']}"
    )

    too_close = _schedule_checkin(world, "2026-09-17T23:59:59Z")
    validate_error(too_close, ApiErrorId.ERR_MILESTONE_SPACING_VIOLATION)
    assert (
        too_close.json()["data"]["error_id"]
        != ApiErrorId.ERR_VOLUNTEER_CHECKIN_SATURATED.value
    ), "Only one sibling sits in the fortnight, so saturation cannot be the complaint"

    one_second_clear = _schedule_checkin(world, "2026-09-18T00:00:01Z", expect=201)
    assert one_second_clear["due_at"].startswith("2026-09-18T00:00:01"), (
        f"Expected due_at 2026-09-18T00:00:01Z, got {one_second_clear['due_at']}"
    )
    assert len(_scheduled_due_ats(world)) == 3, (
        f"Expected three scheduled check-ins, got {_scheduled_due_ats(world)}"
    )


# ---------------------------------------------------------------------------
# The rolling fortnight: a closed span anchored on the candidate row
# ---------------------------------------------------------------------------
def _saturated_engagement():
    """A live engagement carrying two SCHEDULED check-ins exactly 72 hours apart, so the
    distance rule is already satisfied and only the count rule remains under test."""
    world = _anchored_engagement()
    world["second"] = _schedule_checkin(world, "2026-08-23T00:00:00Z", expect=201)
    return world


def test_06_a_third_checkin_inside_the_fortnight_is_refused_by_the_count(api):
    """PRD §3.7: "And the volunteer must not be saturated across her whole portfolio:
    counting milestones with `checkin_status` `SCHEDULED` across *all* engagements of that
    volunteer whose `due_at` falls within the closed fortnight running from seven days before
    the new `due_at` to seven days after it, at most two may already exist before the new row
    is added, so the third such check-in in any rolling fourteen-day span is refused with
    `ERR_VOLUNTEER_CHECKIN_SATURATED`."

    Design: Difficulty/resource_temporal_overlap/rolling_fourteen_day_checkin_saturation_slides_by_candidate_due_at
    """
    world = _saturated_engagement()

    third = _schedule_checkin(world, "2026-08-26T00:00:00Z")

    validate_error(third, ApiErrorId.ERR_VOLUNTEER_CHECKIN_SATURATED)
    assert (
        third.json()["data"]["error_id"] != ApiErrorId.ERR_MILESTONE_SPACING_VIOLATION.value
    ), "The candidate sits exactly 72 hours from its nearest sibling, so the distance rule passes"

    set_clock("2026-08-19T00:00:00Z", world["pm_headers"])
    still_refused = _schedule_checkin(world, "2026-08-27T00:00:00Z")
    validate_error(still_refused, ApiErrorId.ERR_VOLUNTEER_CHECKIN_SATURATED)
    assert len(_scheduled_due_ats(world)) == 2, (
        f"Advancing the clock clears nothing, got {_scheduled_due_ats(world)}"
    )


def test_07_sliding_the_candidate_one_second_past_the_closed_edge_clears_it(api):
    """PRD §3.7: "And the volunteer must not be saturated across her whole portfolio:
    counting milestones with `checkin_status` `SCHEDULED` across *all* engagements of that
    volunteer whose `due_at` falls within the closed fortnight running from seven days before
    the new `due_at` to seven days after it, at most two may already exist before the new row
    is added, so the third such check-in in any rolling fourteen-day span is refused with
    `ERR_VOLUNTEER_CHECKIN_SATURATED`."

    Design: Difficulty/resource_temporal_overlap/rolling_fourteen_day_checkin_saturation_slides_by_candidate_due_at
    """
    world = _saturated_engagement()
    validate_error(
        _schedule_checkin(world, "2026-08-27T00:00:00Z"),
        ApiErrorId.ERR_VOLUNTEER_CHECKIN_SATURATED,
    )

    cleared = _schedule_checkin(world, "2026-08-27T00:00:01Z", expect=201)

    assert cleared["due_at"].startswith("2026-08-27T00:00:01"), (
        f"Expected due_at 2026-08-27T00:00:01Z, got {cleared['due_at']}"
    )
    assert cleared["checkin_status"] == "SCHEDULED", (
        f"Expected checkin_status SCHEDULED, got {cleared['checkin_status']}"
    )
    assert len(_scheduled_due_ats(world)) == 3, (
        f"Expected three scheduled check-ins, got {_scheduled_due_ats(world)}"
    )


# ---------------------------------------------------------------------------
# The same instant, judged by two different conventions
# ---------------------------------------------------------------------------
def _pinned_window_engagement():
    """A live engagement whose pinned window is [2026-08-01, 2026-10-01) and which carries no
    check-ins yet."""
    return setup_in_progress_engagement(
        skill_code="LEGAL_CONTRACTS",
        window_ends_at=WINDOW_UPPER_EDGE,
        deliverables=LEASE_SCHEDULE,
        title="Lease portfolio diligence",
    )


def test_08_the_windows_end_instant_is_outside_it_yet_a_legal_start_for_the_next(api):
    """PRD §2.12: "A new milestone's `due_at` lies inside the pinned availability window's
    half-open interval and strictly after the engagement's `created_at` — on
    `POST /engagements/{id}/milestones` — otherwise
    `ERR_MILESTONE_DUE_OUTSIDE_ENGAGEMENT` (422)."
    PRD §3.2: "Exact adjacency — a new window starting at the precise instant an existing one
    ends — is permitted, and no buffer and no aggregate cap on total offered hours
    participate in this check."

    Design: Difficulty/resource_temporal_overlap/half_open_window_versus_closed_buffer_same_instant_contrast
    """
    world = _pinned_window_engagement()

    on_the_edge = _schedule_checkin(world, WINDOW_UPPER_EDGE)
    validate_error(on_the_edge, ApiErrorId.ERR_MILESTONE_DUE_OUTSIDE_ENGAGEMENT)
    assert (
        on_the_edge.json()["data"]["error_id"]
        != ApiErrorId.ERR_MILESTONE_SPACING_VIOLATION.value
    ), "No sibling check-in exists, so the distance rule cannot be the complaint"

    one_second_inside = _schedule_checkin(world, "2026-09-30T23:59:59Z", expect=201)
    assert one_second_inside["due_at"].startswith("2026-09-30T23:59:59"), (
        f"Expected due_at 2026-09-30T23:59:59Z, got {one_second_inside['due_at']}"
    )

    adjacent = validate_success(
        _publish(world, WINDOW_UPPER_EDGE, "2026-10-20T00:00:00Z", hours=40.00), 201
    )
    assert adjacent["starts_at"].startswith("2026-10-01T00:00:00"), (
        f"The same instant is a legal window start, got {adjacent['starts_at']}"
    )
    assert adjacent["starts_at"][:19] == world["window"]["ends_at"][:19], (
        f"Expected the new window to begin where the pinned one ends, got "
        f"{adjacent['starts_at']} against {world['window']['ends_at']}"
    )
    assert len(_published_windows(world)) == 2, (
        f"Expected two published windows, got {len(_published_windows(world))}"
    )


def test_09_the_closed_buffer_admits_a_sibling_that_the_closed_fortnight_refuses(api):
    """PRD §3.7: "It must sit at least three days away from the `due_at` of every sibling
    milestone whose `checkin_status` is `SCHEDULED` or `HELD` — the buffer is 72 hours and
    its geometry is closed, so a separation of exactly 72 hours is accepted while anything
    strictly closer is refused with `ERR_MILESTONE_SPACING_VIOLATION`."
    PRD §3.7: "And the volunteer must not be saturated across her whole portfolio: counting
    milestones with `checkin_status` `SCHEDULED` across *all* engagements of that volunteer
    whose `due_at` falls within the closed fortnight running from seven days before the new
    `due_at` to seven days after it, at most two may already exist before the new row is
    added, so the third such check-in in any rolling fourteen-day span is refused with
    `ERR_VOLUNTEER_CHECKIN_SATURATED`."

    Design: Difficulty/resource_temporal_overlap/half_open_window_versus_closed_buffer_same_instant_contrast
    """
    world = _pinned_window_engagement()
    first = _schedule_checkin(world, "2026-09-30T23:59:59Z", expect=201)

    second = _schedule_checkin(world, "2026-09-27T23:59:59Z", expect=201)
    assert second["due_at"].startswith("2026-09-27T23:59:59"), (
        f"Exactly 72 hours from {first['due_at']} is admitted, got {second['due_at']}"
    )

    third = _schedule_checkin(world, "2026-09-24T23:59:59Z")

    validate_error(third, ApiErrorId.ERR_VOLUNTEER_CHECKIN_SATURATED)
    body = third.json()
    assert body["data"]["error_id"] != ApiErrorId.ERR_MILESTONE_SPACING_VIOLATION.value, (
        "The candidate sits exactly 72 hours from its nearest sibling"
    )
    assert body["data"]["error_id"] != ApiErrorId.ERR_MILESTONE_DUE_OUTSIDE_ENGAGEMENT.value, (
        "The candidate sits well inside the pinned window"
    )
    assert len(_scheduled_due_ats(world)) == 2, (
        f"Expected two scheduled check-ins, got {_scheduled_due_ats(world)}"
    )


# ---------------------------------------------------------------------------
# Containment of a window inside its cycle
# ---------------------------------------------------------------------------
def test_10_a_window_may_sit_flush_against_either_cycle_edge(api):
    """PRD §2.12: "A new availability window has `ends_at` strictly after `starts_at` and its
    whole half-open interval lies inside some program cycle's half-open interval — on
    `POST /volunteers/{id}/availability-windows` — otherwise `ERR_WINDOW_OUTSIDE_CYCLE`
    (422)."

    Design: Difficulty/resource_temporal_overlap/availability_window_cycle_containment_boundary_and_degenerate_interval
    """
    world = _boundary_roster()
    cycle = read_cycle(world)

    lower = validate_success(
        _publish(world, CYCLE_LOWER_EDGE, WINDOW_LOWER_EDGE, hours=12.00, kind="HARD"),
        201,
    )
    assert lower["starts_at"].startswith("2026-08-01T00:00:00"), (
        f"Expected starts_at 2026-08-01T00:00:00Z, got {lower['starts_at']}"
    )
    assert lower["starts_at"][:19] == cycle["starts_at"][:19], (
        f"The cycle's lower edge is included, got {lower['starts_at']} against "
        f"{cycle['starts_at']}"
    )

    upper = validate_success(
        _publish(world, WINDOW_UPPER_EDGE, CYCLE_UPPER_EDGE, hours=60.00), 201
    )
    assert upper["ends_at"].startswith("2026-11-01T00:00:00"), (
        f"Expected ends_at 2026-11-01T00:00:00Z, got {upper['ends_at']}"
    )
    assert upper["ends_at"][:19] == cycle["ends_at"][:19], (
        f"Half-open containment admits an ends_at equal to the cycle's, got "
        f"{upper['ends_at']} against {cycle['ends_at']}"
    )
    assert len(_published_windows(world)) == 3, (
        f"Expected three published windows, got {len(_published_windows(world))}"
    )


def test_11_one_second_outside_either_cycle_edge_answers_with_containment(api):
    """PRD §3.2: "The whole interval must sit inside some program cycle's interval, and a
    malformed interval or one that escapes every cycle is refused with
    `ERR_WINDOW_OUTSIDE_CYCLE`."
    PRD §2.12: "The ordering is global: a check with a lower number always wins over a check
    with a higher number on the same endpoint."

    Design: Difficulty/resource_temporal_overlap/availability_window_cycle_containment_boundary_and_degenerate_interval
    """
    world = _boundary_roster()

    below = _publish(world, "2026-07-31T23:59:59Z", "2026-09-01T00:00:00Z", hours=30.00)
    validate_error(below, ApiErrorId.ERR_WINDOW_OUTSIDE_CYCLE)
    assert (
        below.json()["data"]["error_id"] != ApiErrorId.ERR_AVAILABILITY_WINDOW_OVERLAP.value
    ), "Containment is checked before overlap, though this probe violates both"

    validate_success(
        _publish(world, WINDOW_UPPER_EDGE, CYCLE_UPPER_EDGE, hours=60.00), 201
    )
    above = _publish(world, "2026-10-20T00:00:00Z", "2026-11-01T00:00:01Z", hours=30.00)
    validate_error(above, ApiErrorId.ERR_WINDOW_OUTSIDE_CYCLE)
    assert (
        above.json()["data"]["error_id"] != ApiErrorId.ERR_AVAILABILITY_WINDOW_OVERLAP.value
    ), "Containment is checked before overlap, though this probe violates both"

    assert len(_published_windows(world)) == 2, (
        f"Expected only the two legal windows, got {len(_published_windows(world))}"
    )


def test_12_a_degenerate_zero_length_interval_is_refused(api):
    """PRD §3.2: "Each window carries `starts_at`, an `ends_at` strictly after it, a
    `window_kind` of `HARD` (the volunteer's guaranteed capacity) or `SOFT` (best-effort),
    and an `hours_offered` budget above zero and no greater than 400.00."

    Design: Difficulty/resource_temporal_overlap/availability_window_cycle_containment_boundary_and_degenerate_interval
    """
    world = _boundary_roster()

    degenerate = _publish(
        world, "2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z", hours=5.00
    )

    validate_error(degenerate, ApiErrorId.ERR_WINDOW_OUTSIDE_CYCLE)
    assert len(_published_windows(world)) == 1, (
        f"Expected only the seeded window, got {len(_published_windows(world))}"
    )
    assert _published_windows(world)[0]["hours_offered"] == pytest.approx(
        300.00, abs=0.01
    ), (
        f"Expected the seeded window untouched at 300.00 hours, got "
        f"{_published_windows(world)[0]['hours_offered']}"
    )
