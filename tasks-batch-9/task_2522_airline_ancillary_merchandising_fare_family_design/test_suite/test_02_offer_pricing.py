"""Offer pricing: variant selection and the ordered multiplier chain.

Which pricing variant applies is decided by physical seat inventory, not by the
demand feed: a seat product with an OPEN segment on the flight is priced from
residual scarcity, one without is priced from willingness to pay.  The offered
price itself is a chain of rounded multiplications in a pinned order, clamped to
the product's own floor and cap after the last of them.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    Scenario,
    assert_field_values,
    assert_instants,
    assert_segment_counts,
    factories,
    make_channel_partner_headers,
)

CLOCK = "2026-08-10T09:00:00Z"


def _variant_world(scenario: Scenario):
    """Two flights with an identical demand feed; only the second has a seat segment."""
    scenario.set_clock(CLOCK)
    bag = scenario.create_product(factories.checked_bag_product_payload())
    legroom = scenario.create_product(factories.extra_legroom_seat_product_payload())

    family = scenario.create_family(factories.eco_lite_family_payload())
    scenario.add_attribute(family["id"], bag["id"], inclusion="INCLUDED", included_quantity=1)
    scenario.publish_family(family["id"])

    channel = scenario.create_channel(factories.direct_web_channel_payload())
    flight_a = scenario.create_flight(flight_no="AA200", origin="JFK", destination="LAX")
    flight_b = scenario.create_flight(
        flight_no="AA300",
        origin="JFK",
        destination="SFO",
        scheduled_departure_utc="2026-09-16T14:00:00Z",
    )
    segment_b = scenario.create_segment(
        flight_b["id"],
        legroom["id"],
        zone="EXIT_ROW",
        row_start=12,
        row_end=12,
        seat_letters=["A", "B", "C", "D"],
        base_price_cents=2000,
    )
    scenario.advance_phase(flight_a["id"], "CHECKIN_OPEN")
    scenario.advance_phase(flight_b["id"], "CHECKIN_OPEN")
    scenario.post_demand(flight_a["id"], 75, 1200)
    scenario.post_demand(flight_b["id"], 75, 1200)

    holder = scenario.create_booking(
        flight_b["id"], family["id"], channel["id"], record_locator="BHOLD1"
    )
    for letter in ("A", "B", "C"):
        scenario.assign_seat(holder["id"], channel["id"], segment_b["id"], 12, letter)

    booking_a = scenario.create_booking(
        flight_a["id"], family["id"], channel["id"], record_locator="OFFRA1"
    )
    booking_b = scenario.create_booking(
        flight_b["id"], family["id"], channel["id"], record_locator="OFFRB1"
    )
    return {
        "channel_id": channel["id"],
        "legroom_id": legroom["id"],
        "segment_b_id": segment_b["id"],
        "booking_a_id": booking_a["id"],
        "booking_b_id": booking_b["id"],
    }


def _single_offer(scenario: Scenario, session, channel_id):
    assert session["candidate_count"] == 1, (
        f"exactly one product was requested, got candidate_count {session['candidate_count']}"
    )
    assert session["suppression_reason"] == "", (
        f"a priced candidate leaves no suppression reason, got {session['suppression_reason']!r}"
    )
    assert len(session["presented_offer_ids"]) == 1, (
        f"expected one presented offer, got {session['presented_offer_ids']}"
    )
    return validate_success(
        scenario.api.get_ancillary_offer(
            session["presented_offer_ids"][0], make_channel_partner_headers(channel_id)
        )
    )


def test_seat_without_an_open_segment_is_priced_from_willingness_to_pay(scenario):
    """With no seat segment on the flight the offer reads the demand feed.

    A load factor of 75 and a demand index of 1200bp give a score of 11007bp, which
    prices the 4200-cent seat at 5085 with an expected value of 5597.

    Design: Difficulty/dual_variant_calc/offer_price_wtp_elastic_vs_residual_inventory
    """
    world = _variant_world(scenario)

    session = scenario.open_offer_session(
        world["booking_a_id"], world["channel_id"], "CHECKIN", [world["legroom_id"]]
    )
    offer = _single_offer(scenario, session, world["channel_id"])

    assert_field_values(
        offer,
        pricing_variant="WTP_ELASTIC",
        wtp_score_bp=11007,
        offered_price_cents=5085,
        expected_value_cents=5597,
        sequence_rank=1,
    )
    # The window opens at the clock and runs exactly one hour.
    assert_instants(offer, valid_from=CLOCK, valid_until="2026-08-10T10:00:00Z")


def test_seat_with_an_open_segment_is_priced_from_residual_scarcity(scenario):
    """An OPEN segment for the seat product switches the offer onto physical scarcity.

    Three of the four exit-row seats are held, so the segment is 75% sold and the
    score is 11500bp - reached without consulting the demand feed - pricing the seat
    at 5313 with an expected value of 6110.

    Design: Difficulty/dual_variant_calc/offer_price_wtp_elastic_vs_residual_inventory
    """
    world = _variant_world(scenario)

    segment = scenario.get_segment(world["segment_b_id"])
    assert_segment_counts(segment, total_seats=4, held_seats=3, available_seats=1)

    session = scenario.open_offer_session(
        world["booking_b_id"], world["channel_id"], "CHECKIN", [world["legroom_id"]]
    )
    offer = _single_offer(scenario, session, world["channel_id"])

    assert_field_values(
        offer,
        pricing_variant="RESIDUAL_INVENTORY",
        wtp_score_bp=11500,
        offered_price_cents=5313,
        expected_value_cents=6110,
        sequence_rank=1,
    )


def test_the_two_variants_diverge_on_identical_demand_feeds(scenario):
    """The 228-cent gap is attributable to the variant alone.

    Both flights report a load factor of 75 and a demand index of 1200bp, so nothing
    but segment existence separates the 5085-cent elastic price from the 5313-cent
    residual one.

    Design: Difficulty/dual_variant_calc/offer_price_wtp_elastic_vs_residual_inventory
    """
    world = _variant_world(scenario)

    elastic = _single_offer(
        scenario,
        scenario.open_offer_session(
            world["booking_a_id"], world["channel_id"], "CHECKIN", [world["legroom_id"]]
        ),
        world["channel_id"],
    )
    residual = _single_offer(
        scenario,
        scenario.open_offer_session(
            world["booking_b_id"], world["channel_id"], "CHECKIN", [world["legroom_id"]]
        ),
        world["channel_id"],
    )

    assert residual["offered_price_cents"] - elastic["offered_price_cents"] == 228, (
        "the variant alone must account for a 228-cent gap, got "
        f"{residual['offered_price_cents']} against {elastic['offered_price_cents']}"
    )
    assert elastic["pricing_variant"] != residual["pricing_variant"], (
        "the two flights must not resolve to the same pricing variant"
    )


def _clamp_world(scenario: Scenario):
    """A 7500-cent change product offered INFLIGHT through a 2000bp-markup GDS channel."""
    scenario.set_clock(CLOCK)
    bag = scenario.create_product(factories.checked_bag_product_payload())
    change = scenario.create_product(
        factories.change_flex_product_payload(
            tax_treatment="TAXABLE_SERVICE", revenue_class="NON_AIR"
        )
    )
    family = scenario.create_family(factories.eco_lite_family_payload())
    scenario.add_attribute(family["id"], bag["id"], inclusion="INCLUDED", included_quantity=1)
    scenario.publish_family(family["id"])

    channel = scenario.create_channel(
        factories.distribution_channel_payload(
            channel_code="GDS_PREMIUM",
            channel_type="GDS",
            commission_bp=1200,
            markup_bp=2000,
            max_ancillary_price_cents=20000,
            supported_categories=["BAGGAGE", "SEAT", "CHANGE", "BOARDING", "ONBOARD"],
            parity_required=True,
        )
    )
    flight = scenario.create_flight(flight_no="AA400", origin="JFK", destination="LAX")
    scenario.post_demand(flight["id"], 100, 5000)
    booking = scenario.create_booking(
        flight["id"], family["id"], channel["id"], record_locator="CLAMP1"
    )
    scenario.advance_phase(flight["id"], "CHECKIN_OPEN")
    scenario.advance_phase(flight["id"], "BOARDING")
    return {
        "channel_id": channel["id"],
        "change_id": change["id"],
        "booking_id": booking["id"],
    }


def test_offered_price_is_clamped_to_the_product_cap_after_the_chain(scenario):
    """The three multipliers run in order and the result is then clamped down to the cap.

    7500 at a 12030bp score gives 9023, the INFLIGHT touchpoint lifts it to 11279 and
    the 2000bp markup to 13535, which exceeds the 13500-cent cap of 18000bp of list
    and is clamped to it.  Folding the multipliers into a single product would land on
    13534 instead.

    Design: Difficulty/combinatorial_formula/offer_price_nonlinear_clamp_chain
    """
    world = _clamp_world(scenario)

    session = scenario.open_offer_session(
        world["booking_id"], world["channel_id"], "INFLIGHT", [world["change_id"]]
    )
    offer = _single_offer(scenario, session, world["channel_id"])

    assert_field_values(
        offer, pricing_variant="WTP_ELASTIC", wtp_score_bp=12030, touchpoint="INFLIGHT",
        sequence_rank=1,
    )
    assert offer["offered_price_cents"] == 13500, (
        "the chain reaches 13535 and is clamped to the 13500-cent cap; 13534 would mean "
        f"the multipliers were folded together, got {offer['offered_price_cents']}"
    )


def test_expected_value_is_computed_from_the_clamped_price(scenario):
    """The expected value follows the clamp rather than the pre-clamp figure.

    13500 at 12030bp gives 16241; deriving it from the pre-clamp 13535 would give
    16242.  The channel's own 20000-cent ceiling plays no part at pricing time.

    Design: Difficulty/combinatorial_formula/offer_price_nonlinear_clamp_chain
    """
    world = _clamp_world(scenario)

    session = scenario.open_offer_session(
        world["booking_id"], world["channel_id"], "INFLIGHT", [world["change_id"]]
    )
    offer = _single_offer(scenario, session, world["channel_id"])

    assert offer["expected_value_cents"] == 16241, (
        "the expected value must be derived from the clamped 13500; 16242 would betray "
        f"the pre-clamp 13535, got {offer['expected_value_cents']}"
    )
