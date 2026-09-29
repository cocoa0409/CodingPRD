"""Money calculations: bundle valuation, seat-map pricing, the ticketing
allocation, offer sequencing and the channel settlement.

Every amount here is an integer number of cents and every rate a basis-point
integer, so each assertion carries the arithmetic that produced it.  Where the
contract pins *where* and *how often* a rounding happens, the test deliberately
chooses inputs on which a different rounding order would answer differently.
"""

from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import (
    MERCHANDISING_ANALYST,
    OPERATIONS_CONTROLLER,
    REVENUE_ACCOUNTANT,
    assert_entry_amounts,
    assert_field_values,
    assert_money_field,
    assert_segment_counts,
    build_fee_fingerprint,
    factories,
    find_one_entry,
    make_channel_partner_headers,
)


# ---------------------------------------------------------------------------
# Catalog, family and channel payloads used across the calculations below
# ---------------------------------------------------------------------------
def _checked_bag():
    """BAG_CHECKED_1: BAGGAGE at 3500 cents, taxed as a service (400 bp)."""
    return factories.ancillary_product_payload(
        sku="BAG_CHECKED_1",
        name="First checked bag",
        category="BAGGAGE",
        list_price_cents=3500,
        tax_treatment="TAXABLE_SERVICE",
        revenue_class="NON_AIR",
        revenue_account_code="4100",
    )


def _second_bag():
    """BAG_SECOND: BAGGAGE at 2000 cents, priced to tie with the aisle seat."""
    return factories.ancillary_product_payload(
        sku="BAG_SECOND",
        name="Second checked bag",
        category="BAGGAGE",
        list_price_cents=2000,
        tax_treatment="TAXABLE_SERVICE",
        revenue_class="NON_AIR",
        revenue_account_code="4100",
    )


def _priority_boarding():
    """PRIORITY_BOARDING: BOARDING at 1250 cents."""
    return factories.ancillary_product_payload(
        sku="PRIORITY_BOARDING",
        name="Priority boarding",
        category="BOARDING",
        list_price_cents=1250,
        tax_treatment="TAXABLE_SERVICE",
        revenue_class="NON_AIR",
        revenue_account_code="4400",
    )


def _standard_seat():
    """SEAT_STANDARD: SEAT at 1900 cents, refundable."""
    return factories.ancillary_product_payload(
        sku="SEAT_STANDARD",
        name="Standard seat",
        category="SEAT",
        list_price_cents=1900,
        tax_treatment="TAXABLE_SERVICE",
        revenue_class="NON_AIR",
        revenue_account_code="4200",
        refundable=True,
    )


def _aisle_seat():
    """SEAT_AISLE: SEAT at 2000 cents, priced to tie with the second bag."""
    return factories.ancillary_product_payload(
        sku="SEAT_AISLE",
        name="Aisle seat",
        category="SEAT",
        list_price_cents=2000,
        tax_treatment="TAXABLE_SERVICE",
        revenue_class="NON_AIR",
        revenue_account_code="4200",
        refundable=True,
    )


def _extra_legroom_seat():
    """SEAT_EXTRA_LEGROOM: SEAT at 4200 cents, refundable."""
    return factories.ancillary_product_payload(
        sku="SEAT_EXTRA_LEGROOM",
        name="Extra legroom seat",
        category="SEAT",
        list_price_cents=4200,
        tax_treatment="TAXABLE_SERVICE",
        revenue_class="NON_AIR",
        revenue_account_code="4200",
        refundable=True,
    )


def _wifi():
    """WIFI_FULL_FLIGHT: ONBOARD at 750 cents and EXEMPT from tax."""
    return factories.ancillary_product_payload(
        sku="WIFI_FULL_FLIGHT",
        name="Full flight wifi",
        category="ONBOARD",
        list_price_cents=750,
        tax_treatment="EXEMPT",
        revenue_class="NON_AIR",
        revenue_account_code="4500",
        refundable=True,
    )


def _merch_family():
    """ECO_MERCH: bundles only the flexible-change product.

    Nothing a merchandising session offers is bundled into this family, so every
    other catalog product stays eligible to be sold at the booking touchpoint.
    """
    return factories.fare_family_payload(
        code="ECO_MERCH",
        name="Economy Merchandisable",
        cabin_class="ECONOMY",
        base_fare_cents=12000,
        bundle_price_cents=14000,
        refundability="NON_REFUNDABLE",
        change_fee_cents=7500,
        boarding_priority_tier=4,
    )


def _direct_web_channel():
    """DIRECT_WEB: no commission, no markup, every category merchandisable."""
    return factories.distribution_channel_payload(
        channel_code="DIRECT_WEB",
        channel_type="DIRECT",
        commission_bp=0,
        markup_bp=0,
        max_ancillary_price_cents=20000,
        supported_categories=["BAGGAGE", "SEAT", "CHANGE", "BOARDING", "ONBOARD"],
        parity_required=True,
    )


def _ota_channel():
    """OTA_SKYDEAL: 900 bp commission, 500 bp markup, 6000-cent ancillary ceiling."""
    return factories.distribution_channel_payload(
        channel_code="OTA_SKYDEAL",
        channel_type="OTA",
        commission_bp=900,
        markup_bp=500,
        max_ancillary_price_cents=6000,
        supported_categories=["BAGGAGE", "SEAT", "CHANGE", "BOARDING", "ONBOARD"],
        parity_required=True,
    )


def _instant(rendered):
    """Read a rendered UTC instant back into a comparable datetime."""
    text = str(rendered).replace("Z", "+00:00")
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def _offers_by_product(offers):
    return {offer["ancillary_product_id"]: offer for offer in offers}


def test_ota_commission_drives_the_settlement_total_at_ticketing(api, scenario):
    """PRD §3.5: "It pins `fare_component_cents` from the family's `bundle_price_cents`
    at that instant, freezing the fare component against later family edits."
    PRD §3.9: "`ancillary_gross_cents` is the signed sum of `gross_cents` over the
    booking's revenue entries whose `entry_type` is `SALE`, `REFUND`, `WAIVER_CREDIT`
    or `WAIVER_REVERSAL`."
    PRD §3.9: "`commission_cents` is the subtotal multiplied by the channel's
    `commission_bp`, divided by 10,000, rounded half up."
    PRD §3.9: "The volume-incentive tier is chosen from the **provisional** total of
    step 4: 300 basis points when that total is greater than or equal to 50,000 cents,
    otherwise 150 basis points when it is greater than or equal to 30,000 cents,
    otherwise 0 basis points."
    PRD §3.9: "`channel_settlement_total_cents` is the provisional total minus
    `incentive_credit_cents`."

    Design: Corner/calculations/channel_settlement_total_applies_ota_commission_at_ticketing
    """
    bag = scenario.create_product(_checked_bag())
    family = scenario.create_family(factories.eco_lite_family_payload())
    scenario.add_attribute(
        family["id"], bag["id"], inclusion="INCLUDED", included_quantity=1
    )
    published = scenario.publish_family(family["id"])
    # 12000 base fare + 3500 bag at ECONOMY (no uplift) = 15500 a la carte
    assert_money_field(published, "unbundled_value_cents", 3500)
    assert_money_field(published, "a_la_carte_total_cents", 15500)

    channel = scenario.create_channel(_ota_channel())
    scenario.publish_to_channel(family["id"], channel["id"], published["version"])
    flight = scenario.create_flight()
    booking = scenario.create_booking(flight["id"], family["id"], channel["id"])
    ticketed = scenario.hold_disclose_ack_and_ticket(booking["id"], channel["id"])

    assert ticketed["booking_status"] == "TICKETED"
    # The fare component is the bundle price, pinned at the ticketing instant.
    assert_money_field(ticketed, "fare_component_cents", 14000)
    # Allocation rows are not sales, so the ancillary gross stays empty.
    assert_money_field(ticketed, "ancillary_gross_cents", 0)
    # 14000 subtotal x 900bp OTA commission / 10000 = 1260
    assert_money_field(ticketed, "commission_cents", 1260)
    # provisional 14000 + 1260 = 15260, short of the 30000 incentive edge
    assert_money_field(ticketed, "incentive_credit_cents", 0)
    # 15260 provisional - 0 incentive = 15260
    assert_money_field(ticketed, "channel_settlement_total_cents", 15260)
    # BAGGAGE allocation 3161 less its 400bp service tax 126 = 3035 recognised
    assert_money_field(ticketed, "recognized_ancillary_net_cents", 3035)

    entries, meta = validate_paginated(
        api.list_booking_revenue_entries(booking["id"], REVENUE_ACCOUNTANT)
    )
    assert meta["total_count"] == 2, (
        "two weighted categories means two allocation rows: " f"{entries}"
    )
    # weights 3500 bag / 12000 air over 15500 total: floors 3161 + 10838 leave one
    # cent, which the heavier air-transport bucket takes.
    bag_row = find_one_entry(entries, entry_type="ALLOCATION", category="BAGGAGE")
    assert_entry_amounts(bag_row, gross_cents=3161, tax_cents=126, net_cents=3035)
    air_row = find_one_entry(entries, entry_type="ALLOCATION", category="AIR_TRANSPORT")
    # 10839 x 750bp transport tax = 812.925, half up to 813
    assert_entry_amounts(air_row, gross_cents=10839, tax_cents=813, net_cents=10026)


def test_withdrawing_an_attribute_removes_it_from_every_family_output(api, scenario):
    """PRD §3.1: "Withdrawn attributes are excluded from every output, including the
    fingerprint."
    PRD §3.1: "The family's `unbundled_value_cents` is the sum of those per-attribute
    values. Its `a_la_carte_total_cents` is `base_fare_cents` plus
    `unbundled_value_cents`. Its `included_attribute_count` is the number of `ACTIVE`
    attributes whose `inclusion` is `INCLUDED`. Its `bundle_discount_bp` — the basis
    points a passenger saves by buying the bundle instead of every component
    separately — is 0 when `unbundled_value_cents` is 0; otherwise it is
    `a_la_carte_total_cents` minus `bundle_price_cents`, multiplied by 10,000, divided
    by `a_la_carte_total_cents`, and rounded half up."
    PRD §2.3: "an `attribute_state` that defaults to `ACTIVE` and may become
    `WITHDRAWN`"
    PRD §2.3: "Attributes are readable singly and as a paginated list filterable by
    `fare_family_id`, by `ancillary_product_id` and by `attribute_state`."

    Design: Corner/calculations/bundle_valuation_excludes_withdrawn_attribute_from_every_output
    """
    bag = scenario.create_product(_checked_bag())
    boarding = scenario.create_product(_priority_boarding())
    family = scenario.create_family(
        factories.fare_family_payload(
            code="ECO_TWO", name="Economy Two", bundle_price_cents=15000
        )
    )
    bag_attr = scenario.add_attribute(
        family["id"], bag["id"], inclusion="INCLUDED", included_quantity=1
    )
    boarding_attr = scenario.add_attribute(
        family["id"], boarding["id"], inclusion="INCLUDED", included_quantity=1
    )

    before = scenario.get_family(family["id"])
    # 3500 bag + 1250 priority boarding, ECONOMY so no uplift on either
    assert_money_field(before, "unbundled_value_cents", 4750)
    assert_money_field(before, "a_la_carte_total_cents", 16750)
    # (16750 - 15000) x 10000 / 16750 = 1044.78, half up to 1045
    assert before["bundle_discount_bp"] == 1045, before["bundle_discount_bp"]
    assert before["included_attribute_count"] == 2, before["included_attribute_count"]

    validate_success(
        api.update_family_attribute(
            boarding_attr["id"], {"attribute_state": "WITHDRAWN"}, MERCHANDISING_ANALYST
        )
    )

    after = scenario.get_family(family["id"])
    # the withdrawn 1250 boarding row contributes nothing: 4750 - 1250 = 3500
    assert_money_field(after, "unbundled_value_cents", 3500)
    assert_money_field(after, "a_la_carte_total_cents", 15500)
    # (15500 - 15000) x 10000 / 15500 = 322.58, half up to 323
    assert after["bundle_discount_bp"] == 323, after["bundle_discount_bp"]
    assert after["included_attribute_count"] == 1, after["included_attribute_count"]
    assert after["fee_fingerprint"] == build_fee_fingerprint(
        "ECO_TWO", 1, [("BAG_CHECKED_1", "INCLUDED", 1, 3500)]
    ), after["fee_fingerprint"]

    # The withdrawn row itself is still on file, priced as it always was.
    withdrawn = validate_success(
        api.get_family_attribute(boarding_attr["id"], MERCHANDISING_ANALYST)
    )
    assert_field_values(withdrawn, attribute_state="WITHDRAWN")
    assert_money_field(withdrawn, "effective_unit_cents", 1250)

    surviving = validate_success(
        api.get_family_attribute(bag_attr["id"], MERCHANDISING_ANALYST)
    )
    assert_field_values(surviving, attribute_state="ACTIVE")
    assert_money_field(surviving, "attr_value_cents", 3500)

    _, all_meta = validate_paginated(
        api.list_family_attributes(
            MERCHANDISING_ANALYST, {"fare_family_id": family["id"]}
        )
    )
    assert all_meta["total_count"] == 2, "both rows remain readable after withdrawal"
    active_rows, active_meta = validate_paginated(
        api.list_family_attributes(
            MERCHANDISING_ANALYST,
            {"fare_family_id": family["id"], "attribute_state": "ACTIVE"},
        )
    )
    assert active_meta["total_count"] == 1, active_rows
    assert active_rows[0]["id"] == bag_attr["id"], active_rows


def test_cabin_uplift_differs_between_an_economy_and_a_business_family(scenario):
    """PRD §3.1: "For each attribute in turn, take its effective unit price, multiply
    it by the attribute's `included_quantity`, multiply that by 10,000 plus the cabin
    uplift in basis points for the family's `cabin_class`, divide by 10,000, and round
    the result half up: that single integer is the attribute's `attr_value_cents`."
    PRD §3.1: "The cabin uplift is nothing at all for `ECONOMY`, 1,500 basis points —
    a fifteen percent premium — for `PREMIUM`, and 3,000 basis points — a thirty
    percent premium — for `BUSINESS`."
    PRD §2.3: "`effective_unit_cents`, which is `override_price_cents` when that is not
    null and otherwise the referenced product's `list_price_cents`"

    Design: Corner/calculations/cabin_uplift_bp_differs_between_economy_and_business_families
    """
    legroom = scenario.create_product(_extra_legroom_seat())

    economy = scenario.create_family(
        factories.fare_family_payload(
            code="ECO_LEG",
            name="Economy Legroom",
            cabin_class="ECONOMY",
            base_fare_cents=12000,
            bundle_price_cents=18000,
        )
    )
    economy_attr = scenario.add_attribute(
        economy["id"],
        legroom["id"],
        inclusion="INCLUDED",
        included_quantity=2,
        override_price_cents=4000,
    )

    business = scenario.create_family(
        factories.fare_family_payload(
            code="BIZ_FLEX",
            name="Business Flex",
            cabin_class="BUSINESS",
            base_fare_cents=60000,
            bundle_price_cents=68000,
            refundability="FULLY_REFUNDABLE",
            change_fee_cents=0,
            boarding_priority_tier=1,
        )
    )
    business_attr = scenario.add_attribute(
        business["id"],
        legroom["id"],
        inclusion="INCLUDED",
        included_quantity=2,
        override_price_cents=4000,
    )

    # Same product, same override, same quantity: only the cabin differs.
    assert_money_field(economy_attr, "effective_unit_cents", 4000)
    assert_money_field(business_attr, "effective_unit_cents", 4000)
    # 4000 override x 2 seats x (10000 + 0bp ECONOMY uplift) / 10000 = 8000
    assert_money_field(economy_attr, "attr_value_cents", 8000)
    # 4000 override x 2 seats x (10000 + 3000bp BUSINESS uplift) / 10000 = 10400
    assert_money_field(business_attr, "attr_value_cents", 10400)

    economy_family = scenario.get_family(economy["id"])
    assert_money_field(economy_family, "unbundled_value_cents", 8000)
    assert_money_field(economy_family, "a_la_carte_total_cents", 20000)
    # (20000 - 18000) x 10000 / 20000 = 1000 exactly
    assert economy_family["bundle_discount_bp"] == 1000, economy_family

    business_family = scenario.get_family(business["id"])
    assert_money_field(business_family, "unbundled_value_cents", 10400)
    assert_money_field(business_family, "a_la_carte_total_cents", 70400)
    # (70400 - 68000) x 10000 / 70400 = 340.91, half up to 341
    assert business_family["bundle_discount_bp"] == 341, business_family

    # Both fingerprints quote the override, not the 4200 catalog list price.
    expected_part = [("SEAT_EXTRA_LEGROOM", "INCLUDED", 2, 4000)]
    assert economy_family["fee_fingerprint"] == build_fee_fingerprint(
        "ECO_LEG", 1, expected_part
    ), economy_family["fee_fingerprint"]
    assert business_family["fee_fingerprint"] == build_fee_fingerprint(
        "BIZ_FLEX", 1, expected_part
    ), business_family["fee_fingerprint"]


def test_seat_price_rounds_the_whole_product_once_not_at_each_step(scenario):
    """PRD §3.3: "Third — and this is the pinned part — the exact integer zone base is
    multiplied by both multipliers, the product is divided by one hundred million (that
    is, by 10,000 twice, once for each basis-point factor), and only that final quotient
    is rounded half up."
    PRD §3.3: "The zone and demand multipliers are applied to the exact rational
    product, never to an intermediate rounded value; rounding after the first
    multiplication and again after the second gives a different and incorrect answer."
    PRD §3.3: "the zone multiplier stored on the segment as `zone_multiplier_bp`, which
    is 13,000 basis points for `FWD`, 10,000 for `MID`, 9,000 for `AFT`, 16,000 for
    `EXIT_ROW` and 14,000 for `BULKHEAD`; and the demand multiplier for the flight's
    current demand tier, which is 10,000 basis points at `LOW`, 11,000 at `MID` and
    12,500 at `HIGH`."
    PRD §3.3: "At creation `available_seats` equals `total_seats`, `held_seats` and
    `sold_seats` are 0, and `segment_state` is `OPEN`."

    Design: Corner/calculations/seat_price_rounds_the_full_product_once_not_stepwise
    """
    legroom = scenario.create_product(_extra_legroom_seat())
    flight = scenario.create_flight()
    segment = scenario.create_segment(
        flight["id"],
        legroom["id"],
        zone="BULKHEAD",
        row_start=16,
        row_end=16,
        seat_letters=["A", "B", "C"],
        base_price_cents=1001,
    )

    # Row 16 draws no band adjustment, so the zone base stays the odd 1001 cents.
    assert_segment_counts(
        segment, total_seats=3, held_seats=0, sold_seats=0, available_seats=3
    )
    assert segment["segment_state"] == "OPEN", segment["segment_state"]
    assert segment["zone_multiplier_bp"] == 14000, segment["zone_multiplier_bp"]
    # 1001 x 14000 BULKHEAD x 10000 LOW / 100,000,000 = 1401.4, half up to 1401
    assert_money_field(segment, "effective_price_cents", 1401)

    # A load factor of 80 puts the flight in the top demand tier.
    snapshot = scenario.post_demand(flight["id"], 80, 0)
    assert snapshot["demand_tier"] == "HIGH", snapshot["demand_tier"]

    repriced = scenario.get_segment(segment["id"])
    # 1001 x 14000 x 12500 / 100,000,000 = 1751.75, half up to 1752.  Rounding after
    # the zone step first (1401) and again after the demand step would give 1751.
    assert_money_field(repriced, "effective_price_cents", 1752)
    assert_segment_counts(repriced, total_seats=3, available_seats=3)


def test_fee_fingerprint_orders_its_parts_by_product_sku(scenario):
    """PRD §2.8: "Take every attribute of the family whose `attribute_state` is
    `ACTIVE`, ordered by the `sku` of the referenced catalog product ascending."
    PRD §2.8: "For each one, form a part by joining four pieces with a colon between
    them: the product's `sku`, then the attribute's `inclusion`, then its
    `included_quantity` written as a decimal integer, then its `effective_unit_cents`
    written as a decimal integer."
    PRD §2.8: "Then form the fingerprint by writing the family's `code`, a vertical bar,
    the family's `revision_no` as a decimal integer, a second vertical bar, and finally
    the parts joined together with a semicolon between consecutive parts."
    PRD §3.1: "Because a `CHARGEABLE` attribute always carries a quantity of 0, it
    always contributes exactly 0 to the bundle value while still contributing to the
    fingerprint and to the disclosed fee total."

    Design: Corner/calculations/fee_fingerprint_orders_parts_by_product_sku_ascending
    """
    boarding = scenario.create_product(_priority_boarding())
    seat = scenario.create_product(_standard_seat())
    bag = scenario.create_product(_checked_bag())

    family = scenario.create_family(
        factories.fare_family_payload(
            code="ECO_ORD", name="Economy Ordered", bundle_price_cents=15000
        )
    )
    # Attached deliberately out of alphabetical order: boarding, seat, then bag.
    scenario.add_attribute(
        family["id"], boarding["id"], inclusion="INCLUDED", included_quantity=1
    )
    seat_attr = scenario.add_attribute(
        family["id"], seat["id"], inclusion="CHARGEABLE", included_quantity=0
    )
    scenario.add_attribute(
        family["id"], bag["id"], inclusion="INCLUDED", included_quantity=1
    )

    # The chargeable seat is quoted at its list price but adds nothing to the bundle.
    assert_money_field(seat_attr, "effective_unit_cents", 1900)
    assert_money_field(seat_attr, "attr_value_cents", 0)

    valued = scenario.get_family(family["id"])
    assert valued["fee_fingerprint"] == (
        "ECO_ORD|1|"
        "BAG_CHECKED_1:INCLUDED:1:3500;"
        "PRIORITY_BOARDING:INCLUDED:1:1250;"
        "SEAT_STANDARD:CHARGEABLE:0:1900"
    ), valued["fee_fingerprint"]

    # 3500 bag + 1250 boarding + 0 for the chargeable seat = 4750 bundled value
    assert_money_field(valued, "unbundled_value_cents", 4750)
    assert_money_field(valued, "a_la_carte_total_cents", 16750)
    # (16750 - 15000) x 10000 / 16750 = 1044.78, half up to 1045
    assert valued["bundle_discount_bp"] == 1045, valued["bundle_discount_bp"]
    assert valued["included_attribute_count"] == 2, valued["included_attribute_count"]


def test_row_band_adjustment_switches_at_rows_five_six_and_sixteen(api, scenario):
    """PRD §3.3: "First, a row-band adjustment is chosen from the segment's `row_start`:
    1,500 cents when `row_start` is 5 or lower, 500 cents when `row_start` is between 6
    and 15 inclusive, and nothing at all when `row_start` is 16 or higher."
    PRD §3.3: "That adjustment is added to `base_price_cents` to give an exact integer
    zone base — no rounding happens here, because nothing has been divided yet."
    PRD §3.3: "The segment's `total_seats` is therefore `row_end` minus `row_start` plus
    one, multiplied by the number of entries in `seat_letters`."
    PRD §3.3: "The test is per seat, not per row range, so two segments may cover the
    very same rows as long as their letter sets are disjoint, and two segments with
    adjacent but non-overlapping row ranges never collide."

    Design: Corner/calculations/seat_price_row_band_boundaries_at_rows_five_six_and_sixteen
    """
    seat = scenario.create_product(_standard_seat())
    flight = scenario.create_flight()
    assert flight["demand_tier"] == "LOW", flight["demand_tier"]

    # Three non-overlapping rectangles, identical but for where their rows start.
    front = scenario.create_segment(
        flight["id"],
        seat["id"],
        zone="MID",
        row_start=1,
        row_end=5,
        seat_letters=["A"],
        base_price_cents=1000,
    )
    middle = scenario.create_segment(
        flight["id"],
        seat["id"],
        zone="MID",
        row_start=6,
        row_end=6,
        seat_letters=["A"],
        base_price_cents=1000,
    )
    rear = scenario.create_segment(
        flight["id"],
        seat["id"],
        zone="MID",
        row_start=16,
        row_end=16,
        seat_letters=["A"],
        base_price_cents=1000,
    )

    # rows 1-5 x one letter = 5 seats; (1000 + 1500) x 10000 MID x 10000 LOW = 2500
    assert_segment_counts(front, total_seats=5, available_seats=5)
    assert_money_field(front, "effective_price_cents", 2500)
    # row 6 is the first row of the middle band: (1000 + 500) x 1 x 1 = 1500
    assert_segment_counts(middle, total_seats=1, available_seats=1)
    assert_money_field(middle, "effective_price_cents", 1500)
    # row 16 is the first row with no band adjustment at all: 1000
    assert_segment_counts(rear, total_seats=1, available_seats=1)
    assert_money_field(rear, "effective_price_cents", 1000)

    segments, meta = validate_paginated(
        api.list_seat_segments(OPERATIONS_CONTROLLER, {"flight_id": flight["id"]})
    )
    assert meta["total_count"] == 3, segments


def test_ticketing_allocation_fills_five_buckets_and_places_the_two_cent_remainder(
    api, scenario
):
    """PRD §3.5: "Each ancillary category's weight is the sum of `attr_value_cents` over
    the family's attributes that are `ACTIVE` and `INCLUDED` whose product falls in that
    category"
    PRD §3.5: "The synthetic `AIR_TRANSPORT` category's weight is the family's
    `base_fare_cents`. The total weight is the family's `a_la_carte_total_cents`, which
    by construction equals `base_fare_cents` plus `unbundled_value_cents`."
    PRD §3.5: "Pass one prorates by **flooring**, never by rounding half up: each
    bucket's gross amount is the pinned `fare_component_cents` multiplied by that
    bucket's weight, divided by the total weight, and truncated downward to a whole
    number of cents."
    PRD §3.5: "Pass two distributes that remainder **one cent at a time**, walking the
    buckets in descending order of weight and breaking ties by the bucket's index in the
    category priority order ascending"
    PRD §3.5: "Pass three taxes each bucket: the bucket's tax is its gross amount
    multiplied by the tax rate in basis points for the bucket's tax treatment, divided
    by 10,000, and rounded half up; the bucket's net is its gross minus its tax."
    PRD §3.5: "The `AIR_TRANSPORT` bucket instead uses `tax_treatment`
    `TAXABLE_TRANSPORT`, `revenue_class` `AIR_TRANSPORT_RELATED`,
    `revenue_account_code` `3000` and `product_sku` `AIR_TRANSPORT`."

    Design: Corner/calculations/revenue_split_fills_five_category_buckets_and_places_the_two_cent_remainder
    """
    bag = scenario.create_product(_checked_bag())
    seat = scenario.create_product(_standard_seat())
    boarding = scenario.create_product(_priority_boarding())
    wifi = scenario.create_product(_wifi())

    family = scenario.create_family(
        factories.fare_family_payload(
            code="ECO_FIVE",
            name="Economy Five Bucket",
            base_fare_cents=12000,
            bundle_price_cents=15000,
        )
    )
    for product in (bag, seat, boarding, wifi):
        scenario.add_attribute(
            family["id"], product["id"], inclusion="INCLUDED", included_quantity=1
        )
    published = scenario.publish_family(family["id"])
    # 3500 + 1900 + 1250 + 750 = 7400 bundled, over a 12000 base fare
    assert_money_field(published, "unbundled_value_cents", 7400)
    assert_money_field(published, "a_la_carte_total_cents", 19400)

    channel = scenario.create_channel(_direct_web_channel())
    scenario.publish_to_channel(family["id"], channel["id"], published["version"])
    flight = scenario.create_flight()
    booking = scenario.create_booking(flight["id"], family["id"], channel["id"])
    ticketed = scenario.hold_disclose_ack_and_ticket(booking["id"], channel["id"])

    assert_money_field(ticketed, "fare_component_cents", 15000)
    assert_money_field(ticketed, "ancillary_gross_cents", 0)
    # 2599 + 1410 + 927 + 579 non-transport nets = 5515
    assert_money_field(ticketed, "recognized_ancillary_net_cents", 5515)
    # a direct channel charges no commission, and 15000 is below the 30000 tier edge
    assert_money_field(ticketed, "commission_cents", 0)
    assert_money_field(ticketed, "incentive_credit_cents", 0)
    assert_money_field(ticketed, "channel_settlement_total_cents", 15000)

    entries, meta = validate_paginated(
        api.list_booking_revenue_entries(booking["id"], REVENUE_ACCOUNTANT)
    )
    assert meta["total_count"] == 5, f"five weighted categories, five rows: {entries}"

    # Floors over the 19400 total weight give 2706 + 1469 + 966 + 579 + 9278 = 14998,
    # so two cents remain: the heaviest bucket (air transport, weight 12000) takes the
    # first and baggage (weight 3500) takes the second.
    bag_row = find_one_entry(entries, entry_type="ALLOCATION", category="BAGGAGE")
    assert_entry_amounts(bag_row, gross_cents=2707, tax_cents=108, net_cents=2599)
    assert_field_values(bag_row, product_sku="BAG_CHECKED_1", revenue_account_code="4100")

    seat_row = find_one_entry(entries, entry_type="ALLOCATION", category="SEAT")
    assert_entry_amounts(seat_row, gross_cents=1469, tax_cents=59, net_cents=1410)
    assert_field_values(seat_row, product_sku="SEAT_STANDARD", revenue_account_code="4200")

    boarding_row = find_one_entry(entries, entry_type="ALLOCATION", category="BOARDING")
    assert_entry_amounts(boarding_row, gross_cents=966, tax_cents=39, net_cents=927)
    assert_field_values(
        boarding_row, product_sku="PRIORITY_BOARDING", revenue_account_code="4400"
    )

    # The onboard bucket is tax exempt, so its net equals its gross.
    onboard_row = find_one_entry(entries, entry_type="ALLOCATION", category="ONBOARD")
    assert_entry_amounts(onboard_row, gross_cents=579, tax_cents=0, net_cents=579)
    assert_field_values(
        onboard_row,
        product_sku="WIFI_FULL_FLIGHT",
        revenue_account_code="4500",
        tax_treatment="EXEMPT",
    )

    air_row = find_one_entry(entries, entry_type="ALLOCATION", category="AIR_TRANSPORT")
    # 9279 x 750bp transport tax = 695.925, half up to 696
    assert_entry_amounts(air_row, gross_cents=9279, tax_cents=696, net_cents=8583)
    assert_field_values(
        air_row,
        product_sku="AIR_TRANSPORT",
        revenue_account_code="3000",
        tax_treatment="TAXABLE_TRANSPORT",
        revenue_class="AIR_TRANSPORT_RELATED",
    )

    # The buckets must add back to the pinned fare component exactly.
    assert sum(e["gross_cents"] for e in entries) == 15000, entries
    assert sum(e["tax_cents"] for e in entries) == 902, entries


def test_offer_session_ranks_by_expected_value_and_presents_only_three(api, scenario):
    """PRD §3.6: "Candidates are ranked by `expected_value_cents` descending."
    PRD §3.6: "The first three entries of the ranked list, at most, are presented; each
    becomes an offer with `offer_status` `PRESENTED`, a `sequence_rank` of 1 through the
    number presented in ranked order, a `valid_from` equal to the logical clock, and a
    `valid_until` exactly one hour later."
    PRD §3.6: "The session responds with the `touchpoint` it ran at, a `candidate_count`
    giving the size of the eligible pool **before** truncation, a `presented_offer_ids`
    array of the ids created in ranked order, and an empty `suppression_reason`."
    PRD §3.6: "The raw score is 10,000 basis points, plus 40 basis points for every
    percentage point by which the flight's `booked_load_factor_pct` exceeds 50 — that is,
    plus 40 multiplied by `booked_load_factor_pct` minus 50 — plus a scarcity term formed
    by multiplying the flight's `demand_index_bp` by 60, dividing by 10,000 and rounding
    half up."
    PRD §3.6: "Finally, `expected_value_cents` is `offered_price_cents` multiplied by
    `wtp_score_bp`, divided by 10,000 and rounded half up; this is the ranking key."

    Design: Corner/calculations/offer_session_ranks_by_expected_value_and_truncates_to_three
    """
    legroom = scenario.create_product(_extra_legroom_seat())
    bag = scenario.create_product(_checked_bag())
    boarding = scenario.create_product(_priority_boarding())
    wifi = scenario.create_product(_wifi())
    change = scenario.create_product(factories.change_flex_product_payload())

    family = scenario.create_family(_merch_family())
    scenario.add_attribute(
        family["id"], change["id"], inclusion="INCLUDED", included_quantity=1
    )
    published = scenario.publish_family(family["id"])
    channel = scenario.create_channel(_direct_web_channel())
    scenario.publish_to_channel(family["id"], channel["id"], published["version"])

    flight = scenario.create_flight()
    # A load factor of exactly 50 with a flat demand index leaves the score untouched.
    scenario.post_demand(flight["id"], 50, 0)
    booking = scenario.create_booking(flight["id"], family["id"], channel["id"])

    session = scenario.open_offer_session(booking["id"], channel["id"], "BOOKING")
    assert session["touchpoint"] == "BOOKING", session
    # The bundled change product is not a candidate; the other four all are.
    assert session["candidate_count"] == 4, session
    assert len(session["presented_offer_ids"]) == 3, session
    assert session["suppression_reason"] in ("", None), session["suppression_reason"]

    offers = scenario.offers_for_booking(booking["id"], channel["id"])
    assert len(offers) == 3, offers
    by_product = _offers_by_product(offers)

    for offer in offers:
        assert offer["offer_status"] == "PRESENTED", offer
        assert offer["pricing_variant"] == "WTP_ELASTIC", offer
        # 10000 + 40 x (50 - 50) + round(0 x 60 / 10000) = 10000
        assert offer["wtp_score_bp"] == 10000, offer
        # a neutral score, a booking touchpoint and a markup-free channel all leave
        # the list price alone, and the expected value repeats it
        assert offer["expected_value_cents"] == offer["offered_price_cents"], offer
        assert _instant(offer["valid_until"]) - _instant(offer["valid_from"]) == timedelta(
            hours=1
        ), offer

    legroom_offer = by_product[legroom["id"]]
    bag_offer = by_product[bag["id"]]
    boarding_offer = by_product[boarding["id"]]
    # 4200 legroom > 3500 bag > 1250 boarding > 750 wifi, so wifi falls off the end
    assert_money_field(legroom_offer, "offered_price_cents", 4200)
    assert legroom_offer["sequence_rank"] == 1, legroom_offer
    assert_money_field(bag_offer, "offered_price_cents", 3500)
    assert bag_offer["sequence_rank"] == 2, bag_offer
    assert_money_field(boarding_offer, "offered_price_cents", 1250)
    assert boarding_offer["sequence_rank"] == 3, boarding_offer

    assert session["presented_offer_ids"] == [
        legroom_offer["id"],
        bag_offer["id"],
        boarding_offer["id"],
    ], session["presented_offer_ids"]

    _, wifi_meta = validate_paginated(
        api.list_ancillary_offers(
            make_channel_partner_headers(channel["id"]),
            {"booking_id": booking["id"], "ancillary_product_id": wifi["id"]},
        )
    )
    assert wifi_meta["total_count"] == 0, "the truncated candidate gets no offer row"


def test_equal_expected_values_rank_baggage_ahead_of_seat(scenario):
    """PRD §3.6: "Ties are broken first by the index of the product's `category` in the
    priority order `BAGGAGE`, `SEAT`, `CHANGE`, `BOARDING`, `ONBOARD`, `AIR_TRANSPORT`
    ascending, and then by the product's `created_at` ascending — never by the product's
    `id`."
    PRD §3.6: "The first three entries of the ranked list, at most, are presented; each
    becomes an offer with `offer_status` `PRESENTED`, a `sequence_rank` of 1 through the
    number presented in ranked order, a `valid_from` equal to the logical clock, and a
    `valid_until` exactly one hour later."
    PRD §3.6: "If the request supplied `requested_product_ids`, the product's id is a
    member of that list."

    Design: Corner/calculations/offer_session_tie_break_prefers_baggage_over_seat_at_equal_expected_value
    """
    # The seat is created first and asked for first, so only the category priority
    # order can put the bag in front of it.
    aisle = scenario.create_product(_aisle_seat())
    second_bag = scenario.create_product(_second_bag())
    change = scenario.create_product(factories.change_flex_product_payload())

    family = scenario.create_family(_merch_family())
    scenario.add_attribute(
        family["id"], change["id"], inclusion="INCLUDED", included_quantity=1
    )
    published = scenario.publish_family(family["id"])
    channel = scenario.create_channel(_direct_web_channel())
    scenario.publish_to_channel(family["id"], channel["id"], published["version"])

    flight = scenario.create_flight()
    scenario.post_demand(flight["id"], 50, 0)
    booking = scenario.create_booking(flight["id"], family["id"], channel["id"])

    session = scenario.open_offer_session(
        booking["id"],
        channel["id"],
        "BOOKING",
        requested_product_ids=[aisle["id"], second_bag["id"]],
    )
    assert session["candidate_count"] == 2, session

    offers = scenario.offers_for_booking(booking["id"], channel["id"])
    assert len(offers) == 2, offers
    by_product = _offers_by_product(offers)
    bag_offer = by_product[second_bag["id"]]
    seat_offer = by_product[aisle["id"]]

    # Both are 2000 at list, both score 10000bp, so both expect exactly 2000.
    for offer in (bag_offer, seat_offer):
        assert offer["wtp_score_bp"] == 10000, offer
        assert_money_field(offer, "offered_price_cents", 2000)
        assert_money_field(offer, "expected_value_cents", 2000)

    assert bag_offer["sequence_rank"] == 1, "BAGGAGE precedes SEAT in the priority order"
    assert seat_offer["sequence_rank"] == 2, seat_offer
    assert session["presented_offer_ids"] == [bag_offer["id"], seat_offer["id"]], session


def test_residual_inventory_pricing_needs_an_open_seat_segment(scenario):
    """PRD §3.6: "The `RESIDUAL_INVENTORY` variant applies when — and only when — the
    product's `category` is `SEAT` **and** at least one seat segment on the booking's
    flight referencing that product has `segment_state` `OPEN`."
    PRD §3.6: "Sum `total_seats` across those open segments to get a basis total, sum
    `available_seats` across the same segments to get a basis available, subtract the
    available from the total, multiply by 100, divide by the basis total, and round half
    up: that is the sold percentage."
    PRD §3.6: "The raw score is then 10,000 basis points plus 60 basis points for every
    percentage point by which the sold percentage exceeds 50 — equivalently, 10,000 plus
    60 multiplied by the sold percentage minus 50, which goes negative when less than
    half the seats have gone."
    PRD §3.6: "The `WTP_ELASTIC` variant applies in every other case: whenever the
    product's `category` is anything other than `SEAT`, **or** when no seat segment on
    the flight for that product is `OPEN`."
    PRD §3.6: "the floor is `list_price_cents` multiplied by 7,000, divided by 10,000 and
    rounded half up — seventy percent of list"

    Design: Corner/calculations/residual_inventory_variant_applies_only_when_an_open_seat_segment_exists
    """
    legroom = scenario.create_product(_extra_legroom_seat())
    change = scenario.create_product(factories.change_flex_product_payload())

    family = scenario.create_family(_merch_family())
    scenario.add_attribute(
        family["id"], change["id"], inclusion="INCLUDED", included_quantity=1
    )
    published = scenario.publish_family(family["id"])
    channel = scenario.create_channel(_direct_web_channel())
    scenario.publish_to_channel(family["id"], channel["id"], published["version"])

    # Two flights with identical demand data: one has a legroom seat map, one has none.
    mapped_flight = scenario.create_flight()
    scenario.post_demand(mapped_flight["id"], 50, 0)
    segment = scenario.create_segment(
        mapped_flight["id"],
        legroom["id"],
        zone="MID",
        row_start=16,
        row_end=16,
        seat_letters=["A", "B", "C"],
        base_price_cents=2000,
    )
    assert_segment_counts(segment, total_seats=3, available_seats=3)
    assert segment["segment_state"] == "OPEN", segment

    bare_flight = scenario.create_flight()
    scenario.post_demand(bare_flight["id"], 50, 0)

    mapped_booking = scenario.create_booking(
        mapped_flight["id"], family["id"], channel["id"]
    )
    mapped_session = scenario.open_offer_session(
        mapped_booking["id"], channel["id"], "BOOKING"
    )
    assert mapped_session["candidate_count"] == 1, mapped_session
    mapped_offers = scenario.offers_for_booking(mapped_booking["id"], channel["id"])
    assert len(mapped_offers) == 1, mapped_offers
    residual = mapped_offers[0]
    assert residual["pricing_variant"] == "RESIDUAL_INVENTORY", residual
    # nothing sold yet: 0 percent sold, 10000 + 60 x (0 - 50) = 7000
    assert residual["wtp_score_bp"] == 7000, residual
    # 4200 x 7000 / 10000 = 2940, and the 70-percent-of-list floor is 2940 too
    assert_money_field(residual, "offered_price_cents", 2940)
    # 2940 x 7000 / 10000 = 2058
    assert_money_field(residual, "expected_value_cents", 2058)

    bare_booking = scenario.create_booking(
        bare_flight["id"], family["id"], channel["id"]
    )
    bare_session = scenario.open_offer_session(
        bare_booking["id"], channel["id"], "BOOKING"
    )
    assert bare_session["candidate_count"] == 1, bare_session
    bare_offers = scenario.offers_for_booking(bare_booking["id"], channel["id"])
    assert len(bare_offers) == 1, bare_offers
    elastic = bare_offers[0]
    # Same product, same flight data, no open segment: the demand feed prices it.
    assert elastic["pricing_variant"] == "WTP_ELASTIC", elastic
    assert elastic["wtp_score_bp"] == 10000, elastic
    assert_money_field(elastic, "offered_price_cents", 4200)
    assert_money_field(elastic, "expected_value_cents", 4200)


def test_accepted_offer_keeps_its_pinned_price_through_a_demand_shift(api, scenario):
    """PRD §3.6: "On success, `accepted_price_cents` is frozen from
    `offered_price_cents`; one `SALE` revenue entry is posted whose `category` is the
    product's `category`, whose `gross_cents` is the accepted price, whose tax and
    reporting metadata are snapshotted from the product, and whose `source_ref` is
    `offer:` followed by the offer's id;"
    PRD §2.11: "Tax is derived per entry from the entry's `tax_treatment`, at a rate of
    750 basis points for `TAXABLE_TRANSPORT`, 400 basis points for `TAXABLE_SERVICE` and
    nothing at all for `EXEMPT`."
    PRD §2.10: "a booking's `recognized_ancillary_net_cents` always equals the signed sum
    of `net_cents` over that booking's revenue entries whose `category` is anything other
    than `AIR_TRANSPORT`"
    PRD §3.3: "Publishing a snapshot re-derives the flight's `demand_tier` — `HIGH` when
    `booked_load_factor_pct` is at least 80, `MID` when it is at least 60 but below 80,
    and `LOW` otherwise — and then reprices every seat segment on the flight, including
    segments already `CLOSED`, since a closed segment is still repriced even though it
    accepts no assignments."

    Design: Corner/calculations/accepted_offer_settles_at_its_pinned_price_after_a_demand_shift
    """
    bag = scenario.create_product(_checked_bag())
    seat = scenario.create_product(_standard_seat())
    change = scenario.create_product(factories.change_flex_product_payload())

    family = scenario.create_family(_merch_family())
    scenario.add_attribute(
        family["id"], change["id"], inclusion="INCLUDED", included_quantity=1
    )
    published = scenario.publish_family(family["id"])
    channel = scenario.create_channel(_direct_web_channel())
    scenario.publish_to_channel(family["id"], channel["id"], published["version"])

    flight = scenario.create_flight()
    scenario.post_demand(flight["id"], 50, 0)
    segment = scenario.create_segment(
        flight["id"],
        seat["id"],
        zone="MID",
        row_start=16,
        row_end=18,
        seat_letters=["A", "B", "C"],
        base_price_cents=2000,
    )
    # 2000 x 10000 MID x 10000 LOW / 100,000,000 = 2000
    assert_money_field(segment, "effective_price_cents", 2000)

    booking = scenario.create_booking(flight["id"], family["id"], channel["id"])
    scenario.open_offer_session(
        booking["id"], channel["id"], "BOOKING", requested_product_ids=[bag["id"]]
    )
    offers = scenario.offers_for_booking(booking["id"], channel["id"])
    assert len(offers) == 1, offers
    offer = offers[0]
    # 3500 list x 10000bp score x 10000bp BOOKING x 10000bp markup-free = 3500
    assert_money_field(offer, "offered_price_cents", 3500)
    assert offer["wtp_score_bp"] == 10000, offer

    held = scenario.get_booking(booking["id"], channel["id"])
    accepted = scenario.accept_offer(offer["id"], channel["id"], held["version"])
    assert accepted["offer_status"] == "ACCEPTED", accepted
    assert_money_field(accepted, "accepted_price_cents", 3500)

    # Demand now surges: the tier moves to HIGH and the seat map reprices.
    snapshot = scenario.post_demand(flight["id"], 90, 0)
    assert snapshot["demand_tier"] == "HIGH", snapshot
    repriced = scenario.get_segment(segment["id"])
    # 2000 x 10000 MID x 12500 HIGH / 100,000,000 = 2500
    assert_money_field(repriced, "effective_price_cents", 2500)

    after = validate_success(
        api.get_ancillary_offer(
            offer["id"], make_channel_partner_headers(channel["id"])
        )
    )
    assert after["offer_status"] == "ACCEPTED", after
    # A load factor of 90 would have scored 10000 + 40 x 40 = 11600bp and priced the
    # bag at 4060; the accepted offer keeps the 3500 it was sold at.
    assert after["wtp_score_bp"] == 10000, after
    assert_money_field(after, "offered_price_cents", 3500)
    assert_money_field(after, "accepted_price_cents", 3500)

    entries, meta = validate_paginated(
        api.list_booking_revenue_entries(booking["id"], REVENUE_ACCOUNTANT)
    )
    assert meta["total_count"] == 1, f"one acceptance, one sale row: {entries}"
    sale = find_one_entry(entries, entry_type="SALE", category="BAGGAGE")
    # 3500 x 400bp service tax = 140, so 3360 nets through
    assert_entry_amounts(sale, gross_cents=3500, tax_cents=140, net_cents=3360)
    assert sale["source_ref"] == f"offer:{offer['id']}", sale["source_ref"]

    settled = scenario.get_booking(booking["id"], channel["id"])
    assert_money_field(settled, "ancillary_gross_cents", 3500)
    assert_money_field(settled, "recognized_ancillary_net_cents", 3360)
