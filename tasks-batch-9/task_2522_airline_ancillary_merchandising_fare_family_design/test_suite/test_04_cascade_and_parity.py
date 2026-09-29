"""Single writes whose consequences travel several entities deep.

Re-pricing one attribute of a published family drifts its publications, breaches
the channel that required parity, stales the acknowledged disclosure and supersedes
the presented offer - four levels from one PATCH.  Declaring an irregular-operations
waiver credits the sold ancillary, moves the waived-change-fee counter, and through
that counter changes the quote a later change-open produces.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    MERCHANDISING_ANALYST,
    OPERATIONS_CONTROLLER,
    Scenario,
    assert_entry_amounts,
    assert_field_values,
    assert_fingerprint,
    factories,
    find_entries,
    find_one_entry,
    make_channel_partner_headers,
)

CLOCK = "2026-08-10T09:00:00Z"
PRE_PATCH_FINGERPRINT = "ECO_LITE|1|BAG_CHECKED_1:INCLUDED:1:3500"


def _cascade_world(scenario: Scenario):
    """ECO_LITE published to a parity-required channel, with a live booking and offer."""
    scenario.set_clock(CLOCK)
    bag = scenario.create_product(factories.checked_bag_product_payload())
    boarding = scenario.create_product(factories.priority_boarding_product_payload())

    family = scenario.create_family(factories.eco_lite_family_payload())
    attr_bag = scenario.add_attribute(
        family["id"], bag["id"], inclusion="INCLUDED", included_quantity=1
    )
    published = scenario.publish_family(family["id"])

    channel = scenario.create_channel(factories.direct_web_channel_payload())
    publication = scenario.publish_to_channel(
        family["id"], channel["id"], published["version"]
    )

    flight = scenario.create_flight(flight_no="AA800", origin="JFK", destination="LAX")
    scenario.post_demand(flight["id"], 75, 1200)

    booking = scenario.create_booking(
        flight["id"], family["id"], channel["id"], record_locator="CASC01"
    )
    disclosed = scenario.disclose_and_acknowledge(booking["id"], channel["id"])
    session = scenario.open_offer_session(
        booking["id"], channel["id"], "BOOKING", [boarding["id"]]
    )
    offer_id = session["presented_offer_ids"][0]

    return {
        "family_id": family["id"],
        "attr_bag_id": attr_bag["id"],
        "channel_id": channel["id"],
        "publication_id": publication["id"],
        "booking_id": booking["id"],
        "offer_id": offer_id,
        "acknowledged_fingerprint": disclosed["disclosed_fee_fingerprint"],
    }


def _patch_bag_override(scenario: Scenario, attribute_id: str):
    return validate_success(
        scenario.api.update_family_attribute(
            attribute_id, {"override_price_cents": 3000}, MERCHANDISING_ANALYST
        )
    )


def test_attribute_patch_revalues_and_refingerprints_the_family(scenario):
    """Level one: the attribute takes the override and the family is re-valued in place.

    An override of 3000 on the single included attribute gives an unbundled value of
    3000, an a-la-carte total of 15000 and a 667bp discount, and the fingerprint is
    rebuilt.  The family stays PUBLISHED at the same revision: re-pricing does not
    re-open review.

    Design: Difficulty/transitive_cascade/attribute_patch_parity_breach_chain_depth4
    """
    world = _cascade_world(scenario)
    before = scenario.get_family(world["family_id"])

    patched = _patch_bag_override(scenario, world["attr_bag_id"])
    assert_field_values(patched, effective_unit_cents=3000, attr_value_cents=3000)

    family = scenario.get_family(world["family_id"])
    assert_field_values(
        family,
        unbundled_value_cents=3000,
        a_la_carte_total_cents=15000,
        bundle_discount_bp=667,
        status="PUBLISHED",
    )
    assert_fingerprint(family, "fee_fingerprint", "ECO_LITE|1|BAG_CHECKED_1:INCLUDED:1:3000")
    assert family["revision_no"] == before["revision_no"], (
        "a PATCH re-prices without advancing the revision, "
        f"got {family['revision_no']} against {before['revision_no']}"
    )


def test_attribute_patch_drifts_the_publication_and_breaches_the_channel(scenario):
    """Levels two and three: the publication drifts and the channel counts a breach.

    The publication moves to OUT_OF_PARITY with reason ATTRIBUTE_REPRICED while still
    holding the fingerprint it published, and the parity-required channel goes from
    COMPLIANT with zero breaches to BREACHED with one.

    Design: Difficulty/transitive_cascade/attribute_patch_parity_breach_chain_depth4
    """
    world = _cascade_world(scenario)

    channel_before = scenario.get_channel(world["channel_id"])
    assert_field_values(
        channel_before, parity_breach_count=0, content_parity_status="COMPLIANT"
    )

    _patch_bag_override(scenario, world["attr_bag_id"])

    publication = scenario.get_publication(world["publication_id"])
    assert_field_values(
        publication, parity_state="OUT_OF_PARITY", drift_reason="ATTRIBUTE_REPRICED"
    )
    assert_fingerprint(
        publication, "published_fee_fingerprint", PRE_PATCH_FINGERPRINT
    )

    channel = scenario.get_channel(world["channel_id"])
    assert_field_values(
        channel, parity_breach_count=1, content_parity_status="BREACHED"
    )


def test_attribute_patch_stales_the_disclosure_and_supersedes_the_offer(scenario):
    """Levels three and four: the acknowledged disclosure stales and the live offer dies.

    The booking keeps its HELD status and the fingerprint it acknowledged, but its
    disclosure_state becomes STALE, and the PRESENTED boarding offer - priced at 1376
    with an expected value of 1515 - is SUPERSEDED.

    Design: Difficulty/transitive_cascade/attribute_patch_parity_breach_chain_depth4
    """
    world = _cascade_world(scenario)
    partner = make_channel_partner_headers(world["channel_id"])

    offer_before = validate_success(
        scenario.api.get_ancillary_offer(world["offer_id"], partner)
    )
    assert_field_values(
        offer_before,
        offer_status="PRESENTED",
        offered_price_cents=1376,
        expected_value_cents=1515,
    )

    _patch_bag_override(scenario, world["attr_bag_id"])

    booking = scenario.get_booking(world["booking_id"], world["channel_id"])
    assert_field_values(booking, disclosure_state="STALE", booking_status="HELD")
    assert booking["disclosed_fee_fingerprint"] == world["acknowledged_fingerprint"], (
        "the booking keeps the fingerprint it acknowledged, got "
        f"{booking['disclosed_fee_fingerprint']!r}"
    )

    offer_after = validate_success(
        scenario.api.get_ancillary_offer(world["offer_id"], partner)
    )
    assert offer_after["offer_status"] == "SUPERSEDED", (
        f"the re-price supersedes the live offer, got {offer_after['offer_status']!r}"
    )


def _waiver_cascade_world(scenario: Scenario):
    """A ticketed booking that bought a 1376-cent boarding offer on flight AA900."""
    scenario.set_clock(CLOCK)
    bag = scenario.create_product(factories.checked_bag_product_payload())
    boarding = scenario.create_product(factories.priority_boarding_product_payload())

    family = scenario.create_family(factories.eco_lite_family_payload())
    scenario.add_attribute(family["id"], bag["id"], inclusion="INCLUDED", included_quantity=1)
    published = scenario.publish_family(family["id"])

    channel = scenario.create_channel(factories.direct_web_channel_payload())
    scenario.publish_to_channel(family["id"], channel["id"], published["version"])

    flight = scenario.create_flight(flight_no="AA900", origin="JFK", destination="LAX")
    scenario.post_demand(flight["id"], 75, 1200)

    booking = scenario.create_booking(
        flight["id"], family["id"], channel["id"], record_locator="WAIVR1"
    )
    session = scenario.open_offer_session(
        booking["id"], channel["id"], "BOOKING", [boarding["id"]]
    )
    offer_id = session["presented_offer_ids"][0]
    held = scenario.get_booking(booking["id"], channel["id"])
    scenario.accept_offer(offer_id, channel["id"], held["version"])
    ticketed = scenario.hold_disclose_ack_and_ticket(booking["id"], channel["id"])

    return {
        "flight_id": flight["id"],
        "channel_id": channel["id"],
        "booking_id": booking["id"],
        "boarding_sku": boarding["sku"],
        "ticketed": ticketed,
    }


def test_waiver_declaration_marks_the_flight_and_credits_the_sold_ancillary(scenario):
    """Levels one and two: the flight turns irregular and the boarding sale is credited.

    The waiver posts a single WAIVER_CREDIT mirroring the 1376-cent sale, records one
    credited booking, flags the booking and accumulates the family's whole 7500-cent
    change fee as waived.

    Design: Difficulty/transitive_cascade/irops_waiver_cascade_depth3
    """
    world = _waiver_cascade_world(scenario)
    assert_field_values(
        world["ticketed"], ancillary_gross_cents=1376, channel_settlement_total_cents=15376
    )

    waiver = scenario.declare_waiver(
        world["flight_id"], "DELAY", 240, ["BOARDING", "CHANGE"]
    )
    assert_field_values(
        waiver,
        waiver_state="ACTIVE",
        credited_bookings_count=1,
        credited_amount_cents=1376,
    )

    flight = validate_success(
        scenario.api.get_flight(world["flight_id"], OPERATIONS_CONTROLLER)
    )
    assert_field_values(flight, irops_state="IRREGULAR", active_waiver_count=1)

    entries = scenario.booking_ledger(world["booking_id"])
    credit = find_one_entry(entries, entry_type="WAIVER_CREDIT", category="BOARDING")
    assert_entry_amounts(credit, -1376, -55, -1321)
    assert_field_values(
        credit,
        product_sku=world["boarding_sku"],
        tax_treatment="TAXABLE_SERVICE",
        revenue_account_code="4400",
        source_ref=f"waiver:{waiver['id']}",
    )

    booking = scenario.get_booking(world["booking_id"], world["channel_id"])
    assert_field_values(booking, waiver_applied=True, change_fee_waived_cents=7500)


def test_waiver_credit_reverses_only_sale_rows(scenario):
    """The allocations are left alone and the money returns to its pre-offer values.

    Four rows exist afterwards - two allocations, the sale and its credit - and the
    booking reads a zero ancillary gross, 3035 recognized net and a 14000-cent
    settlement.

    Design: Difficulty/transitive_cascade/irops_waiver_cascade_depth3
    """
    world = _waiver_cascade_world(scenario)

    scenario.declare_waiver(world["flight_id"], "DELAY", 240, ["BOARDING", "CHANGE"])

    entries = scenario.booking_ledger(world["booking_id"])
    assert len(entries) == 4, (
        f"two allocations, one sale and one credit, found {len(entries)}"
    )
    assert len(find_entries(entries, entry_type="ALLOCATION")) == 2, (
        "the waiver credits sales only, so both allocations must survive untouched"
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

    booking = scenario.get_booking(world["booking_id"], world["channel_id"])
    assert_field_values(
        booking,
        ancillary_gross_cents=0,
        recognized_ancillary_net_cents=3035,
        channel_settlement_total_cents=14000,
    )


def test_the_waived_counter_reaches_the_later_change_quote(scenario):
    """Level three: the change-open that follows quotes a zero fee.

    The waiver never writes pending_change_fee_cents; it only raises
    change_fee_waived_cents, and the later quote of max(0, 7500 - 7500) is what makes
    the cascade transitive.

    Design: Difficulty/transitive_cascade/irops_waiver_cascade_depth3
    """
    world = _waiver_cascade_world(scenario)

    scenario.declare_waiver(world["flight_id"], "DELAY", 240, ["BOARDING", "CHANGE"])
    opened = scenario.open_change(world["booking_id"], world["channel_id"])

    assert_field_values(
        opened, booking_status="CHANGE_PENDING", pending_change_fee_cents=0
    )
