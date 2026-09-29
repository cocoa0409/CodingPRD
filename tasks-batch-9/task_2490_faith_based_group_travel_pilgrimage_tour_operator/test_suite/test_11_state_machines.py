"""Transitions the machines admit and refuse: the opening of sales, the state a
service booking is born in, terminal lockdown on departures, bookings and land
lines, the negotiation party gate, the celebrant gate, and advisory supersession.
"""

from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_instant_equals,
    assert_version_bumped,
    cancel_service_booking,
    clergy_confirm,
    counter_fare,
    create_advisory,
    create_air_block,
    create_land_assignment,
    create_land_resource,
    create_open_access_site,
    create_sacred_site,
    create_service_booking,
    hold_filler_service,
    offer_fare,
    open_departure,
    open_sales,
    program_with_departure,
    publish_advisory,
    read_advisory,
    read_air_block,
    read_departure,
    read_land_assignment,
    read_service_booking,
    validate_error,
    validate_success,
    TEST_USERS,
)

PLANNER = TEST_USERS["program_manager"]
AIR_DESK = TEST_USERS["air_desk_agent"]
LAND = TEST_USERS["land_contractor"]
RISK = TEST_USERS["risk_officer"]


# ---------------------------------------------------------------------------
# Departure: the opening of sales, and the terminal cancellation
# ---------------------------------------------------------------------------


def test_opening_sales_writes_the_provisional_tier_snapshot(api):
    """PRD §3.1: "Opening sales clears `final_tier_code` back to unset and
    `final_per_pax_price_cents` back to 0, re-derives the provisional snapshot,
    re-reads the risk posture, and increments the departure's `version`." And on
    the empty roster it re-derives from: "It then raises that count to at least 1
    before selecting a tier, so an empty roster is still quoted at the
    smallest-group tier and `provisional_deposit_cents` is never left at 0 once
    the roster has been touched."

    Design: Corner/state_machines/departure_open_sales_transition_writes_provisional_tier
    """
    program, departure = program_with_departure()
    # An empty itinerary is refused, so the departure carries one held service.
    hold_filler_service(program, departure)
    before = read_departure(departure["id"])

    opened = validate_success(
        api_client.open_departure_sales(departure["id"], PLANNER)
    )

    assert opened["status"] == "OPEN_FOR_SALE"
    assert opened["provisional_tier_code"] == "T1"
    assert opened["provisional_per_pax_price_cents"] == 587_000
    assert opened["provisional_single_supplement_cents"] == 98_000
    assert opened["provisional_deposit_cents"] == 50_000
    assert opened["paying_pax_count"] == 0
    assert_version_bumped(before, opened)


def test_a_cancelled_departure_cannot_be_reopened_for_sale(api):
    """PRD §3.1: "A departure reaches `CANCELLED` from `PLANNING`,
    `OPEN_FOR_SALE` or `SALES_CLOSED`, with the full unwind described in §3.9.
    `OPERATED` and `CANCELLED` are terminal and admit no further transition."

    Design: Corner/state_machines/cancelled_departure_cannot_reopen_sales
    """
    program, departure = program_with_departure()
    hold_filler_service(program, departure)
    open_sales(departure["id"])
    cancelled = validate_success(
        api_client.cancel_departure(
            departure["id"], {"cancellation_reason": "INSUFFICIENT_DEMAND"}, PLANNER
        )
    )
    assert cancelled["status"] == "CANCELLED"

    response = api_client.open_departure_sales(departure["id"], PLANNER)
    validate_error(response, ApiErrorId.DEPARTURE_INVALID_STATE.value)

    assert read_departure(departure["id"])["status"] == "CANCELLED"


# ---------------------------------------------------------------------------
# ServiceBooking: the state it is born in, and terminal cancellation
# ---------------------------------------------------------------------------


def _garden_site_and_departure():
    program, departure = program_with_departure()
    site = create_open_access_site(
        name="Mount of Beatitudes Garden", country="IL", daily_capacity_pax=300
    )
    return departure, site


def test_a_newly_held_service_is_site_held_with_no_celebrant_recorded(api):
    """PRD §3.2: "The server computes `buffered_end_utc` as the
    `scheduled_start_utc` advanced by `duration_minutes` and then by the site's
    `turnaround_buffer_minutes`; that instant is the **exclusive** end of the
    interval the booking occupies. The row is written in `SITE_HELD`, with
    `cancelled_by_risk` false, and holding it sets the parent departure's
    `service_coverage_ok` to false, because a newly held service is not yet
    confirmed."

    Design: Corner/state_machines/service_booking_starts_in_site_held
    """
    departure, site = _garden_site_and_departure()

    created = validate_success(
        api_client.create_service_booking(
            {
                "departure_id": departure["id"],
                "sacred_site_id": site["id"],
                "service_type": "PRAYER_SERVICE",
                "scheduled_start_utc": "2026-11-04T08:00:00Z",
                "duration_minutes": 45,
                "pax_count": 12,
            },
            PLANNER,
        ),
        201,
    )

    assert created["status"] == "SITE_HELD"
    # 08:00 plus 45 minutes of service and no turnaround at all.
    assert_instant_equals(created["buffered_end_utc"], "2026-11-04T08:45:00Z")
    assert created["clergy_contact_name"] is None
    assert created["clergy_tradition"] is None
    assert created["permit_reference"] is None
    assert created["cancelled_by_risk"] is False
    assert read_departure(departure["id"])["service_coverage_ok"] is False


def test_cancelling_a_service_booking_twice_is_refused_on_the_second_call(api):
    """PRD §3.2: "A `ProgramManager` or a `RiskOfficer` may cancel a booking in
    `SITE_HELD`, `CLERGY_CONFIRMED` or `CONFIRMED`, supplying a
    `cancellation_reason`; cancelling an already-`CANCELLED` booking is
    `ERR_SERVICE_BOOKING_INVALID_STATE`."

    Design: Corner/state_machines/service_booking_cancel_twice_rejects_second_call
    """
    departure, site = _garden_site_and_departure()
    booking = create_service_booking(
        departure["id"],
        site["id"],
        service_type="PRAYER_SERVICE",
        scheduled_start_utc="2026-11-04T08:00:00Z",
        duration_minutes=45,
        pax_count=12,
    )
    cancel_service_booking(booking["id"], "ITINERARY_RESEQUENCED")

    response = api_client.cancel_service_booking(
        booking["id"], {"cancellation_reason": "ITINERARY_RESEQUENCED"}, PLANNER
    )
    validate_error(response, ApiErrorId.SERVICE_BOOKING_INVALID_STATE.value)

    live = read_service_booking(booking["id"])
    assert live["status"] == "CANCELLED"
    assert live["cancelled_by_risk"] is False


def test_a_celebrant_of_the_wrong_tradition_is_refused(api):
    """PRD §3.2: "The recorded `clergy_tradition` — one of `CATHOLIC`,
    `ORTHODOX`, `PROTESTANT`, `JEWISH`, `MUSLIM` or `INTERFAITH` — must equal
    the program's `faith_tradition`, unless the program's tradition is
    `INTERFAITH`, which accepts any celebrant; a mismatch is
    `ERR_CLERGY_NOT_CONFIRMED`."

    Design: Corner/state_machines/clergy_confirm_with_mismatched_tradition_rejected
    """
    _program, departure = program_with_departure()
    site = create_sacred_site(
        name="Basilica of the Holy Sepulchre",
        country="IL",
        access_regime="PERMIT_REQUIRED",
        daily_capacity_pax=200,
        turnaround_buffer_minutes=30,
        requires_local_clergy=True,
    )
    booking = create_service_booking(
        departure["id"],
        site["id"],
        service_type="MASS",
        scheduled_start_utc="2026-11-02T06:00:00Z",
        duration_minutes=60,
        pax_count=10,
        permit_reference="PRM-2026-441",
    )

    response = api_client.clergy_confirm_service_booking(
        booking["id"],
        {
            "clergy_contact_name": "Fr. Nikolaos Vasilakis",
            "clergy_tradition": "ORTHODOX",
        },
        PLANNER,
    )
    validate_error(response, ApiErrorId.CLERGY_NOT_CONFIRMED.value)

    live = read_service_booking(booking["id"])
    assert live["status"] == "SITE_HELD"
    assert live["clergy_contact_name"] is None
    assert live["clergy_tradition"] is None
    # The Catholic celebrant the same booking would have accepted.
    accepted = clergy_confirm(booking["id"], "Fr. Elias Haddad", "CATHOLIC")
    assert accepted["status"] == "CLERGY_CONFIRMED"


# ---------------------------------------------------------------------------
# AirBlock: the party gate and the terminal contract
# ---------------------------------------------------------------------------


def test_confirming_an_already_contracted_block_is_refused(api):
    """PRD §3.6: "Confirming a block requires it to be in `OFFERED`, requires
    the logical clock to be at or before `deposit_deadline_utc`, and requires
    that no other block on the same departure is already `CONFIRMED` — a
    departure has at most one contracted block. Any of those failures is
    `ERR_AIR_BLOCK_INVALID_STATE`."

    Design: Corner/state_machines/air_block_confirm_twice_rejects_second_call
    """
    _program, departure = program_with_departure()
    block = create_air_block(departure["id"], carrier_code="LY", seats_held=20)
    offer_fare(block["id"], 850_000)
    validate_success(api_client.confirm_air_block(block["id"], AIR_DESK))

    response = api_client.confirm_air_block(block["id"], AIR_DESK)
    validate_error(response, ApiErrorId.AIR_BLOCK_INVALID_STATE.value)

    live = read_air_block(block["id"])
    assert live["status"] == "CONFIRMED"
    assert live["contracted_fare_cents"] == 850_000
    assert live["negotiation_round"] == 1


def test_an_operator_counter_cannot_open_the_negotiation(api):
    """PRD §3.6: "An `OPERATOR_COUNTER` is accepted from `OFFERED` only, and
    moves the block to `COUNTERED`." The party gate itself: "The `party` must
    match the standing state, and a mismatch is `ERR_AIR_BLOCK_INVALID_STATE`
    (HTTP 409)"

    Design: Corner/state_machines/air_block_operator_counter_from_draft_is_rejected
    """
    _program, departure = program_with_departure()
    block = create_air_block(departure["id"], carrier_code="LY", seats_held=20)

    response = api_client.add_negotiation_round(
        block["id"], {"party": "OPERATOR_COUNTER", "fare_cents": 700_000}, AIR_DESK
    )
    validate_error(response, ApiErrorId.AIR_BLOCK_INVALID_STATE.value)

    live = read_air_block(block["id"])
    assert live["status"] == "DRAFT"
    assert live["negotiation_round"] == 0
    # §3.6: "The block opens in `DRAFT` with `negotiation_round` at 0,
    # `offered_fare_cents` at 0, no `countered_fare_cents` and no
    # `contracted_fare_cents` yet" — the rejected counter wrote nothing.
    assert live["countered_fare_cents"] is None
    # The carrier offer the same DRAFT block does accept.
    offered = offer_fare(block["id"], 850_000)
    assert offered["status"] == "OFFERED"
    countered = counter_fare(block["id"], 700_000)
    assert countered["status"] == "COUNTERED"


# ---------------------------------------------------------------------------
# LandAssignment: TERMINATED admits nothing further
# ---------------------------------------------------------------------------


def test_countersigning_a_terminated_land_line_is_refused(api):
    """PRD §3.3: "Countersigning a line moves it from `DRAFT` to
    `COUNTERSIGNED`, requires that the line be in `DRAFT` and that the parent
    departure not be `CANCELLED`, recomputes the departure's rollup, and
    increments the line's `version`; countersigning anything other than a draft
    is `ERR_LAND_ASSIGNMENT_INVALID_STATE`."

    Design: Corner/state_machines/land_assignment_countersign_after_terminate_rejected
    """
    _program, departure = program_with_departure(
        departure_overrides={
            "departure_date": "2026-10-05",
            "return_date": "2026-10-15",
        }
    )
    resource = create_land_resource(
        operator_name="Jerusalem Ground Services",
        country="IL",
        resource_type="MOTORCOACH",
        units_total=3,
        unit_rate_local_cents=127_500,
        fx_rate_bp=10_833,
        force_majeure_notice_days=30,
    )
    line = create_land_assignment(
        resource["id"],
        departure["id"],
        date_from="2026-10-05",
        date_to="2026-10-09",
        units_requested=2,
    )
    terminated = validate_success(
        api_client.terminate_land_assignment(
            line["id"], {"termination_reason": "OPERATOR_SWITCH"}, LAND
        )
    )
    # The clock sits 65 days ahead of date_from, past the 30-day notice window.
    assert terminated["terminated_penalty_free"] is True

    response = api_client.countersign_land_assignment(line["id"], LAND)
    validate_error(response, ApiErrorId.LAND_ASSIGNMENT_INVALID_STATE.value)

    live = read_land_assignment(line["id"])
    assert live["status"] == "TERMINATED"
    assert live["terminated_penalty_free"] is True


# ---------------------------------------------------------------------------
# RiskAdvisory: one governing notice per country
# ---------------------------------------------------------------------------


def test_publishing_a_second_advisory_supersedes_the_first_and_repostures(api):
    """PRD §3.9: "Publication first moves any other advisory for the same
    `country` that is currently `PUBLISHED` to `SUPERSEDED`, so at most one
    advisory per country governs at a time."

    Design: Corner/state_machines/publishing_second_advisory_supersedes_the_first_and_repostures
    """
    stage = open_departure()
    departure_id = stage["departure"]["id"]
    first = create_advisory(country="IL", level="EXERCISE_CAUTION")
    publish_advisory(first["id"])
    assert read_departure(departure_id)["risk_posture"] == "WATCH"
    second = create_advisory(country="IL", level="RECONSIDER")

    published = validate_success(api_client.publish_advisory(second["id"], RISK))

    assert read_advisory(first["id"])["status"] == "SUPERSEDED"
    assert published["status"] == "PUBLISHED"
    assert published["affected_departure_count"] == 1

    departure = read_departure(departure_id)
    assert departure["risk_posture"] == "RESTRICTED"
    assert departure["governing_advisory_id"] == second["id"]
    assert departure["status"] == "OPEN_FOR_SALE"
