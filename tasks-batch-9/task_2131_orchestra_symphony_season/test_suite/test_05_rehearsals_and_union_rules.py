"""Scheduling services, booking players and the union rules that guard both."""

from test_helpers import (
    ORCHESTRA_MANAGER,
    ApiErrorId,
    add_engagement,
    build_world,
    create_musician,
    create_service,
    decline_engagement,
    make_musician_headers,
    publish_service,
    read_engagement,
    read_musician,
    read_service,
    validate_error,
    validate_paginated,
    validate_success,
)


# --------------------------------------------------------------------------
# Scheduling gates
# --------------------------------------------------------------------------
def test_scheduling_a_service_on_a_draft_concert_is_refused(api):
    """PRD 3.3: "Scheduling requires the parent concert's `programming_status` to be
    `PROGRAMMED` or `LOCKED`, refusing a `DRAFT` concert with
    `ERR_CONCERT_NOT_PROGRAMMED`."

    Design: Corner/errors/create_service_on_draft_concert_returns_concert_not_programmed
    """
    world = build_world(program_indexes=[])

    response = api.create_rehearsal(
        {
            "concert_id": world.concert["id"],
            "venue_id": world.venue["id"],
            "service_type": "REHEARSAL",
            "scheduled_start_utc": "2026-11-04T14:00:00Z",
            "scheduled_end_utc": "2026-11-04T15:00:00Z",
            "minimum_complement": 0,
            "break_minutes": 0,
        },
        ORCHESTRA_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_CONCERT_NOT_PROGRAMMED.value, 409)

    _, meta = validate_paginated(
        api.list_rehearsals(ORCHESTRA_MANAGER,
                            params={"concert_id": world.concert["id"]})
    )
    assert meta["total_count"] == 0


def test_clocking_a_draft_service_is_refused(api):
    """PRD 3.3: "The `OrchestraManager` supplies `actual_start_utc` and
    `actual_end_utc`, and the latter must fall strictly after the former or the
    request is `ERR_INVALID_REQUEST`; a service that is not `PUBLISHED` is refused
    with `ERR_SERVICE_NOT_PUBLISHED`."
    PRD 3.3: "The service opens in `DRAFT` with `compliance_status` of
    `COMPLIANT`, `confirmed_engagement_count` of 0, `actual_start_utc` and
    `actual_end_utc` null, `provisional_service_cost_cents` at 0 and
    `final_service_cost_cents` null."

    Design: Corner/state_machines/clock_draft_service_returns_service_not_published
    """
    world = build_world()
    service = create_service(world.concert["id"], world.venue["id"])

    response = api.clock_rehearsal(
        service["id"], "2026-11-04T14:00:00Z", "2026-11-04T15:00:00Z",
        ORCHESTRA_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_SERVICE_NOT_PUBLISHED.value, 409)

    unchanged = read_service(service["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["actual_start_utc"] is None
    assert unchanged["final_service_cost_cents"] is None


def test_booking_a_player_onto_a_published_service_is_refused(api):
    """PRD 3.3: "The service must still be in `DRAFT` — a service already published
    or beyond is refused with `ERR_SERVICE_NOT_DRAFT` — and the concert's season
    must have a union agreement registered, without which the booking is refused
    with `ERR_UNION_AGREEMENT_MISSING` since none of the union arithmetic below
    would be defined."

    Design: Corner/state_machines/engagement_on_published_service_returns_service_not_draft
    """
    world = build_world()
    player = create_musician(full_name="Pia Solberg", instrument="VIOLIN")
    service = create_service(world.concert["id"], world.venue["id"],
                             minimum_complement=0, break_minutes=0)
    publish_service(service["id"])

    response = api.create_engagement(
        service["id"], {"musician_id": player["id"]}, ORCHESTRA_MANAGER
    )
    validate_error(response, ApiErrorId.ERR_SERVICE_NOT_DRAFT.value, 409)

    assert read_service(service["id"])["confirmed_engagement_count"] == 0
    assert read_musician(player["id"])["services_charged_ytd"] == 0


def test_declining_an_already_declined_engagement_is_refused(api):
    """PRD 3.3: "An engagement that is not `CONFIRMED` is refused with
    `ERR_ENGAGEMENT_NOT_CONFIRMED`, and the parent service must be either `DRAFT`
    or `PUBLISHED` — declining out of a cancelled or completed service is refused
    with `ERR_SERVICE_NOT_PUBLISHED`."
    PRD 3.3: "Hop one decrements the parent service's `confirmed_engagement_count`
    by one."

    Design: Corner/state_machines/decline_engagement_twice_returns_not_confirmed
    """
    world = build_world()
    player = create_musician(full_name="Pia Solberg", instrument="VIOLIN")
    service = create_service(world.concert["id"], world.venue["id"])
    engagement = add_engagement(service["id"], player["id"])
    decline_engagement(engagement["id"], player["id"])

    response = api.decline_engagement(
        engagement["id"], make_musician_headers(player["id"])
    )
    validate_error(response, ApiErrorId.ERR_ENGAGEMENT_NOT_CONFIRMED.value, 409)

    assert read_engagement(engagement["id"])["status"] == "DECLINED"
    assert read_service(service["id"])["confirmed_engagement_count"] == 0, (
        "the refused second decline must not push the count below zero"
    )


# --------------------------------------------------------------------------
# Union booking rules
# --------------------------------------------------------------------------
def test_booking_inside_the_rest_gap_is_refused(api):
    """PRD 2.6: "For the musician being booked, the gap between the end of any other
    of their `CONFIRMED` engagements' services and the start of this one —
    measured in whichever direction is applicable — must be at least
    `min_rest_minutes_between_services`; a gap exactly equal to the minimum
    passes. A shorter gap yields `ERR_UNION_REST_VIOLATION` with HTTP 422."

    Design: Corner/validations/engagement_inside_rest_gap_returns_union_rest_violation
    """
    world = build_world(
        union_overrides={
            "min_rest_minutes_between_services": 90,
            "max_services_per_day": 2,
            "mandatory_break_minutes": 20,
        }
    )
    player = create_musician(full_name="Pia Solberg", instrument="VIOLIN")
    morning = create_service(
        world.concert["id"], world.venue["id"],
        scheduled_start_utc="2026-11-04T09:00:00Z",
        scheduled_end_utc="2026-11-04T11:00:00Z",
        minimum_complement=0, break_minutes=20,
    )
    midday = create_service(
        world.concert["id"], world.venue["id"],
        scheduled_start_utc="2026-11-04T12:00:00Z",
        scheduled_end_utc="2026-11-04T14:00:00Z",
        minimum_complement=0, break_minutes=20,
    )
    add_engagement(morning["id"], player["id"])

    response = api.create_engagement(
        midday["id"], {"musician_id": player["id"]}, ORCHESTRA_MANAGER
    )
    error = validate_error(response, ApiErrorId.ERR_UNION_REST_VIOLATION.value, 422)
    assert error["error_id"] != ApiErrorId.ERR_UNION_DAILY_SERVICE_CAP.value, (
        "only two services are involved, so the daily cap of 2 is not yet reached"
    )

    assert read_service(midday["id"])["confirmed_engagement_count"] == 0
    _, meta = validate_paginated(
        api.list_engagements(ORCHESTRA_MANAGER, params={"musician_id": player["id"]})
    )
    assert meta["total_count"] == 1


def test_a_third_doubled_instrument_is_refused(api):
    """PRD 2.6: "The `doubling_count` on an engagement must not exceed 2, else
    `ERR_DOUBLING_LIMIT_EXCEEDED` with HTTP 422."
    PRD 3.3: "The **doubling limit** caps `doubling_count` at 2; a third doubled
    instrument is `ERR_DOUBLING_LIMIT_EXCEEDED`."

    Design: Corner/validations/engagement_with_three_doublings_returns_doubling_limit
    """
    world = build_world()
    player = create_musician(full_name="Ada Reed", instrument="CLARINET")
    service = create_service(world.concert["id"], world.venue["id"])

    response = api.create_engagement(
        service["id"], {"musician_id": player["id"], "doubling_count": 3},
        ORCHESTRA_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_DOUBLING_LIMIT_EXCEEDED.value, 422)

    _, meta = validate_paginated(
        api.list_engagements(ORCHESTRA_MANAGER, params={"service_id": service["id"]})
    )
    assert meta["total_count"] == 0
    assert read_service(service["id"])["confirmed_engagement_count"] == 0


def test_daily_service_cap_refuses_a_third_call_on_one_date(api):
    """PRD 2.6: "The musician may not hold more than `max_services_per_day`
    `CONFIRMED` engagements whose services start on the same UTC calendar date,
    whether or not those services overlap in time. Exceeding the cap yields
    `ERR_UNION_DAILY_SERVICE_CAP` with HTTP 409."

    Design: Difficulty/resource_temporal_overlap/musician_daily_service_cap_without_time_overlap
    """
    world = build_world(
        union_overrides={
            "max_services_per_day": 2,
            "min_rest_minutes_between_services": 90,
            "mandatory_break_minutes": 20,
        }
    )
    player = create_musician(full_name="Pia Solberg", instrument="VIOLIN")
    slots = [("09:00:00", "11:00:00"), ("13:00:00", "15:00:00"), ("18:00:00", "20:00:00")]
    services = [
        create_service(
            world.concert["id"], world.venue["id"],
            service_type="REHEARSAL" if index < 2 else "DRESS_REHEARSAL",
            scheduled_start_utc=f"2026-11-04T{start}Z",
            scheduled_end_utc=f"2026-11-04T{end}Z",
            minimum_complement=0, break_minutes=20,
        )
        for index, (start, end) in enumerate(slots)
    ]
    add_engagement(services[0]["id"], player["id"])
    add_engagement(services[1]["id"], player["id"])

    response = api.create_engagement(
        services[2]["id"], {"musician_id": player["id"]}, ORCHESTRA_MANAGER
    )
    validate_error(response, ApiErrorId.ERR_UNION_DAILY_SERVICE_CAP.value, 409)

    assert read_service(services[0]["id"])["confirmed_engagement_count"] == 1
    assert read_service(services[1]["id"])["confirmed_engagement_count"] == 1
    assert read_musician(player["id"])["services_charged_ytd"] == 0, (
        "no service has been published, so no service credit has been charged"
    )


def test_daily_service_cap_binds_even_when_the_rest_gap_is_ample(api):
    """PRD 2.6: "The musician may not hold more than `max_services_per_day`
    `CONFIRMED` engagements whose services start on the same UTC calendar date,
    whether or not those services overlap in time. Exceeding the cap yields
    `ERR_UNION_DAILY_SERVICE_CAP` with HTTP 409."
    PRD 3.3: "The **daily-service cap** counts this player's `CONFIRMED`
    engagements whose services begin on the same UTC calendar date as this one; if
    the player already holds `max_services_per_day` of them the booking is
    `ERR_UNION_DAILY_SERVICE_CAP`, and this applies whether or not the services
    overlap in time — two well-separated calls on one day still count as two."

    Design: Difficulty/resource_temporal_overlap/musician_daily_service_cap_without_time_overlap
    """
    world = build_world(
        union_overrides={
            "max_services_per_day": 2,
            "min_rest_minutes_between_services": 90,
            "mandatory_break_minutes": 20,
        }
    )
    player = create_musician(full_name="Pia Solberg", instrument="VIOLIN")
    slots = [("09:00:00", "11:00:00"), ("13:00:00", "15:00:00"), ("18:00:00", "20:00:00")]
    services = [
        create_service(
            world.concert["id"], world.venue["id"],
            service_type="REHEARSAL" if index < 2 else "DRESS_REHEARSAL",
            scheduled_start_utc=f"2026-11-04T{start}Z",
            scheduled_end_utc=f"2026-11-04T{end}Z",
            minimum_complement=0, break_minutes=20,
        )
        for index, (start, end) in enumerate(slots)
    ]
    add_engagement(services[0]["id"], player["id"])
    add_engagement(services[1]["id"], player["id"])

    response = api.create_engagement(
        services[2]["id"], {"musician_id": player["id"]}, ORCHESTRA_MANAGER
    )
    error = validate_error(response, ApiErrorId.ERR_UNION_DAILY_SERVICE_CAP.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_UNION_REST_VIOLATION.value, (
        "the 15:00 to 18:00 gap is 180 minutes, well over the 90-minute minimum"
    )

    assert read_service(services[2]["id"])["confirmed_engagement_count"] == 0
    _, meta = validate_paginated(
        api.list_engagements(ORCHESTRA_MANAGER, params={"musician_id": player["id"]})
    )
    assert meta["total_count"] == 2


# --------------------------------------------------------------------------
# Publication gates
# --------------------------------------------------------------------------
def test_publishing_below_the_minimum_complement_is_refused(api):
    """PRD 2.6: "At publication time the service's `confirmed_engagement_count` must
    be at least its `minimum_complement`, else `ERR_INSUFFICIENT_COMPLEMENT` with
    HTTP 409."
    PRD 3.3: "Third, the **complement rule**: `confirmed_engagement_count` must be
    at least `minimum_complement`, else `ERR_INSUFFICIENT_COMPLEMENT`."

    Design: Corner/validations/publish_below_minimum_complement_returns_insufficient_complement
    """
    world = build_world()
    player = create_musician(full_name="Pia Solberg", instrument="VIOLIN")
    service = create_service(world.concert["id"], world.venue["id"],
                             minimum_complement=2, break_minutes=0)
    engagement = add_engagement(service["id"], player["id"])

    response = api.publish_rehearsal(service["id"], ORCHESTRA_MANAGER)
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_COMPLEMENT.value, 409)

    assert read_service(service["id"])["status"] == "DRAFT"
    assert read_engagement(engagement["id"])["provisional_pay_cents"] is None
    assert read_musician(player["id"])["services_charged_ytd"] == 0


def test_publication_reports_the_union_break_rule_before_the_hall_conflict(api):
    """PRD 2.6: "Every write request is evaluated against a fixed ladder of checks,
    and the ladder is strictly ordered: the first check that fails determines the
    response, and no later check is evaluated."
    PRD 2.6: "**Union break rule.** A service whose scheduled duration is longer
    than 90 minutes must schedule at least `mandatory_break_minutes` of break,
    else `ERR_UNION_BREAK_VIOLATION` with HTTP 422. This applies only to `POST
    /orchestra/rehearsals/{service_id}/publish`."
    PRD 2.6: "**Venue changeover rule.** A service may not be published while
    another `PUBLISHED` service in the same hall collides with it once the hall's
    changeover buffer is added to both ends, yielding
    `ERR_VENUE_CHANGEOVER_CONFLICT` with HTTP 409."

    Design: Difficulty/priority_pair_validation_conflict/publish_union_break_beats_venue_changeover
    """
    world = build_world(union_overrides={"mandatory_break_minutes": 20},
                        venue_overrides={"name": "Grand Hall",
                                         "changeover_buffer_minutes": 60})
    first = create_service(
        world.concert["id"], world.venue["id"],
        scheduled_start_utc="2026-11-04T14:00:00Z",
        scheduled_end_utc="2026-11-04T16:00:00Z",
        minimum_complement=0, break_minutes=20,
    )
    publish_service(first["id"])

    second = create_service(
        world.concert["id"], world.venue["id"],
        scheduled_start_utc="2026-11-04T16:30:00Z",
        scheduled_end_utc="2026-11-04T18:30:00Z",
        minimum_complement=0, break_minutes=0,
    )

    response = api.publish_rehearsal(second["id"], ORCHESTRA_MANAGER)
    error = validate_error(response, ApiErrorId.ERR_UNION_BREAK_VIOLATION.value, 422)
    assert error["error_id"] != ApiErrorId.ERR_VENUE_CHANGEOVER_CONFLICT.value, (
        "the service also collides with the published one, but rung 10 outranks rung 14"
    )


def test_a_service_failing_the_break_rule_stays_draft_and_unpriced(api):
    """PRD 3.3: "First, the **break rule**: if the interval from
    `scheduled_start_utc` to `scheduled_end_utc` is longer than 90 minutes, then
    `break_minutes` must be at least the agreement's `mandatory_break_minutes`,
    else `ERR_UNION_BREAK_VIOLATION`. A service of exactly 90 minutes is not long
    enough to require a break."
    PRD 3.3: "The service opens in `DRAFT` with `compliance_status` of
    `COMPLIANT`, `confirmed_engagement_count` of 0, `actual_start_utc` and
    `actual_end_utc` null, `provisional_service_cost_cents` at 0 and
    `final_service_cost_cents` null."

    Design: Difficulty/priority_pair_validation_conflict/publish_union_break_beats_venue_changeover
    """
    world = build_world(union_overrides={"mandatory_break_minutes": 20},
                        venue_overrides={"name": "Grand Hall",
                                         "changeover_buffer_minutes": 60})
    first = create_service(
        world.concert["id"], world.venue["id"],
        scheduled_start_utc="2026-11-04T14:00:00Z",
        scheduled_end_utc="2026-11-04T16:00:00Z",
        minimum_complement=0, break_minutes=20,
    )
    publish_service(first["id"])
    second = create_service(
        world.concert["id"], world.venue["id"],
        scheduled_start_utc="2026-11-04T16:30:00Z",
        scheduled_end_utc="2026-11-04T18:30:00Z",
        minimum_complement=0, break_minutes=0,
    )

    validate_error(
        api.publish_rehearsal(second["id"], ORCHESTRA_MANAGER),
        ApiErrorId.ERR_UNION_BREAK_VIOLATION.value,
        422,
    )

    refused = read_service(second["id"])
    assert refused["status"] == "DRAFT"
    assert refused["provisional_service_cost_cents"] == 0


def test_publishing_inside_the_hall_changeover_buffer_is_refused(api):
    """PRD 2.8: "Two services in the same hall collide when both of the following
    hold at once: the new service's `scheduled_start_utc` falls strictly before the
    other service's `scheduled_end_utc` advanced by the buffer, and the other
    service's `scheduled_start_utc` falls strictly before the new service's
    `scheduled_end_utc` advanced by the buffer."
    PRD 2.6: "**Venue changeover rule.** A service may not be published while
    another `PUBLISHED` service in the same hall collides with it once the hall's
    changeover buffer is added to both ends, yielding
    `ERR_VENUE_CHANGEOVER_CONFLICT` with HTTP 409."

    Design: Difficulty/resource_temporal_overlap/venue_changeover_buffer_conflict_on_publish
    """
    world = build_world(union_overrides={"mandatory_break_minutes": 20},
                        venue_overrides={"name": "Grand Hall",
                                         "changeover_buffer_minutes": 60})
    first = create_service(
        world.concert["id"], world.venue["id"],
        scheduled_start_utc="2026-11-04T14:00:00Z",
        scheduled_end_utc="2026-11-04T16:00:00Z",
        minimum_complement=0, break_minutes=20,
    )
    publish_service(first["id"])

    second = create_service(
        world.concert["id"], world.venue["id"],
        scheduled_start_utc="2026-11-04T16:30:00Z",
        scheduled_end_utc="2026-11-04T18:00:00Z",
        minimum_complement=0, break_minutes=20,
    )

    response = api.publish_rehearsal(second["id"], ORCHESTRA_MANAGER)
    validate_error(response, ApiErrorId.ERR_VENUE_CHANGEOVER_CONFLICT.value, 409)

    assert read_service(second["id"])["status"] == "DRAFT"
    assert read_service(first["id"])["status"] == "PUBLISHED"


def test_publishing_exactly_at_the_end_plus_buffer_is_allowed(api):
    """PRD 2.8: "The intervals are half-open, so a new service starting at exactly
    the other service's end plus the buffer does **not** collide and is allowed."
    PRD 2.8: "Only services whose status is `PUBLISHED` participate in this test;
    `DRAFT`, `COMPLETED` and `CANCELLED` services in the same hall are invisible to
    it, which is why a room may hold any number of draft services at overlapping
    times and only the second attempt to publish fails."

    Design: Difficulty/resource_temporal_overlap/venue_changeover_buffer_conflict_on_publish
    """
    world = build_world(union_overrides={"mandatory_break_minutes": 20},
                        venue_overrides={"name": "Grand Hall",
                                         "changeover_buffer_minutes": 60})
    first = create_service(
        world.concert["id"], world.venue["id"],
        scheduled_start_utc="2026-11-04T14:00:00Z",
        scheduled_end_utc="2026-11-04T16:00:00Z",
        minimum_complement=0, break_minutes=20,
    )
    publish_service(first["id"])

    second = create_service(
        world.concert["id"], world.venue["id"],
        scheduled_start_utc="2026-11-04T17:00:00Z",
        scheduled_end_utc="2026-11-04T18:30:00Z",
        minimum_complement=0, break_minutes=20,
    )

    published = validate_success(api.publish_rehearsal(second["id"], ORCHESTRA_MANAGER))
    assert published["status"] == "PUBLISHED", (
        "17:00 is exactly 16:00 plus the 60-minute buffer, so the intervals do not collide"
    )
    assert read_service(first["id"])["status"] == "PUBLISHED"
