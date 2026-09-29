"""Overlap is measured on the right shape.

Seat segments overlap on a two-dimensional rectangle - the closed row interval
crossed with the letter set - so segments that share rows but no letters coexist.
Seat occupancy is a point conflict on (segment, row, letter), distinct from asking
for a row outside the rectangle.  Offer validity is a half-open window, so the
instant equal to valid_until is already outside it.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    OPERATIONS_CONTROLLER,
    REVENUE_ACCOUNTANT,
    ApiErrorId,
    Scenario,
    assert_entry_amounts,
    assert_field_values,
    assert_instants,
    assert_segment_counts,
    factories,
    find_one_entry,
    make_channel_partner_headers,
)

CLOCK = "2026-08-10T09:00:00Z"


def _rectangle_world(scenario: Scenario):
    """Flight AB900 with one OPEN MID segment on rows 10..14 x {A,B,C}."""
    scenario.set_clock(CLOCK)
    seat = scenario.create_product(factories.standard_seat_product_payload())
    flight = scenario.create_flight(flight_no="AB900", origin="JFK", destination="LAX")
    base = scenario.create_segment(
        flight["id"],
        seat["id"],
        zone="MID",
        row_start=10,
        row_end=14,
        seat_letters=["A", "B", "C"],
        base_price_cents=2000,
    )
    return {"product_id": seat["id"], "flight_id": flight["id"], "base_segment": base}


def test_seat_segment_sharing_rows_and_a_letter_is_refused(scenario):
    """Rows 12..16 x {C,D} shares seats 12C, 13C and 14C, so it is refused.

    The clash is on three concrete seats, not on the row interval alone, and the
    rejection leaves the flight with only its original segment.

    Design: Difficulty/resource_temporal_overlap/seat_segment_rectangle_overlap_rows_crossed_with_letters
    """
    world = _rectangle_world(scenario)

    response = scenario.api.create_seat_segment(
        factories.seat_segment_payload(
            world["flight_id"],
            world["product_id"],
            zone="AFT",
            row_start=12,
            row_end=16,
            seat_letters=["C", "D"],
            base_price_cents=1800,
        ),
        OPERATIONS_CONTROLLER,
    )
    validate_error(response, ApiErrorId.SEAT_SEGMENT_ROW_OVERLAP, 409)

    segments = validate_success(
        scenario.api.list_seat_segments(
            OPERATIONS_CONTROLLER, {"flight_id": world["flight_id"]}
        )
    )
    assert len(segments) == 1, (
        f"the refused candidate must not be persisted, found {len(segments)} segments"
    )


def test_seat_segment_sharing_rows_but_no_letter_is_accepted(scenario):
    """Rows 12..16 x {D,E} straddles the same rows yet shares no seat, so it is legal.

    The new segment holds (16 - 12 + 1) x 2 == 10 seats, all available, and the
    original 15-seat segment is untouched: two segments now cover 25 of the 180
    cabin seats.

    Design: Difficulty/resource_temporal_overlap/seat_segment_rectangle_overlap_rows_crossed_with_letters
    """
    world = _rectangle_world(scenario)

    created = scenario.create_segment(
        world["flight_id"],
        world["product_id"],
        zone="AFT",
        row_start=12,
        row_end=16,
        seat_letters=["D", "E"],
        base_price_cents=1800,
    )
    assert_segment_counts(created, total_seats=10, available_seats=10)

    base = scenario.get_segment(world["base_segment"]["id"])
    assert_segment_counts(base, total_seats=15, available_seats=15)
    assert base["segment_state"] == "OPEN", (
        f"the existing segment stays OPEN, got {base['segment_state']!r}"
    )

    segments = validate_success(
        scenario.api.list_seat_segments(
            OPERATIONS_CONTROLLER, {"flight_id": world["flight_id"]}
        )
    )
    assert len(segments) == 2, f"expected exactly 2 segments, found {len(segments)}"
    assert sum(s["total_seats"] for s in segments) == 25, (
        "the two segments must cover 25 seats in total, "
        f"got {sum(s['total_seats'] for s in segments)}"
    )


def _offer_window_world(scenario: Scenario):
    """Flight AC100 at 09:00 with a HELD booking and an unfiltered BOOKING session.

    ECO_LITE bundles the checked bag, so the seat and the boarding product are the
    two merchandisable candidates.  No seat segment exists on the flight, so the
    seat offer is priced by the willingness-to-pay path.
    """
    scenario.set_clock(CLOCK)
    bag = scenario.create_product(factories.checked_bag_product_payload())
    seat = scenario.create_product(factories.standard_seat_product_payload())
    boarding = scenario.create_product(factories.priority_boarding_product_payload())

    family = scenario.create_family(factories.eco_lite_family_payload())
    scenario.add_attribute(family["id"], bag["id"], inclusion="INCLUDED", included_quantity=1)
    scenario.publish_family(family["id"])

    channel = scenario.create_channel(factories.direct_web_channel_payload())
    flight = scenario.create_flight(flight_no="AC100", origin="JFK", destination="LAX")
    scenario.post_demand(flight["id"], 75, 1200)

    booking = scenario.create_booking(
        flight["id"], family["id"], channel["id"], record_locator="WINDW1"
    )
    session = scenario.open_offer_session(booking["id"], channel["id"], "BOOKING")

    seat_offers = scenario.offers_for_booking(
        booking["id"], channel["id"], ancillary_product_id=seat["id"]
    )
    boarding_offers = scenario.offers_for_booking(
        booking["id"], channel["id"], ancillary_product_id=boarding["id"]
    )
    assert len(seat_offers) == 1, f"expected one seat offer, got {len(seat_offers)}"
    assert len(boarding_offers) == 1, (
        f"expected one boarding offer, got {len(boarding_offers)}"
    )

    return {
        "channel_id": channel["id"],
        "booking_id": booking["id"],
        "session": session,
        "seat_offer": seat_offers[0],
        "boarding_offer": boarding_offers[0],
        "seat_sku": seat["sku"],
    }


def test_offers_are_presented_with_a_one_hour_halfopen_window(scenario):
    """Both offers open at the clock and are ranked by expected value.

    The session sees two candidates: the seat at 2091 with an expected value of
    2302 takes rank 1 and the boarding product at 1376 with 1515 takes rank 2.
    Each window runs from 09:00:00Z up to - but not including - 10:00:00Z.

    Design: Difficulty/resource_temporal_overlap/offer_window_halfopen_boundary_at_valid_until
    """
    world = _offer_window_world(scenario)

    assert world["session"]["candidate_count"] == 2, (
        f"two products are merchandisable, got {world['session']['candidate_count']}"
    )
    assert_field_values(
        world["seat_offer"],
        sequence_rank=1,
        offered_price_cents=2091,
        expected_value_cents=2302,
    )
    assert_field_values(
        world["boarding_offer"],
        sequence_rank=2,
        offered_price_cents=1376,
        expected_value_cents=1515,
    )
    for offer in (world["seat_offer"], world["boarding_offer"]):
        # valid_from is the clock; valid_until is exactly one hour later.
        assert_instants(
            offer,
            valid_from="2026-08-10T09:00:00Z",
            valid_until="2026-08-10T10:00:00Z",
        )


def test_offer_accepted_one_second_before_valid_until_succeeds(scenario):
    """09:59:59Z is still inside the window, so the acceptance stands and sells the seat.

    The offer becomes ACCEPTED at its offered 2091 cents and posts exactly one SALE
    of 2091 / 84 / 2007 traced to the offer.  Pre-ticket the booking recognizes the
    ancillary money but the settlement fields stay at zero, because there is no fare
    component yet.

    Design: Difficulty/resource_temporal_overlap/offer_window_halfopen_boundary_at_valid_until
    """
    world = _offer_window_world(scenario)
    booking_id = world["booking_id"]
    channel_id = world["channel_id"]
    offer_id = world["seat_offer"]["id"]

    booking = scenario.get_booking(booking_id, channel_id)
    scenario.set_clock("2026-08-10T09:59:59Z")

    accepted = scenario.accept_offer(offer_id, channel_id, booking["version"])
    assert_field_values(accepted, offer_status="ACCEPTED", accepted_price_cents=2091)

    entries = validate_success(
        scenario.api.list_booking_revenue_entries(booking_id, REVENUE_ACCOUNTANT)
    )
    assert len(entries) == 1, f"acceptance posts exactly one row, found {len(entries)}"
    sale = find_one_entry(entries, entry_type="SALE", category="SEAT")
    assert_entry_amounts(sale, 2091, 84, 2007)
    assert sale["product_sku"] == world["seat_sku"], (
        f"the sale must name the seat product, got {sale['product_sku']!r}"
    )
    assert sale["source_ref"] == f"offer:{offer_id}", (
        f"the sale must trace to the accepted offer, got {sale['source_ref']!r}"
    )

    after = scenario.get_booking(booking_id, channel_id)
    assert_field_values(
        after,
        ancillary_gross_cents=2091,
        recognized_ancillary_net_cents=2007,
        commission_cents=0,
        incentive_credit_cents=0,
        channel_settlement_total_cents=0,
    )
    assert after["fare_component_cents"] is None, (
        f"an un-ticketed booking has no fare component, got {after['fare_component_cents']!r}"
    )


def test_clock_reaching_valid_until_expires_the_untouched_offer(scenario):
    """A clock equal to valid_until is outside the window, so the rank-2 offer expires.

    Accepting the seat offer does not supersede the boarding offer - superseding is
    confined to sibling offers of the same product - so it is still PRESENTED when
    the clock reaches exactly 10:00:00Z, and that clock move reports
    expired_offer_count 1.

    Design: Difficulty/resource_temporal_overlap/offer_window_halfopen_boundary_at_valid_until
    """
    world = _offer_window_world(scenario)
    channel_id = world["channel_id"]
    partner = make_channel_partner_headers(channel_id)
    boarding_offer_id = world["boarding_offer"]["id"]

    booking = scenario.get_booking(world["booking_id"], channel_id)
    scenario.set_clock("2026-08-10T09:59:59Z")
    scenario.accept_offer(world["seat_offer"]["id"], channel_id, booking["version"])

    still_open = validate_success(
        scenario.api.get_ancillary_offer(boarding_offer_id, partner)
    )
    assert still_open["offer_status"] == "PRESENTED", (
        "accepting a seat offer must not supersede a boarding offer, "
        f"got {still_open['offer_status']!r}"
    )

    clock = scenario.set_clock("2026-08-10T10:00:00Z")
    assert clock["expired_offer_count"] == 1, (
        f"the boundary instant expires the open offer, got {clock['expired_offer_count']}"
    )
    expired = validate_success(
        scenario.api.get_ancillary_offer(boarding_offer_id, partner)
    )
    assert expired["offer_status"] == "EXPIRED", (
        f"a clock equal to valid_until leaves the offer EXPIRED, got {expired['offer_status']!r}"
    )


def _occupancy_world(scenario: Scenario):
    """Flight AC200 with a repriced 2200-cent MID segment, 16A already held."""
    scenario.set_clock(CLOCK)
    bag = scenario.create_product(factories.checked_bag_product_payload())
    seat = scenario.create_product(factories.standard_seat_product_payload())

    family = scenario.create_family(factories.eco_lite_family_payload())
    scenario.add_attribute(family["id"], bag["id"], inclusion="INCLUDED", included_quantity=1)
    scenario.publish_family(family["id"])

    channel = scenario.create_channel(factories.direct_web_channel_payload())
    flight = scenario.create_flight(flight_no="AC200", origin="JFK", destination="LAX")
    segment = scenario.create_segment(
        flight["id"],
        seat["id"],
        zone="MID",
        row_start=16,
        row_end=18,
        seat_letters=["A", "B", "C"],
        base_price_cents=2000,
    )
    scenario.post_demand(flight["id"], 60, 0)

    first = scenario.create_booking(
        flight["id"], family["id"], channel["id"], record_locator="SEATA1"
    )
    first_assignment = scenario.assign_seat(
        first["id"], channel["id"], segment["id"], 16, "A"
    )
    second = scenario.create_booking(
        flight["id"], family["id"], channel["id"], record_locator="SEATB1"
    )
    return {
        "channel_id": channel["id"],
        "segment_id": segment["id"],
        "first_booking_id": first["id"],
        "first_assignment_id": first_assignment["id"],
        "second_booking_id": second["id"],
    }


def test_taken_seat_is_refused_as_a_point_conflict(scenario):
    """A second booking asking for 16A is refused, and the sitting assignment is untouched.

    Design: Difficulty/resource_temporal_overlap/seat_point_occupancy_and_out_of_rectangle_assignment
    """
    world = _occupancy_world(scenario)
    partner = make_channel_partner_headers(world["channel_id"])

    response = scenario.api.create_seat_assignment(
        world["second_booking_id"],
        factories.seat_assignment_payload(world["segment_id"], 16, "A"),
        partner,
    )
    validate_error(response, ApiErrorId.SEAT_ALREADY_OCCUPIED, 409)

    first = validate_success(
        scenario.api.get_seat_assignment(world["first_assignment_id"], partner)
    )
    assert_field_values(first, assignment_state="HELD", row=16, seat_letter="A")

    segment = scenario.get_segment(world["segment_id"])
    assert_segment_counts(
        segment, total_seats=9, held_seats=1, sold_seats=0, available_seats=8
    )


def test_row_outside_the_segment_rectangle_is_a_different_failure(scenario):
    """Row 21 lies outside the closed rows 16..18, which is a validation failure, not a conflict.

    The two failure modes must stay distinct: this one answers 422 with
    ERR_SEAT_ROW_OUT_OF_SEGMENT rather than the 409 an occupied seat returns.

    Design: Difficulty/resource_temporal_overlap/seat_point_occupancy_and_out_of_rectangle_assignment
    """
    world = _occupancy_world(scenario)
    partner = make_channel_partner_headers(world["channel_id"])

    response = scenario.api.create_seat_assignment(
        world["second_booking_id"],
        factories.seat_assignment_payload(world["segment_id"], 21, "A"),
        partner,
    )
    validate_error(response, ApiErrorId.SEAT_ROW_OUT_OF_SEGMENT, 422)

    segment = scenario.get_segment(world["segment_id"])
    assert_segment_counts(
        segment, total_seats=9, held_seats=1, sold_seats=0, available_seats=8
    )


def test_free_seat_on_the_same_segment_is_held_at_the_repriced_amount(scenario):
    """16B is free, so the assignment succeeds at the segment's 2200-cent repriced amount.

    Rows 16 and above take no row-band adjustment, the MID zone contributes no
    uplift and a load factor of 60 puts the flight in the MID demand tier, so the
    price is 2200.  The segment then reads 9 total, 2 held, 0 sold and 7 available,
    and neither held booking has a ledger row.

    Design: Difficulty/resource_temporal_overlap/seat_point_occupancy_and_out_of_rectangle_assignment
    """
    world = _occupancy_world(scenario)

    assignment = scenario.assign_seat(
        world["second_booking_id"], world["channel_id"], world["segment_id"], 16, "B"
    )
    assert_field_values(
        assignment, assignment_state="HELD", price_charged_cents=2200
    )

    segment = scenario.get_segment(world["segment_id"])
    assert_segment_counts(
        segment, total_seats=9, held_seats=2, sold_seats=0, available_seats=7
    )

    for booking_id in (world["first_booking_id"], world["second_booking_id"]):
        entries = validate_success(
            scenario.api.list_booking_revenue_entries(booking_id, REVENUE_ACCOUNTANT)
        )
        assert entries == [], f"a held seat posts no revenue, got {entries}"
