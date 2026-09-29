"""Fare family money: the two valuation bases, per-attribute rounding, settlement tiers.

A family's bundle valuation is computed on the override basis and persisted on the
catalog entity, while the regulatory disclosure snapshots the list basis onto the
booking - the same three attributes therefore produce two different totals.  The
rounding contract is per attribute, not on the sum.  At ticketing the incentive
tier is keyed on the provisional total, not on the settled total.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    MERCHANDISING_ANALYST,
    Scenario,
    assert_entry_amounts,
    assert_field_values,
    assert_fingerprint,
    factories,
    find_one_entry,
)

CLOCK = "2026-08-10T09:00:00Z"


def _premium_override_world(scenario: Scenario):
    """PREM_FLEX published with two overridden attributes and one at list price.

    The family is PREMIUM, so every attribute value carries the 1500bp cabin uplift.
    """
    scenario.set_clock(CLOCK)
    bag = scenario.create_product(factories.checked_bag_product_payload())
    seat = scenario.create_product(factories.standard_seat_product_payload())
    boarding = scenario.create_product(factories.priority_boarding_product_payload())

    family = scenario.create_family(
        factories.fare_family_payload(
            code="PREM_FLEX",
            name="Premium Flex",
            cabin_class="PREMIUM",
            base_fare_cents=24000,
            bundle_price_cents=30000,
            refundability="REFUNDABLE_WITH_FEE",
            change_fee_cents=7500,
            boarding_priority_tier=2,
        )
    )
    attr_bag = scenario.add_attribute(
        family["id"],
        bag["id"],
        inclusion="INCLUDED",
        included_quantity=2,
        override_price_cents=3300,
        waiver_eligible=True,
    )
    attr_seat = scenario.add_attribute(
        family["id"],
        seat["id"],
        inclusion="INCLUDED",
        included_quantity=1,
        waiver_eligible=True,
    )
    attr_boarding = scenario.add_attribute(
        family["id"],
        boarding["id"],
        inclusion="INCLUDED",
        included_quantity=1,
        override_price_cents=1200,
        waiver_eligible=False,
    )
    scenario.submit_family(family["id"])
    published = scenario.review_family(family["id"], "APPROVE")

    channel = scenario.create_channel(factories.direct_web_channel_payload())
    flight = scenario.create_flight(flight_no="AA100", origin="JFK", destination="LAX")
    booking = scenario.create_booking(
        flight["id"], family["id"], channel["id"], record_locator="PRM001"
    )
    return {
        "family_id": family["id"],
        "family": published,
        "attr_bag_id": attr_bag["id"],
        "attr_seat_id": attr_seat["id"],
        "attr_boarding_id": attr_boarding["id"],
        "channel_id": channel["id"],
        "booking_id": booking["id"],
    }


def test_override_basis_valuation_is_persisted_on_the_family(scenario):
    """The override basis prices each attribute from its override, then uplifts and sums.

    The overridden bag at 3300 for two units values at 7590, the seat at list values
    at 2185 and the overridden boarding product at 1380, so the family carries an
    unbundled value of 11155, an a-la-carte total of 35155 and a 1466bp discount.

    Design: Difficulty/dual_variant_calc/family_valuation_override_vs_list_basis
    """
    world = _premium_override_world(scenario)

    bag = validate_success(
        scenario.api.get_family_attribute(world["attr_bag_id"], MERCHANDISING_ANALYST)
    )
    assert_field_values(bag, effective_unit_cents=3300, attr_value_cents=7590)
    seat = validate_success(
        scenario.api.get_family_attribute(world["attr_seat_id"], MERCHANDISING_ANALYST)
    )
    assert_field_values(seat, attr_value_cents=2185)
    boarding = validate_success(
        scenario.api.get_family_attribute(world["attr_boarding_id"], MERCHANDISING_ANALYST)
    )
    assert_field_values(boarding, attr_value_cents=1380)

    family = scenario.get_family(world["family_id"])
    assert_field_values(
        family,
        unbundled_value_cents=11155,
        a_la_carte_total_cents=35155,
        bundle_discount_bp=1466,
    )


def test_list_basis_valuation_is_snapshotted_onto_the_booking(scenario):
    """The disclosure ignores the overrides and re-prices the same attributes at list.

    List prices of 3500 x 2, 1900 and 1250 uplifted by 1500bp give 11673 cents -
    518 more than the family's override-basis value.  The disclosure also states the
    7500-cent change fee, pins the fingerprint in sku order and moves the booking to
    PENDING_ACK.

    Design: Difficulty/dual_variant_calc/family_valuation_override_vs_list_basis
    """
    world = _premium_override_world(scenario)

    disclosed = scenario.disclose(world["booking_id"], world["channel_id"])

    assert_field_values(
        disclosed,
        disclosed_unbundled_list_cents=11673,
        disclosed_total_fee_cents=7500,
        disclosure_state="PENDING_ACK",
    )
    assert_fingerprint(
        disclosed,
        "disclosed_fee_fingerprint",
        "PREM_FLEX|1|BAG_CHECKED_1:INCLUDED:2:3300;"
        "PRIORITY_BOARDING:INCLUDED:1:1200;SEAT_STANDARD:INCLUDED:1:1900",
    )

    family = scenario.get_family(world["family_id"])
    assert (
        disclosed["disclosed_unbundled_list_cents"] - family["unbundled_value_cents"] == 518
    ), (
        "the list basis must exceed the override basis by 518 cents, got "
        f"{disclosed['disclosed_unbundled_list_cents']} against {family['unbundled_value_cents']}"
    )


def test_disclosure_does_not_rewrite_the_family_valuation(scenario):
    """The list basis writes only to the booking: the catalog valuation is left alone.

    Design: Difficulty/dual_variant_calc/family_valuation_override_vs_list_basis
    """
    world = _premium_override_world(scenario)

    before = scenario.get_family(world["family_id"])
    assert before["unbundled_value_cents"] == 11155, (
        f"the override basis values the family at 11155, got {before['unbundled_value_cents']}"
    )

    scenario.disclose(world["booking_id"], world["channel_id"])

    after = scenario.get_family(world["family_id"])
    assert_field_values(
        after,
        unbundled_value_cents=11155,
        a_la_carte_total_cents=35155,
        bundle_discount_bp=1466,
    )


def _rounding_world(scenario: Scenario):
    """PREM_ROUND in DRAFT with the boarding attribute attached, wifi still to come.

    Both products land on exactly a half cent once the PREMIUM uplift is applied:
    1250 x 1.15 == 1437.5 and 750 x 1.15 == 862.5.
    """
    scenario.set_clock(CLOCK)
    boarding = scenario.create_product(factories.priority_boarding_product_payload())
    wifi = scenario.create_product(
        factories.wifi_product_payload(
            name="Full-flight wifi", tax_treatment="EXEMPT", refundable=True
        )
    )
    family = scenario.create_family(
        factories.fare_family_payload(
            code="PREM_ROUND",
            name="Premium Round",
            cabin_class="PREMIUM",
            base_fare_cents=24000,
            bundle_price_cents=25000,
            refundability="FULLY_REFUNDABLE",
            change_fee_cents=0,
            boarding_priority_tier=1,
        )
    )
    attr_boarding = scenario.add_attribute(
        family["id"], boarding["id"], inclusion="INCLUDED", included_quantity=1
    )
    return {
        "family_id": family["id"],
        "wifi_id": wifi["id"],
        "attr_boarding_id": attr_boarding["id"],
    }


def test_each_attribute_is_rounded_before_the_sum(scenario):
    """Two half-cent attributes each round up, so the unbundled value is 2301 rather than 2300.

    Rounding once per attribute gives 1438 + 863; deferring the rounding to the sum
    would give 2300 and lose a cent.

    Design: Difficulty/combinatorial_formula/bundle_valuation_round_per_attribute_then_sum
    """
    world = _rounding_world(scenario)

    attr_wifi = scenario.add_attribute(
        world["family_id"], world["wifi_id"], inclusion="INCLUDED", included_quantity=1
    )

    boarding = validate_success(
        scenario.api.get_family_attribute(world["attr_boarding_id"], MERCHANDISING_ANALYST)
    )
    assert_field_values(boarding, attr_value_cents=1438)
    assert_field_values(attr_wifi, attr_value_cents=863)

    family = scenario.get_family(world["family_id"])
    assert family["unbundled_value_cents"] == 2301, (
        "rounding per attribute yields 2301; 2300 would mean the sum was rounded once, "
        f"got {family['unbundled_value_cents']}"
    )


def test_the_rounding_cent_propagates_into_the_discount_basis_points(scenario):
    """The extra cent carries through to the a-la-carte total and the discount.

    26301 rather than 26300, and 495bp rather than 494bp.  The family also counts
    both included attributes and rebuilds its fingerprint in sku order.

    Design: Difficulty/combinatorial_formula/bundle_valuation_round_per_attribute_then_sum
    """
    world = _rounding_world(scenario)

    scenario.add_attribute(
        world["family_id"], world["wifi_id"], inclusion="INCLUDED", included_quantity=1
    )

    family = scenario.get_family(world["family_id"])
    assert_field_values(
        family,
        a_la_carte_total_cents=26301,
        included_attribute_count=2,
    )
    assert family["bundle_discount_bp"] == 495, (
        "the per-attribute rounding lifts the discount to 495bp; 494bp would betray a "
        f"single rounding of the sum, got {family['bundle_discount_bp']}"
    )
    assert_fingerprint(
        family,
        "fee_fingerprint",
        "PREM_ROUND|1|PRIORITY_BOARDING:INCLUDED:1:1250;WIFI_FULL_FLIGHT:INCLUDED:1:750",
    )


def _settlement_tier_world(scenario: Scenario):
    """SETTLE_BASE published to OTA_SKYDEAL, one acknowledged HELD booking ready to ticket."""
    scenario.set_clock(CLOCK)
    bag = scenario.create_product(factories.checked_bag_product_payload())
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
    scenario.publish_to_channel(family["id"], channel["id"], published["version"])

    flight = scenario.create_flight(flight_no="AA500", origin="JFK", destination="LAX")
    booking = scenario.create_booking(
        flight["id"], family["id"], channel["id"], record_locator="TIER01"
    )
    scenario.disclose_and_acknowledge(booking["id"], channel["id"])
    return {
        "family_id": family["id"],
        "channel_id": channel["id"],
        "booking_id": booking["id"],
    }


def test_incentive_tier_is_keyed_on_the_provisional_total(scenario):
    """A provisional total that lands exactly on 30000 earns the 150bp tier.

    The 27523-cent fare at 900bp yields a 2477-cent commission, so the provisional
    total is exactly 30000 and 450 cents are credited back.  The settled total of
    29550 sits below the boundary that granted the credit, which is precisely why the
    tier may not be re-derived from it.

    Design: Difficulty/combinatorial_formula/channel_settlement_incentive_tier_keyed_on_provisional_total
    """
    world = _settlement_tier_world(scenario)

    ticketed = scenario.ticket(world["booking_id"], world["channel_id"])

    assert_field_values(
        ticketed,
        fare_component_cents=27523,
        ancillary_gross_cents=0,
        commission_cents=2477,
    )
    assert ticketed["fare_component_cents"] + ticketed["commission_cents"] == 30000, (
        "the provisional total must land on the 30000 boundary, got "
        f"{ticketed['fare_component_cents'] + ticketed['commission_cents']}"
    )
    assert ticketed["incentive_credit_cents"] == 450, (
        "a provisional total of 30000 earns 150bp, i.e. 450 cents; 0 would mean the tier "
        f"was read off the settled total, got {ticketed['incentive_credit_cents']}"
    )
    assert ticketed["channel_settlement_total_cents"] == 29550, (
        "the settled total is the provisional total less the credit, "
        f"got {ticketed['channel_settlement_total_cents']}"
    )


def test_ticketing_allocates_the_fare_across_two_buckets(scenario):
    """The ticket posts one allocation per positive-weight bucket, summing to the fare.

    The bag weighs 3500 against a 29500-cent a-la-carte total and air transport
    weighs 26000, so the 27523-cent fare splits 3265 / 24258 with the single
    remainder cent going to the heavier bucket.

    Design: Difficulty/combinatorial_formula/channel_settlement_incentive_tier_keyed_on_provisional_total
    """
    world = _settlement_tier_world(scenario)

    scenario.ticket(world["booking_id"], world["channel_id"])

    entries = scenario.booking_ledger(world["booking_id"])
    assert len(entries) == 2, (
        f"only the two positive-weight buckets are allocated, found {len(entries)}"
    )
    assert_entry_amounts(
        find_one_entry(entries, entry_type="ALLOCATION", category="BAGGAGE"), 3265, 131, 3134
    )
    assert_entry_amounts(
        find_one_entry(entries, entry_type="ALLOCATION", category="AIR_TRANSPORT"),
        24258,
        1819,
        22439,
    )
    assert sum(e["gross_cents"] for e in entries) == 27523, (
        "the allocation must be exhaustive, got "
        f"{sum(e['gross_cents'] for e in entries)}"
    )

    family = scenario.get_family(world["family_id"])
    assert_field_values(family, a_la_carte_total_cents=29500, bundle_discount_bp=670)
