"""Edges where one unit decides the answer.

Each case walks the value from just below the edge to exactly on it, so a
strictly-greater-than reading of an at-or-above threshold - or the reverse - shows
up as a different number rather than as a vague failure.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    MERCHANDISING_ANALYST,
    OPERATIONS_CONTROLLER,
    ApiErrorId,
    Scenario,
    assert_field_values,
    assert_instants,
    assert_segment_counts,
    factories,
    make_channel_partner_headers,
)

CLOCK = "2026-08-10T09:00:00Z"


def _demand_tier_world(scenario: Scenario):
    """One MID segment starting at row 16, whose row band adjustment is exactly 0.

    With the row band contributing nothing, the demand multiplier is the only
    moving part of the effective price.
    """
    scenario.set_clock(CLOCK)
    seat = scenario.create_product(factories.standard_seat_product_payload())
    flight = scenario.create_flight(flight_no="AB300", origin="JFK", destination="LAX")
    segment = scenario.create_segment(
        flight["id"],
        seat["id"],
        zone="MID",
        row_start=16,
        row_end=18,
        seat_letters=["A", "B", "C"],
        base_price_cents=2000,
    )
    return {"flight_id": flight["id"], "segment_id": segment["id"]}


def _flight(scenario: Scenario, flight_id: str):
    return validate_success(scenario.api.get_flight(flight_id, OPERATIONS_CONTROLLER))


def test_the_mid_demand_tier_starts_at_exactly_sixty_percent(scenario):
    """59 percent is still LOW, 60 percent is already MID.

    The threshold is at-or-above, so the segment reprices from 2000 to 2200 the
    moment the load factor reaches 60 - not one point later.

    Design: Difficulty/boundary_precision_check/demand_tier_thresholds_at_59_60_79_and_80_pct
    """
    world = _demand_tier_world(scenario)

    scenario.post_demand(world["flight_id"], 59, 0)
    assert _flight(scenario, world["flight_id"])["demand_tier"] == "LOW", (
        "59 percent sits below the MID threshold"
    )
    low = scenario.get_segment(world["segment_id"])
    assert low["effective_price_cents"] == 2000, (
        f"a LOW tier leaves the base price alone, got {low['effective_price_cents']}"
    )

    scenario.post_demand(world["flight_id"], 60, 0)
    assert _flight(scenario, world["flight_id"])["demand_tier"] == "MID", (
        "60 percent is at the MID threshold, which is inclusive"
    )
    mid = scenario.get_segment(world["segment_id"])
    assert mid["effective_price_cents"] == 2200, (
        f"a MID tier lifts 2000 to 2200, got {mid['effective_price_cents']}"
    )


def test_the_high_demand_tier_starts_at_exactly_eighty_percent(scenario):
    """79 percent is still MID, 80 percent is already HIGH, and inventory never moves.

    Design: Difficulty/boundary_precision_check/demand_tier_thresholds_at_59_60_79_and_80_pct
    """
    world = _demand_tier_world(scenario)

    scenario.post_demand(world["flight_id"], 79, 0)
    assert _flight(scenario, world["flight_id"])["demand_tier"] == "MID", (
        "79 percent is inside the MID band"
    )
    inside = scenario.get_segment(world["segment_id"])
    assert inside["effective_price_cents"] == 2200, (
        f"the price is unchanged inside the band, got {inside['effective_price_cents']}"
    )
    assert_segment_counts(inside, total_seats=9, held_seats=0, sold_seats=0, available_seats=9)

    scenario.post_demand(world["flight_id"], 80, 0)
    assert _flight(scenario, world["flight_id"])["demand_tier"] == "HIGH", (
        "80 percent is at the HIGH threshold, which is inclusive"
    )
    high = scenario.get_segment(world["segment_id"])
    assert high["effective_price_cents"] == 2500, (
        f"a HIGH tier lifts 2000 to 2500, got {high['effective_price_cents']}"
    )
    assert_segment_counts(high, total_seats=9, held_seats=0, sold_seats=0, available_seats=9)


def _empty_pool_world(scenario: Scenario):
    """A channel that supports only the one category the family already bundles.

    OTA_BAGONLY sells BAGGAGE and nothing else, and ECO_LITE already includes the
    only BAGGAGE product, so the eligibility filter has nothing left to offer.
    """
    scenario.set_clock(CLOCK)
    bag = scenario.create_product(factories.checked_bag_product_payload())
    scenario.create_product(factories.priority_boarding_product_payload())

    family = scenario.create_family(factories.eco_lite_family_payload())
    scenario.add_attribute(family["id"], bag["id"], inclusion="INCLUDED", included_quantity=1)
    scenario.publish_family(family["id"])

    channel = scenario.create_channel(
        factories.distribution_channel_payload(
            channel_code="OTA_BAGONLY",
            channel_type="OTA",
            commission_bp=900,
            markup_bp=0,
            max_ancillary_price_cents=6000,
            supported_categories=["BAGGAGE"],
            parity_required=True,
        )
    )
    flight = scenario.create_flight(flight_no="AB400", origin="JFK", destination="LAX")
    scenario.post_demand(flight["id"], 75, 1200)
    booking = scenario.create_booking(
        flight["id"], family["id"], channel["id"], record_locator="EMPTY1"
    )
    return {
        "channel_id": channel["id"],
        "booking_id": booking["id"],
        "booking_version": booking["version"],
    }


def test_an_empty_candidate_pool_still_opens_a_session(scenario):
    """No eligible product is a successful session with nothing in it, not an error.

    The session answers 201 with an empty offer list and names the reason, echoing
    the touchpoint it was opened for.

    Design: Difficulty/boundary_precision_check/offer_session_empty_candidate_pool_returns_empty_list
    """
    world = _empty_pool_world(scenario)

    session = validate_success(
        scenario.api.create_offer_session(
            world["booking_id"],
            factories.offer_session_payload("BOOKING"),
            make_channel_partner_headers(world["channel_id"]),
        ),
        201,
    )
    assert_field_values(
        session,
        candidate_count=0,
        presented_offer_ids=[],
        suppression_reason="NO_ELIGIBLE_CANDIDATES",
        touchpoint="BOOKING",
    )


def test_an_empty_session_writes_neither_an_offer_nor_the_booking(scenario):
    """No offer row is created and the booking is untouched, version included.

    Design: Difficulty/boundary_precision_check/offer_session_empty_candidate_pool_returns_empty_list
    """
    world = _empty_pool_world(scenario)

    validate_success(
        scenario.api.create_offer_session(
            world["booking_id"],
            factories.offer_session_payload("BOOKING"),
            make_channel_partner_headers(world["channel_id"]),
        ),
        201,
    )

    offers = scenario.offers_for_booking(world["booking_id"], world["channel_id"])
    assert offers == [], f"an empty pool creates no offer, got {offers}"

    booking = scenario.get_booking(world["booking_id"], world["channel_id"])
    assert booking["booking_status"] == "HELD", (
        f"the booking is untouched, got {booking['booking_status']!r}"
    )
    assert booking["version"] == world["booking_version"], (
        "an empty session is not a booking write, so the version must stand still: "
        f"{booking['version']} != {world['booking_version']}"
    )


def _bundle_floor_pair(scenario: Scenario):
    """Two identical DRAFT families whose bundle prices straddle the a-la-carte total.

    Base fare 10000 plus one 3500 bag gives an a-la-carte total of 13500 for both.
    EDGE_EQ asks exactly 13500; EDGE_OVER asks one cent more.
    """
    scenario.set_clock(CLOCK)
    bag = scenario.create_product(factories.checked_bag_product_payload())

    equal = scenario.create_family(
        factories.fare_family_payload(
            code="EDGE_EQ",
            name="Edge Equal",
            cabin_class="ECONOMY",
            base_fare_cents=10000,
            bundle_price_cents=13500,
            refundability="NON_REFUNDABLE",
            change_fee_cents=5000,
            boarding_priority_tier=4,
        )
    )
    scenario.add_attribute(equal["id"], bag["id"], inclusion="INCLUDED", included_quantity=1)

    over = scenario.create_family(
        factories.fare_family_payload(
            code="EDGE_OVER",
            name="Edge Over",
            cabin_class="ECONOMY",
            base_fare_cents=10000,
            bundle_price_cents=13501,
            refundability="NON_REFUNDABLE",
            change_fee_cents=5000,
            boarding_priority_tier=4,
        )
    )
    scenario.add_attribute(over["id"], bag["id"], inclusion="INCLUDED", included_quantity=1)

    return {"equal_id": equal["id"], "over_id": over["id"]}


def test_a_bundle_priced_exactly_at_the_a_la_carte_total_submits(scenario):
    """13500 against a 13500 total is legal: the ceiling includes its own value.

    The family reaches review with a zero discount, which is the whole point of the
    at-or-below reading.

    Design: Difficulty/boundary_precision_check/bundle_price_equal_vs_one_cent_over_a_la_carte_total
    """
    pair = _bundle_floor_pair(scenario)

    submitted = scenario.submit_family(pair["equal_id"])
    assert_field_values(
        submitted,
        status="IN_REVIEW",
        a_la_carte_total_cents=13500,
        unbundled_value_cents=3500,
        bundle_discount_bp=0,
        fee_fingerprint="EDGE_EQ|1|BAG_CHECKED_1:INCLUDED:1:3500",
    )


def test_a_bundle_one_cent_over_the_a_la_carte_total_is_refused(scenario):
    """13501 against the same 13500 total breaches the floor and stays in draft.

    Design: Difficulty/boundary_precision_check/bundle_price_equal_vs_one_cent_over_a_la_carte_total
    """
    pair = _bundle_floor_pair(scenario)

    response = scenario.api.submit_fare_family(pair["over_id"], {}, MERCHANDISING_ANALYST)
    validate_error(response, ApiErrorId.BUNDLE_DISCOUNT_FLOOR_BREACH, 422)

    family = scenario.get_family(pair["over_id"])
    assert_field_values(family, status="DRAFT", revision_no=1)


def _cooloff_world(scenario: Scenario):
    """A seat offer declined at 09:10, which anchors the cool-off barrier at 09:40.

    SEAT_STANDARD is not bundled into ECO_LITE and no seat segment exists for it, so
    the offer is priced on the willingness-to-pay path.
    """
    scenario.set_clock(CLOCK)
    bag = scenario.create_product(factories.checked_bag_product_payload())
    seat = scenario.create_product(factories.standard_seat_product_payload())

    family = scenario.create_family(factories.eco_lite_family_payload())
    scenario.add_attribute(family["id"], bag["id"], inclusion="INCLUDED", included_quantity=1)
    scenario.publish_family(family["id"])

    channel = scenario.create_channel(factories.direct_web_channel_payload())
    flight = scenario.create_flight(flight_no="AB500", origin="JFK", destination="LAX")
    scenario.post_demand(flight["id"], 75, 1200)
    booking = scenario.create_booking(
        flight["id"], family["id"], channel["id"], record_locator="COOLF1"
    )

    scenario.open_offer_session(
        booking["id"], channel["id"], "BOOKING", [seat["id"]]
    )
    presented = scenario.offers_for_booking(
        booking["id"], channel["id"], offer_status="PRESENTED"
    )
    assert len(presented) == 1, f"the seat offer must be on the table, got {presented}"

    scenario.set_clock("2026-08-10T09:10:00Z")
    scenario.decline_offer(presented[0]["id"], channel["id"])

    return {
        "channel_id": channel["id"],
        "booking_id": booking["id"],
        "seat_id": seat["id"],
        "declined_offer_id": presented[0]["id"],
    }


def _cooloff_session(scenario: Scenario, world):
    return scenario.api.create_offer_session(
        world["booking_id"],
        factories.offer_session_payload("BOOKING", [world["seat_id"]]),
        make_channel_partner_headers(world["channel_id"]),
    )


def test_a_re_offer_one_minute_before_the_barrier_is_refused(scenario):
    """The cool-off still bites at 09:39, one minute short of the thirty-minute mark.

    The declined offer anchors the window at 09:10, so 09:10 plus thirty minutes is
    strictly later than 09:39 and the session is refused without creating a row.

    Design: Difficulty/boundary_precision_check/offer_cooloff_boundary_at_exact_thirty_minutes
    """
    world = _cooloff_world(scenario)
    scenario.set_clock("2026-08-10T09:39:00Z")

    validate_error(
        _cooloff_session(scenario, world), ApiErrorId.OFFER_COOLOFF_CONFLICT, 409
    )

    offers = scenario.offers_for_booking(world["booking_id"], world["channel_id"])
    assert len(offers) == 1, f"the refused session created no offer, got {offers}"
    declined = validate_success(
        scenario.api.get_ancillary_offer(
            world["declined_offer_id"], make_channel_partner_headers(world["channel_id"])
        )
    )
    assert declined["offer_status"] == "DECLINED", (
        f"the anchor offer stays declined, got {declined['offer_status']!r}"
    )
    assert declined["updated_at"].startswith("2026-08-10T09:10:00"), (
        f"the decline stamped the logical clock, got {declined['updated_at']!r}"
    )


def test_a_re_offer_at_exactly_thirty_minutes_succeeds(scenario):
    """At 09:40 the barrier is behind us, because it must be strictly later than now.

    The seat comes back on the table at the same willingness-to-pay price, with a
    fresh one-hour window, and the booking now owns both offers.

    Design: Difficulty/boundary_precision_check/offer_cooloff_boundary_at_exact_thirty_minutes
    """
    world = _cooloff_world(scenario)
    partner = make_channel_partner_headers(world["channel_id"])

    scenario.set_clock("2026-08-10T09:39:00Z")
    validate_error(
        _cooloff_session(scenario, world), ApiErrorId.OFFER_COOLOFF_CONFLICT, 409
    )

    scenario.set_clock("2026-08-10T09:40:00Z")
    session = validate_success(_cooloff_session(scenario, world), 201)
    assert session["candidate_count"] == 1, (
        f"the seat is eligible again, got candidate_count {session['candidate_count']}"
    )
    assert len(session["presented_offer_ids"]) == 1, (
        f"exactly one offer is presented, got {session['presented_offer_ids']}"
    )

    offer = validate_success(
        scenario.api.get_ancillary_offer(session["presented_offer_ids"][0], partner)
    )
    assert_field_values(
        offer,
        pricing_variant="WTP_ELASTIC",
        wtp_score_bp=11007,
        offered_price_cents=2091,
        expected_value_cents=2302,
    )
    # A fresh one-hour window opening at the clock the session ran at.
    assert_instants(
        offer,
        valid_from="2026-08-10T09:40:00Z",
        valid_until="2026-08-10T10:40:00Z",
    )

    offers = scenario.offers_for_booking(world["booking_id"], world["channel_id"])
    assert len(offers) == 2, (
        f"the declined offer and the new one both survive, got {len(offers)}"
    )
    assert sorted(o["offer_status"] for o in offers) == ["DECLINED", "PRESENTED"], (
        f"one declined, one presented, got {[o['offer_status'] for o in offers]}"
    )
