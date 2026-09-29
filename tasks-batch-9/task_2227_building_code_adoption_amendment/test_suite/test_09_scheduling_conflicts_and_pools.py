"""Scheduling a hearing or a session against an occupied resource."""
from test_helpers import (
    ApiErrorId,
    fixtures,
    get_success_data,
    make_council_admin_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_01_a_thirty_minute_gap_falls_inside_the_sixty_minute_buffer(api):
    """"The requested interval, padded by 60 minutes on each side, must not
    overlap another `SCHEDULED` or `CONVENED` hearing of the same committee; an
    overlap is refused with `ERR_HEARING_TIME_CONFLICT`." A sitting from 14:00 to
    17:00 therefore reserves 13:00 to 18:00, so a hearing starting at 17:30 is
    refused.

    Design: Difficulty/resource_temporal_overlap/hearing_sixty_minute_buffer_rejects_thirty_minute_gap_accepts_exact_sixty
    """
    world = fixtures.setup_seated_energy_committee(api)
    fixtures.add_scheduled_hearing(api, world)

    response = fixtures.schedule_hearing(
        api,
        world,
        scheduled_start="2026-10-05T17:30:00Z",
        scheduled_end="2026-10-05T19:00:00Z",
    )
    validate_error(response, ApiErrorId.ERR_HEARING_TIME_CONFLICT, 409)


def test_02_a_hearing_starting_exactly_sixty_minutes_later_is_accepted(api):
    """The padding is exactly 60 minutes on each side, so a hearing starting at
    18:00 — the instant the earlier sitting's buffered footprint ends — clears the
    conflict test and "starts in `SCHEDULED` with an empty
    `agenda_proposal_ids`", leaving the committee with two live hearings.

    Design: Difficulty/resource_temporal_overlap/hearing_sixty_minute_buffer_rejects_thirty_minute_gap_accepts_exact_sixty
    """
    world = fixtures.setup_seated_energy_committee(api)
    fixtures.add_scheduled_hearing(api, world)

    response = fixtures.schedule_hearing(
        api,
        world,
        scheduled_start="2026-10-05T18:00:00Z",
        scheduled_end="2026-10-05T19:30:00Z",
    )
    hearing = validate_success(response, 201)
    assert hearing["status"] == "SCHEDULED"
    assert hearing["scheduled_start"] == "2026-10-05T18:00:00Z"

    _, meta = validate_paginated(
        api.list_committee_hearings(world["committee_id"], make_council_admin_headers())
    )
    assert meta["total_count"] == 2


def _morning_session_world(api):
    """Riverbend hosting a 40-seat morning session in a 60-seat room."""
    world = fixtures.setup_published_adoption_rule(api)
    fixtures.add_riverbend(api, world)
    fixtures.add_session(
        api,
        world,
        key="morning",
        seat_capacity=40,
        starts_at="2027-01-10T09:00:00Z",
        ends_at="2027-01-10T13:00:00Z",
    )
    return world


def test_03_overlapping_sessions_are_summed_against_the_host_room(api):
    """"Summed across every non-`CANCELLED` session of that host whose interval
    overlaps the requested one, `seat_capacity` must not exceed the host's
    `host_seat_capacity`, and an excess is refused with
    `ERR_HOST_CAPACITY_EXCEEDED`." A 25-seat session running 12:00 to 16:00
    overlaps the 40-seat morning session, and 40 plus 25 exceeds Riverbend's 60
    seats.

    Design: Difficulty/resource_temporal_overlap/training_session_host_capacity_is_aggregate_over_overlapping_sessions
    """
    world = _morning_session_world(api)

    response = fixtures.create_session(
        api,
        world,
        audience="DESIGN_PROFESSIONAL",
        seat_capacity=25,
        starts_at="2027-01-10T12:00:00Z",
        ends_at="2027-01-10T16:00:00Z",
    )
    validate_error(response, ApiErrorId.ERR_HOST_CAPACITY_EXCEEDED, 409)


def test_04_an_adjacent_session_consumes_none_of_the_shared_room(api):
    """"The overlap test uses the half-open convention with zero buffer —
    deliberately unlike the buffered hearing rule — so a session starting exactly
    when another ends does not overlap it and never consumes shared capacity." A
    full 60-seat session from 13:00 is therefore accepted and "starts in
    `SCHEDULED` with `seats_available` equal to `seat_capacity`".

    Design: Difficulty/resource_temporal_overlap/training_session_host_capacity_is_aggregate_over_overlapping_sessions
    """
    world = _morning_session_world(api)

    response = fixtures.create_session(
        api,
        world,
        audience="DESIGN_PROFESSIONAL",
        seat_capacity=60,
        starts_at="2027-01-10T13:00:00Z",
        ends_at="2027-01-10T17:00:00Z",
    )
    session = validate_success(response, 201)
    assert session["status"] == "SCHEDULED"
    assert session["seat_capacity"] == 60
    assert session["seats_available"] == 60

    assert world["sessions"]["morning"]["seat_capacity"] == 40

    _, meta = validate_paginated(
        api.list_jurisdiction_hosted_training_sessions(
            world["riverbend_id"], make_council_admin_headers()
        )
    )
    assert meta["total_count"] == 2


def test_05_auto_fill_over_an_empty_pool_is_refused(api):
    """The eligible pool holds only proposals "whose `review_status` is
    `COMMENT_CLOSED` and whose `analysis_status` is `COMPLETE`", and "if the pool
    comes up empty, the request is refused with `ERR_NO_ELIGIBLE_PROPOSALS`". A
    cycle carrying no proposals at all presents exactly that empty pool.

    Design: Difficulty/boundary_precision_check/agenda_auto_fill_on_empty_eligible_pool_is_rejected
    """
    world = fixtures.setup_seated_energy_committee(api)
    fixtures.add_scheduled_hearing(api, world)

    response = fixtures.fill_agenda(api, world)
    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_PROPOSALS, 409)


def test_06_the_refused_auto_fill_writes_no_agenda(api):
    """Only a successful fill sets `agenda_proposal_ids`, so the refusal leaves
    the hearing as it was created — `SCHEDULED` "with an empty
    `agenda_proposal_ids`".

    Design: Difficulty/boundary_precision_check/agenda_auto_fill_on_empty_eligible_pool_is_rejected
    """
    world = fixtures.setup_seated_energy_committee(api)
    fixtures.add_scheduled_hearing(api, world)

    fixtures.fill_agenda(api, world)

    hearing = get_success_data(
        api.get_hearing(world["hearing_id"], make_council_admin_headers())
    )
    assert hearing["status"] == "SCHEDULED"
    assert hearing["agenda_proposal_ids"] == []


def test_07_a_forming_committee_may_not_be_given_a_hearing(api):
    """"The committee must be `SEATED`, or scheduling is refused with
    `ERR_COMMITTEE_NOT_SEATED`." Three of six voting seats filled leaves
    `active_voting_member_count` at 3, short of the "at least two thirds of
    `voting_seat_count` rounded up to a whole seat" that seating demands, even
    though the request itself is well formed.

    Design: Difficulty/cross_entity_state_dependency/hearing_creation_blocked_while_committee_is_forming
    """
    world = fixtures.setup_forming_energy_committee(api)

    response = fixtures.schedule_hearing(api, world)
    validate_error(response, ApiErrorId.ERR_COMMITTEE_NOT_SEATED, 409)


def test_08_the_forming_committee_keeps_its_derived_figures_and_no_hearings(api):
    """"`sector_coverage_complete` is true when the committee's `ACTIVE` members
    between them cover all three of the `INDUSTRY`, `FIRE_SERVICE` and
    `LOCAL_JURISDICTION` sectors", which those three members do — so the seat
    count alone holds the committee in `FORMING`, and the refused request created
    no hearing.

    Design: Difficulty/cross_entity_state_dependency/hearing_creation_blocked_while_committee_is_forming
    """
    world = fixtures.setup_forming_energy_committee(api)

    fixtures.schedule_hearing(api, world)

    committee = get_success_data(
        api.get_discipline_committee(
            world["committee_id"], make_council_admin_headers()
        )
    )
    assert committee["status"] == "FORMING"
    assert committee["active_voting_member_count"] == 3
    assert committee["sector_coverage_complete"] is True

    _, meta = validate_paginated(
        api.list_committee_hearings(world["committee_id"], make_council_admin_headers())
    )
    assert meta["total_count"] == 0
