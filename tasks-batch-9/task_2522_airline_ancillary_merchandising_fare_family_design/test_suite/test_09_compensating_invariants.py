"""Compensating actions must restore the invariants they disturbed.

Both cases run a forward action and then its compensation, and check that the
money identity (recognized_ancillary_net_cents against the ledger, and the
channel settlement total against the fare component plus ancillary gross) and
the physical identity (total_seats == held + sold + available) each come back to
their pre-action value while the append-only ledger only ever grows.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    OPERATIONS_CONTROLLER,
    REVENUE_ACCOUNTANT,
    Scenario,
    assert_entry_amounts,
    assert_field_values,
    assert_recognized_net_matches_ledger,
    assert_segment_counts,
    factories,
    find_one_entry,
    make_channel_partner_headers,
)

CLOCK = "2026-08-10T09:00:00Z"


def _settlement_world(scenario: Scenario):
    """SETTLE_BASE published on DIRECT_WEB, flight AC300 with a 2200-cent seat.

    Returns the ids the tests need: the channel, the flight, the segment, the
    booking and its single seat assignment, ticketed so that the seat sale and
    the fare allocation are both on the ledger.
    """
    scenario.set_clock(CLOCK)
    bag = scenario.create_product(factories.checked_bag_product_payload())
    seat = scenario.create_product(factories.standard_seat_product_payload())

    family = scenario.create_family(
        factories.fare_family_payload(
            code="SETTLE_BASE",
            name="Settlement Base",
            cabin_class="ECONOMY",
            base_fare_cents=26000,
            bundle_price_cents=27523,
            refundability="NON_REFUNDABLE",
            change_fee_cents=7500,
            boarding_priority_tier=3,
        )
    )
    scenario.add_attribute(family["id"], bag["id"], inclusion="INCLUDED", included_quantity=1)
    published = scenario.publish_family(family["id"])

    channel = scenario.create_channel(factories.direct_web_channel_payload())
    scenario.publish_to_channel(family["id"], channel["id"], published["version"])

    flight = scenario.create_flight(flight_no="AC300", origin="JFK", destination="LAX")
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

    booking = scenario.create_booking(
        flight["id"], family["id"], channel["id"], record_locator="INVAR1"
    )
    assignment = scenario.assign_seat(booking["id"], channel["id"], segment["id"], 16, "A")
    scenario.hold_disclose_ack_and_ticket(booking["id"], channel["id"])

    return {
        "channel_id": channel["id"],
        "flight_id": flight["id"],
        "segment_id": segment["id"],
        "booking_id": booking["id"],
        "assignment_id": assignment["id"],
        "seat_sku": seat["sku"],
    }


def test_seat_release_refund_restores_recognized_ancillary_net(scenario):
    """A PASSENGER_RELEASE refund brings recognized ancillary net back to its pre-sale value.

    Ticketing leaves three rows - the two fare allocations and the 2200-cent seat
    sale - and recognized_ancillary_net_cents reads 5246.  The release posts a
    mirroring REFUND of -2200 / -88 / -2112, so the identity settles back on the
    3134 cents the baggage allocation recognized, with ancillary_gross_cents at 0.

    Design: Difficulty/compensating_invariant/seat_release_refund_preserves_ancillary_net_revenue_identity
    """
    world = _settlement_world(scenario)
    booking_id = world["booking_id"]
    channel_id = world["channel_id"]

    before = scenario.get_booking(booking_id, channel_id)
    entries_before = scenario.booking_ledger(booking_id)
    assert len(entries_before) == 3, (
        f"ticketing posts two allocations and the seat sale, found {len(entries_before)}"
    )
    assert_entry_amounts(
        find_one_entry(entries_before, entry_type="ALLOCATION", category="BAGGAGE"),
        3265,
        131,
        3134,
    )
    assert_entry_amounts(
        find_one_entry(entries_before, entry_type="ALLOCATION", category="AIR_TRANSPORT"),
        24258,
        1819,
        22439,
    )
    assert_entry_amounts(
        find_one_entry(entries_before, entry_type="SALE", category="SEAT"), 2200, 88, 2112
    )
    assert_field_values(
        before, ancillary_gross_cents=2200, recognized_ancillary_net_cents=5246
    )
    assert_recognized_net_matches_ledger(before, entries_before)

    scenario.release_seat(world["assignment_id"], channel_id, "PASSENGER_RELEASE")

    entries_after = scenario.booking_ledger(booking_id)
    refund = find_one_entry(entries_after, entry_type="REFUND", category="SEAT")
    assert_entry_amounts(refund, -2200, -88, -2112)
    assert refund["product_sku"] == world["seat_sku"], (
        f"the refund must name the seat product, got {refund['product_sku']!r}"
    )
    assert refund["source_ref"] == f"seat:{world['assignment_id']}", (
        f"the refund must trace to the released assignment, got {refund['source_ref']!r}"
    )

    after = scenario.get_booking(booking_id, channel_id)
    assert_field_values(
        after, ancillary_gross_cents=0, recognized_ancillary_net_cents=3134
    )
    assert_recognized_net_matches_ledger(after, entries_after)


def test_seat_release_refund_restores_channel_settlement_total(scenario):
    """The settlement identity is restored to the bundle price by the compensating refund.

    Before the release the settlement reads 27523 + 2200 = 29723 with a zero
    commission and, on a provisional total below 30000, a zero incentive.  After
    the refund removes the seat gross the total is exactly the 27523-cent fare
    component again, and the booking is still TICKETED.

    Design: Difficulty/compensating_invariant/seat_release_refund_preserves_ancillary_net_revenue_identity
    """
    world = _settlement_world(scenario)
    booking_id = world["booking_id"]
    channel_id = world["channel_id"]

    before = scenario.get_booking(booking_id, channel_id)
    assert_field_values(
        before,
        fare_component_cents=27523,
        commission_cents=0,
        incentive_credit_cents=0,
        channel_settlement_total_cents=29723,
    )

    scenario.release_seat(world["assignment_id"], channel_id, "PASSENGER_RELEASE")

    after = scenario.get_booking(booking_id, channel_id)
    assert_field_values(
        after,
        booking_status="TICKETED",
        fare_component_cents=27523,
        commission_cents=0,
        incentive_credit_cents=0,
        channel_settlement_total_cents=27523,
    )


def test_seat_release_compensation_is_additive_and_frees_the_seat(scenario):
    """The compensation adds a row rather than editing one, and returns the seat to inventory.

    The booking ends up owning four ledger rows: the original SALE still reads
    2200 / 88 / 2112 untouched.  The assignment is RELEASED with reason
    PASSENGER_RELEASE and the segment reads held 0, sold 0, available 9 == total 9.

    Design: Difficulty/compensating_invariant/seat_release_refund_preserves_ancillary_net_revenue_identity
    """
    world = _settlement_world(scenario)
    channel_id = world["channel_id"]
    assignment_id = world["assignment_id"]

    sale_before = find_one_entry(
        scenario.booking_ledger(world["booking_id"]), entry_type="SALE", category="SEAT"
    )

    released = scenario.release_seat(assignment_id, channel_id, "PASSENGER_RELEASE")
    assert_field_values(
        released, assignment_state="RELEASED", released_reason="PASSENGER_RELEASE"
    )

    entries_after = scenario.booking_ledger(world["booking_id"])
    assert len(entries_after) == 4, (
        "the release must append a fourth row rather than delete the sale, "
        f"found {len(entries_after)} rows"
    )
    sale_after = find_one_entry(entries_after, entry_type="SALE", category="SEAT")
    assert sale_after["id"] == sale_before["id"], "the SALE row must not be replaced"
    assert_entry_amounts(sale_after, 2200, 88, 2112)

    segment = scenario.get_segment(world["segment_id"])
    assert_segment_counts(
        segment, total_seats=9, held_seats=0, sold_seats=0, available_seats=9
    )


def _diversion_world(scenario: Scenario):
    """ECO_LITE on DIRECT_WEB, flight AC400 with a four-seat exit row, three seats held."""
    scenario.set_clock(CLOCK)
    bag = scenario.create_product(factories.checked_bag_product_payload())
    legroom = scenario.create_product(factories.extra_legroom_seat_product_payload())

    family = scenario.create_family(factories.eco_lite_family_payload())
    scenario.add_attribute(family["id"], bag["id"], inclusion="INCLUDED", included_quantity=1)
    scenario.publish_family(family["id"])

    channel = scenario.create_channel(factories.direct_web_channel_payload())
    flight = scenario.create_flight(
        flight_no="AC400",
        origin="JFK",
        destination="SFO",
        scheduled_departure_utc="2026-09-16T14:00:00Z",
    )
    segment = scenario.create_segment(
        flight["id"],
        legroom["id"],
        zone="EXIT_ROW",
        row_start=12,
        row_end=12,
        seat_letters=["A", "B", "C", "D"],
        base_price_cents=2000,
    )
    booking = scenario.create_booking(
        flight["id"], family["id"], channel["id"], record_locator="CONSV1"
    )
    assignments = [
        scenario.assign_seat(booking["id"], channel["id"], segment["id"], 12, letter)
        for letter in ("A", "B", "C")
    ]
    return {
        "channel_id": channel["id"],
        "flight_id": flight["id"],
        "segment_id": segment["id"],
        "booking_id": booking["id"],
        "assignment_ids": [a["id"] for a in assignments],
    }


def test_diversion_waiver_release_restores_segment_seat_conservation(scenario):
    """A DIVERSION waiver scoped to SEAT moves every held unit back to available.

    The segment starts at total 4, held 3, available 1.  The waiver's cascade
    releases all three assignments with reason IROPS_REACCOMMODATION and the
    segment reads held 0, sold 0, available 4 == total 4, still OPEN.

    Design: Difficulty/compensating_invariant/diversion_waiver_seat_release_preserves_segment_seat_conservation
    """
    world = _diversion_world(scenario)

    before = scenario.get_segment(world["segment_id"])
    assert_segment_counts(
        before, total_seats=4, held_seats=3, sold_seats=0, available_seats=1
    )

    scenario.declare_waiver(world["flight_id"], "DIVERSION", 0, ["SEAT"])

    partner = make_channel_partner_headers(world["channel_id"])
    for assignment_id in world["assignment_ids"]:
        assignment = validate_success(scenario.api.get_seat_assignment(assignment_id, partner))
        assert_field_values(
            assignment,
            assignment_state="RELEASED",
            released_reason="IROPS_REACCOMMODATION",
        )

    after = scenario.get_segment(world["segment_id"])
    assert_segment_counts(
        after, total_seats=4, held_seats=0, sold_seats=0, available_seats=4
    )
    assert after["segment_state"] == "OPEN", (
        f"a seat waiver does not close the segment, got {after['segment_state']!r}"
    )


def test_diversion_waiver_release_of_held_seats_posts_no_revenue(scenario):
    """Releasing seats that were only held is purely physical: no ledger row, no credit.

    The booking was never ticketed, so the waiver credits nothing - the waiver
    reports credited_bookings_count 0 and credited_amount_cents 0, the booking
    keeps waiver_applied false with a zero ancillary gross, and its ledger is empty.

    Design: Difficulty/compensating_invariant/diversion_waiver_seat_release_preserves_segment_seat_conservation
    """
    world = _diversion_world(scenario)

    waiver = scenario.declare_waiver(world["flight_id"], "DIVERSION", 0, ["SEAT"])
    assert_field_values(waiver, credited_bookings_count=0, credited_amount_cents=0)

    entries = validate_success(
        scenario.api.list_booking_revenue_entries(world["booking_id"], REVENUE_ACCOUNTANT)
    )
    assert entries == [], (
        f"a held seat was never sold, so no ledger row may exist: {entries}"
    )

    booking = scenario.get_booking(world["booking_id"], world["channel_id"])
    assert_field_values(
        booking,
        booking_status="HELD",
        ancillary_gross_cents=0,
        waiver_applied=False,
    )


def test_diversion_waiver_marks_the_flight_irregular_with_one_active_waiver(scenario):
    """Declaring the diversion drives the flight into IRREGULAR with active_waiver_count 1.

    Design: Difficulty/compensating_invariant/diversion_waiver_seat_release_preserves_segment_seat_conservation
    """
    world = _diversion_world(scenario)

    scenario.declare_waiver(world["flight_id"], "DIVERSION", 0, ["SEAT"])

    flight = validate_success(
        scenario.api.get_flight(world["flight_id"], OPERATIONS_CONTROLLER)
    )
    assert_field_values(flight, irops_state="IRREGULAR", active_waiver_count=1)
