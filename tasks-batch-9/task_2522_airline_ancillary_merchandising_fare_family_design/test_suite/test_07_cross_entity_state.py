"""Guards that read a state the acting entity never writes.

In each case the request's own entity is flawless and the refusal - or the later
success - comes from a second entity: the fare family's status, the flight's
irregular-operations state, or a sibling family's parity on the shared channel.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    MERCHANDISING_ANALYST,
    OPERATIONS_CONTROLLER,
    ApiErrorId,
    Scenario,
    assert_entry_amounts,
    assert_field_values,
    factories,
    find_one_entry,
    make_channel_partner_headers,
)

CLOCK = "2026-08-10T09:00:00Z"
LITE_FINGERPRINT = "ECO_LITE|1|BAG_CHECKED_1:INCLUDED:1:3500"


def _suspended_family_world(scenario: Scenario):
    """A sale-ready booking whose family the catalog owner has just suspended.

    The channel does not require parity, so its content parity status cannot be the
    reason a ticket is refused: only the family's own status can be.
    """
    scenario.set_clock(CLOCK)
    bag = scenario.create_product(factories.checked_bag_product_payload())

    family = scenario.create_family(factories.eco_lite_family_payload())
    scenario.add_attribute(family["id"], bag["id"], inclusion="INCLUDED", included_quantity=1)
    published = scenario.publish_family(family["id"])

    channel = scenario.create_channel(
        factories.distribution_channel_payload(
            channel_code="META_NOPARITY",
            channel_type="NDC",
            commission_bp=300,
            markup_bp=200,
            max_ancillary_price_cents=20000,
            supported_categories=["BAGGAGE", "SEAT"],
            parity_required=False,
        )
    )
    publication = scenario.publish_to_channel(
        family["id"], channel["id"], published["version"]
    )

    flight = scenario.create_flight(flight_no="AB600", origin="JFK", destination="LAX")
    booking = scenario.create_booking(
        flight["id"], family["id"], channel["id"], record_locator="SUSPN1"
    )
    scenario.disclose_and_acknowledge(booking["id"], channel["id"])

    scenario.change_family_status(
        family["id"], "SUSPENDED", "competitive repricing under way"
    )
    return {
        "family_id": family["id"],
        "channel_id": channel["id"],
        "publication_id": publication["id"],
        "booking_id": booking["id"],
    }


def test_a_suspended_family_blocks_the_ticket_it_prices(scenario):
    """The booking is perfect; the family behind it is not published any more.

    Suspension is a catalog decision taken on a different entity, and it stops the
    sale without touching the family's priced content.

    Design: Difficulty/cross_entity_state_dependency/ticket_requires_fare_family_published_not_suspended
    """
    world = _suspended_family_world(scenario)

    response = scenario.api.ticket_booking(
        world["booking_id"], {}, make_channel_partner_headers(world["channel_id"])
    )
    validate_error(response, ApiErrorId.FAMILY_NOT_PUBLISHED, 409)

    family = scenario.get_family(world["family_id"])
    assert family["status"] == "SUSPENDED", (
        f"the family really is suspended, got {family['status']!r}"
    )
    assert family["fee_fingerprint"] == LITE_FINGERPRINT, (
        f"a suspension does not reprice anything, got {family['fee_fingerprint']!r}"
    )


def test_a_suspension_leaves_the_booking_and_the_channel_alone(scenario):
    """The disclosure survives, no revenue moves, and the channel stays compliant.

    The publication drifts out of parity because its family is suspended, but the
    channel does not require parity, so its own status is unaffected - which is what
    rules out parity as the cause of the refusal.

    Design: Difficulty/cross_entity_state_dependency/ticket_requires_fare_family_published_not_suspended
    """
    world = _suspended_family_world(scenario)
    scenario.api.ticket_booking(
        world["booking_id"], {}, make_channel_partner_headers(world["channel_id"])
    )

    booking = scenario.get_booking(world["booking_id"], world["channel_id"])
    assert_field_values(booking, booking_status="HELD", disclosure_state="ACKNOWLEDGED")
    assert booking["fare_component_cents"] is None, (
        f"no fare was pinned, got {booking['fare_component_cents']!r}"
    )
    assert scenario.booking_ledger(world["booking_id"]) == [], (
        "a refused ticket posts no revenue"
    )

    publication = scenario.get_publication(world["publication_id"])
    assert_field_values(
        publication, parity_state="OUT_OF_PARITY", drift_reason="FAMILY_SUSPENDED"
    )
    channel = scenario.get_channel(world["channel_id"])
    assert channel["content_parity_status"] == "COMPLIANT", (
        "a channel that does not require parity stays compliant, got "
        f"{channel['content_parity_status']!r}"
    )


def _irops_blocked_world(scenario: Scenario):
    """A sale-ready booking on a flight that has just been diverted.

    The waiver covers SEAT only and the booking has no seat sale, so nothing is
    credited: the only effect on the sale is the flight's irregular state.
    """
    scenario.set_clock(CLOCK)
    bag = scenario.create_product(factories.checked_bag_product_payload())

    family = scenario.create_family(factories.eco_lite_family_payload())
    scenario.add_attribute(family["id"], bag["id"], inclusion="INCLUDED", included_quantity=1)
    published = scenario.publish_family(family["id"])

    channel = scenario.create_channel(factories.direct_web_channel_payload())
    scenario.publish_to_channel(family["id"], channel["id"], published["version"])

    flight = scenario.create_flight(flight_no="AB700", origin="JFK", destination="LAX")
    booking = scenario.create_booking(
        flight["id"], family["id"], channel["id"], record_locator="IROPS1"
    )
    scenario.disclose_and_acknowledge(booking["id"], channel["id"])

    waiver = scenario.declare_waiver(flight["id"], "DIVERSION", 0, ["SEAT"])
    return {
        "flight_id": flight["id"],
        "channel_id": channel["id"],
        "booking_id": booking["id"],
        "waiver_id": waiver["id"],
    }


def test_an_irregular_flight_blocks_the_sale_and_credits_nothing(scenario):
    """The blocker lives on the flight, in a dimension the booking never writes.

    The diversion waiver scoped to seats finds no seat sale to credit, so it moves no
    money - it simply stops the sale.

    Design: Difficulty/cross_entity_state_dependency/ticket_blocked_while_flight_irops_irregular_then_allowed_after_rescind
    """
    world = _irops_blocked_world(scenario)

    response = scenario.api.ticket_booking(
        world["booking_id"], {}, make_channel_partner_headers(world["channel_id"])
    )
    validate_error(response, ApiErrorId.IROPS_SALES_BLOCKED, 409)

    booking = scenario.get_booking(world["booking_id"], world["channel_id"])
    assert booking["booking_status"] == "HELD", (
        f"the refused ticket leaves the booking held, got {booking['booking_status']!r}"
    )
    assert scenario.booking_ledger(world["booking_id"]) == [], (
        "a blocked sale posts no revenue"
    )

    waiver = validate_success(
        scenario.api.get_irops_waiver(world["waiver_id"], OPERATIONS_CONTROLLER)
    )
    assert_field_values(waiver, credited_bookings_count=0, credited_amount_cents=0)


def test_rescinding_the_waiver_lets_the_same_ticket_through(scenario):
    """Recovery is not a return to normal, and the guard reads "not irregular".

    After the rescind the flight is RECOVERED rather than NORMAL, and the identical
    ticket request now succeeds and allocates the bundle.

    Design: Difficulty/cross_entity_state_dependency/ticket_blocked_while_flight_irops_irregular_then_allowed_after_rescind
    """
    world = _irops_blocked_world(scenario)
    partner = make_channel_partner_headers(world["channel_id"])

    validate_error(
        scenario.api.ticket_booking(world["booking_id"], {}, partner),
        ApiErrorId.IROPS_SALES_BLOCKED,
        409,
    )

    scenario.rescind_waiver(
        world["waiver_id"], "diversion cancelled, flight operating normally"
    )
    flight = validate_success(
        scenario.api.get_flight(world["flight_id"], OPERATIONS_CONTROLLER)
    )
    assert_field_values(flight, irops_state="RECOVERED", active_waiver_count=0)

    ticketed = validate_success(scenario.api.ticket_booking(world["booking_id"], {}, partner))
    assert_field_values(
        ticketed,
        booking_status="TICKETED",
        fare_component_cents=14000,
        channel_settlement_total_cents=14000,
        commission_cents=0,
        incentive_credit_cents=0,
    )

    entries = scenario.booking_ledger(world["booking_id"])
    allocations = [e for e in entries if e["entry_type"] == "ALLOCATION"]
    assert len(allocations) == 2, (
        f"the bundle splits into a bag bucket and a transport bucket, got {allocations}"
    )
    assert_entry_amounts(
        find_one_entry(entries, entry_type="ALLOCATION", category="BAGGAGE"), 3161, 126, 3035
    )
    assert_entry_amounts(
        find_one_entry(entries, entry_type="ALLOCATION", category="AIR_TRANSPORT"),
        10839,
        813,
        10026,
    )


def _sideways_parity_world(scenario: Scenario):
    """Two families on one channel: the offer sits on the second, the drift on the first.

    Re-pricing PAR_ONE's bag attribute breaches the shared channel, even though the
    booking, its family PAR_TWO and the offer itself are untouched.
    """
    scenario.set_clock(CLOCK)
    bag = scenario.create_product(factories.checked_bag_product_payload())
    seat = scenario.create_product(factories.standard_seat_product_payload())
    boarding = scenario.create_product(factories.priority_boarding_product_payload())

    one = scenario.create_family(
        factories.fare_family_payload(
            code="PAR_ONE",
            name="Parity One",
            cabin_class="ECONOMY",
            base_fare_cents=12000,
            bundle_price_cents=14000,
            refundability="NON_REFUNDABLE",
            change_fee_cents=7500,
            boarding_priority_tier=4,
        )
    )
    one_bag = scenario.add_attribute(
        one["id"], bag["id"], inclusion="INCLUDED", included_quantity=1
    )
    one_published = scenario.publish_family(one["id"])

    two = scenario.create_family(
        factories.fare_family_payload(
            code="PAR_TWO",
            name="Parity Two",
            cabin_class="ECONOMY",
            base_fare_cents=12000,
            bundle_price_cents=13000,
            refundability="NON_REFUNDABLE",
            change_fee_cents=7500,
            boarding_priority_tier=4,
        )
    )
    scenario.add_attribute(two["id"], seat["id"], inclusion="INCLUDED", included_quantity=1)
    two_published = scenario.publish_family(two["id"])

    channel = scenario.create_channel(
        factories.distribution_channel_payload(
            channel_code="OTA_SKYDEAL",
            channel_type="OTA",
            commission_bp=900,
            markup_bp=500,
            max_ancillary_price_cents=6000,
            supported_categories=["BAGGAGE", "SEAT", "BOARDING", "ONBOARD"],
            parity_required=True,
        )
    )
    pub_one = scenario.publish_to_channel(
        one["id"], channel["id"], one_published["version"]
    )
    pub_two = scenario.publish_to_channel(
        two["id"], channel["id"], two_published["version"]
    )

    flight = scenario.create_flight(flight_no="AB800", origin="JFK", destination="LAX")
    scenario.post_demand(flight["id"], 75, 1200)
    booking = scenario.create_booking(
        flight["id"], two["id"], channel["id"], record_locator="PARIT1"
    )
    scenario.open_offer_session(
        booking["id"], channel["id"], "BOOKING", [boarding["id"]]
    )
    presented = scenario.offers_for_booking(
        booking["id"], channel["id"], offer_status="PRESENTED"
    )
    assert len(presented) == 1, f"one boarding offer is on the table, got {presented}"

    validate_success(
        scenario.api.update_family_attribute(
            one_bag["id"], {"override_price_cents": 3000}, MERCHANDISING_ANALYST
        )
    )
    current = scenario.get_booking(booking["id"], channel["id"])
    return {
        "channel_id": channel["id"],
        "booking_id": booking["id"],
        "booking_version": current["version"],
        "offer_id": presented[0]["id"],
        "pub_one_id": pub_one["id"],
        "pub_two_id": pub_two["id"],
    }


def test_a_sibling_familys_drift_blocks_the_acceptance(scenario):
    """The guard reaches sideways through the channel, and the offer survives intact.

    The supplied booking version is current and 1445 is far under the channel's 6000
    ceiling, so neither the version check nor the price cap can be the reason.

    Design: Difficulty/cross_entity_state_dependency/offer_accept_requires_channel_parity_compliant_across_families
    """
    world = _sideways_parity_world(scenario)
    partner = make_channel_partner_headers(world["channel_id"])

    response = scenario.api.accept_offer(
        world["offer_id"],
        factories.offer_accept_payload(world["booking_version"]),
        partner,
    )
    validate_error(response, ApiErrorId.CHANNEL_CONTENT_PARITY_BREACH, 409)

    offer = validate_success(
        scenario.api.get_ancillary_offer(world["offer_id"], partner)
    )
    assert_field_values(
        offer,
        offer_status="PRESENTED",
        offered_price_cents=1445,
        expected_value_cents=1591,
    )
    assert offer["accepted_price_cents"] is None, (
        f"a refused acceptance freezes no price, got {offer['accepted_price_cents']!r}"
    )


def test_only_the_repriced_familys_publication_drifts(scenario):
    """One publication drifts, the other does not, and the channel carries the breach.

    The booking's own family stays in parity throughout, and the refused acceptance
    leaves the ledger and the booking's gross at zero.

    Design: Difficulty/cross_entity_state_dependency/offer_accept_requires_channel_parity_compliant_across_families
    """
    world = _sideways_parity_world(scenario)
    partner = make_channel_partner_headers(world["channel_id"])

    scenario.api.accept_offer(
        world["offer_id"],
        factories.offer_accept_payload(world["booking_version"]),
        partner,
    )

    pub_one = scenario.get_publication(world["pub_one_id"])
    assert_field_values(
        pub_one, parity_state="OUT_OF_PARITY", drift_reason="ATTRIBUTE_REPRICED"
    )
    pub_two = scenario.get_publication(world["pub_two_id"])
    assert pub_two["parity_state"] == "IN_PARITY", (
        "the booking's own family never drifted, got "
        f"{pub_two['parity_state']!r}"
    )

    channel = scenario.get_channel(world["channel_id"])
    assert_field_values(
        channel, content_parity_status="BREACHED", parity_breach_count=1
    )

    booking = scenario.get_booking(world["booking_id"], world["channel_id"])
    assert booking["ancillary_gross_cents"] == 0, (
        f"no ancillary was sold, got {booking['ancillary_gross_cents']}"
    )
    assert scenario.booking_ledger(world["booking_id"]) == [], (
        "a refused acceptance posts no revenue"
    )
