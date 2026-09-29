"""When one request breaks several rules, the lowest priority number answers.

Each case is built so that two or three checks are genuinely violated at once and
then proves both halves: the reported error is the highest-precedence one, and the
lower-precedence violations really were present in the same request.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    MERCHANDISING_ANALYST,
    ApiErrorId,
    Scenario,
    assert_field_values,
    assert_segment_counts,
    factories,
    make_channel_partner_headers,
)

CLOCK = "2026-08-10T09:00:00Z"


def _exhausted_segment_world(scenario: Scenario):
    """A two-seat segment fully held, plus a cancelled booking on the same flight."""
    scenario.set_clock(CLOCK)
    bag = scenario.create_product(factories.checked_bag_product_payload())
    seat = scenario.create_product(factories.standard_seat_product_payload())

    family = scenario.create_family(factories.eco_lite_family_payload())
    scenario.add_attribute(family["id"], bag["id"], inclusion="INCLUDED", included_quantity=1)
    scenario.publish_family(family["id"])

    channel = scenario.create_channel(factories.direct_web_channel_payload())
    flight = scenario.create_flight(flight_no="AB100", origin="JFK", destination="LAX")
    segment = scenario.create_segment(
        flight["id"],
        seat["id"],
        zone="MID",
        row_start=20,
        row_end=20,
        seat_letters=["A", "B"],
        base_price_cents=2000,
    )

    filler = scenario.create_booking(
        flight["id"], family["id"], channel["id"], record_locator="FILL01"
    )
    for letter in ("A", "B"):
        scenario.assign_seat(filler["id"], channel["id"], segment["id"], 20, letter)

    cancelled = scenario.create_booking(
        flight["id"], family["id"], channel["id"], record_locator="CANC01"
    )
    scenario.cancel(cancelled["id"], channel["id"], "passenger abandoned the session")

    return {
        "channel_id": channel["id"],
        "segment_id": segment["id"],
        "cancelled_booking_id": cancelled["id"],
    }


def test_cancelled_booking_beats_exhausted_inventory_and_occupancy(scenario):
    """The booking-state check answers, though capacity and occupancy also fail.

    The segment has no seat left and 20A is already taken, so the capacity and
    occupancy checks are violated too - but they sit lower in the ladder than the
    terminal booking status, so the answer is ERR_BOOKING_STATE_INVALID.

    Design: Difficulty/priority_pair_validation_conflict/booking_state_beats_seat_capacity_on_hold
    """
    world = _exhausted_segment_world(scenario)
    partner = make_channel_partner_headers(world["channel_id"])

    segment_before = scenario.get_segment(world["segment_id"])
    assert_segment_counts(
        segment_before, total_seats=2, held_seats=2, available_seats=0
    )

    response = scenario.api.create_seat_assignment(
        world["cancelled_booking_id"],
        factories.seat_assignment_payload(world["segment_id"], 20, "A"),
        partner,
    )
    validate_error(response, ApiErrorId.BOOKING_STATE_INVALID, 409)


def test_the_refused_hold_changes_nothing(scenario):
    """The cancelled booking gains no assignment and the segment is untouched.

    Design: Difficulty/priority_pair_validation_conflict/booking_state_beats_seat_capacity_on_hold
    """
    world = _exhausted_segment_world(scenario)
    partner = make_channel_partner_headers(world["channel_id"])

    scenario.api.create_seat_assignment(
        world["cancelled_booking_id"],
        factories.seat_assignment_payload(world["segment_id"], 20, "A"),
        partner,
    )

    segment = scenario.get_segment(world["segment_id"])
    assert_segment_counts(
        segment, total_seats=2, held_seats=2, sold_seats=0, available_seats=0
    )

    booking = scenario.get_booking(world["cancelled_booking_id"], world["channel_id"])
    assert booking["booking_status"] == "CANCELLED", (
        f"the booking stays terminal, got {booking['booking_status']!r}"
    )
    assignments = validate_success(
        scenario.api.list_seat_assignments(
            partner, {"booking_id": world["cancelled_booking_id"]}
        )
    )
    assert assignments == [], (
        f"a cancelled booking owns no seat assignment, got {assignments}"
    )


def _stale_disclosure_world(scenario: Scenario):
    """One PATCH stales the disclosure, drifts the publication and breaches the channel."""
    scenario.set_clock(CLOCK)
    bag = scenario.create_product(factories.checked_bag_product_payload())

    family = scenario.create_family(factories.eco_lite_family_payload())
    attribute = scenario.add_attribute(
        family["id"], bag["id"], inclusion="INCLUDED", included_quantity=1
    )
    published = scenario.publish_family(family["id"])

    channel = scenario.create_channel(factories.direct_web_channel_payload())
    publication = scenario.publish_to_channel(
        family["id"], channel["id"], published["version"]
    )

    flight = scenario.create_flight(flight_no="AB200", origin="JFK", destination="LAX")
    booking = scenario.create_booking(
        flight["id"], family["id"], channel["id"], record_locator="STALE1"
    )
    scenario.disclose_and_acknowledge(booking["id"], channel["id"])

    validate_success(
        scenario.api.update_family_attribute(
            attribute["id"], {"override_price_cents": 3000}, MERCHANDISING_ANALYST
        )
    )
    return {
        "channel_id": channel["id"],
        "publication_id": publication["id"],
        "booking_id": booking["id"],
    }


def test_stale_disclosure_beats_the_parity_failures_at_ticketing(scenario):
    """The regulatory safety check answers, not either of the distribution checks.

    The same PATCH left the publication out of parity and the channel breached, yet
    ticketing reports ERR_FEE_DISCLOSURE_STALE.  A STALE disclosure is also outside
    the not-yet-acknowledged set, so the acknowledgement error is wrong as well.

    Design: Difficulty/priority_pair_validation_conflict/disclosure_stale_beats_publication_and_channel_parity
    """
    world = _stale_disclosure_world(scenario)
    partner = make_channel_partner_headers(world["channel_id"])

    response = scenario.api.ticket_booking(world["booking_id"], {}, partner)
    validate_error(response, ApiErrorId.FEE_DISCLOSURE_STALE, 409)


def test_the_lower_priority_parity_violations_really_were_present(scenario):
    """Both losing conditions hold, so the precedence claim is not vacuous.

    The publication is OUT_OF_PARITY and the channel is BREACHED, while the refused
    ticket left the booking HELD with no fare component, no settlement and an empty
    ledger.

    Design: Difficulty/priority_pair_validation_conflict/disclosure_stale_beats_publication_and_channel_parity
    """
    world = _stale_disclosure_world(scenario)
    partner = make_channel_partner_headers(world["channel_id"])

    scenario.api.ticket_booking(world["booking_id"], {}, partner)

    publication = scenario.get_publication(world["publication_id"])
    assert publication["parity_state"] == "OUT_OF_PARITY", (
        f"the publication really had drifted, got {publication['parity_state']!r}"
    )
    channel = scenario.get_channel(world["channel_id"])
    assert channel["content_parity_status"] == "BREACHED", (
        f"the channel really was breached, got {channel['content_parity_status']!r}"
    )

    booking = scenario.get_booking(world["booking_id"], world["channel_id"])
    assert_field_values(
        booking,
        booking_status="HELD",
        disclosure_state="STALE",
        channel_settlement_total_cents=0,
    )
    assert booking["fare_component_cents"] is None, (
        f"the refused ticket pinned no fare component, got {booking['fare_component_cents']!r}"
    )
    assert scenario.booking_ledger(world["booking_id"]) == [], (
        "the refused ticket must have run no allocation"
    )
