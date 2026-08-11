"""Volume-estimate variants, the travel bands, the coordination-fee caps and the
two vendor payout variants."""

from test_helpers import (
    BILLING_ADMIN,
    COORD_FEE_TIER2_CAP_CENTS,
    MOVE_MANAGER,
    PACKAGE_BASE_CENTS,
    api_client,
    append_manual_line,
    assert_exactly_one_line,
    assert_money,
    assert_two_dp,
    assert_vendor_payout_conservation,
    accept_vendor_assignment,
    coordination_fee_cents,
    heuristic_volume_cft,
    invoice_lines,
    invoice_of,
    make_vendor_headers,
    new_client,
    new_engagement,
    new_item,
    new_vendor,
    new_vendor_assignment,
    read_engagement,
    read_invoice,
    read_summary,
    read_vendor_assignment,
    schedule_vendor_assignment,
    set_clock,
    setup_engagement,
    travel_surcharge_cents,
    validate_paginated,
    validate_success,
)


def test_the_empty_catalogue_selects_the_assessment_heuristic():
    """PRD §3.1: "The volume estimate has two variants and the switch between them is
    the catalogue itself: while `inventory_item_count` is 0 the assessment heuristic
    applies, multiplying a per-tier room count — 2 rooms for `STUDIO`, 3 for
    `ONE_BED`, 5 for `TWO_BED` and 8 for `HOUSE` — by 180 cubic feet per room, which
    can be wildly wrong for a heavy downsizer"

    Design: Corner/calculations/volume_estimate_uses_the_assessment_heuristic_while_the_catalogue_is_empty
    """
    world = setup_engagement(
        with_client_party=False, mileage_miles=15, origin_stairs_flights=1, origin_long_carry_feet=75
    )
    summary = read_summary(world["engagement_id"])
    assert_two_dp(
        summary["volume_estimate_cft"], heuristic_volume_cft("STUDIO"), "volume_estimate_cft"
    )
    engagement = read_engagement(world["engagement_id"])
    assert engagement["inventory_item_count"] == 0
    assert_two_dp(engagement["total_inventory_volume_cft"], 0.00, "total_inventory_volume_cft")


def test_the_first_catalogued_item_switches_the_estimate_to_the_inventory_rollup():
    """PRD §3.1: "from the first catalogued item onward the inventory rollup applies,
    summing `volume_cft` across every item of the engagement regardless of
    disposition or handling state, which is exactly what `total_inventory_volume_cft`
    stores"

    Design: Corner/calculations/volume_estimate_switches_to_the_inventory_rollup_on_the_first_item
    """
    world = setup_engagement(
        with_client_party=False, mileage_miles=15, origin_stairs_flights=1, origin_long_carry_feet=75
    )
    new_item(
        world["engagement_id"], label="Walnut sideboard", footprint_linear_inches=60, volume_cft=42.5
    )
    summary = read_summary(world["engagement_id"])
    assert_two_dp(summary["volume_estimate_cft"], 42.50, "volume_estimate_cft")

    engagement = read_engagement(world["engagement_id"])
    assert engagement["inventory_item_count"] == 1
    assert_two_dp(engagement["total_inventory_volume_cft"], 42.50, "total_inventory_volume_cft")
    assert_two_dp(engagement["keep_volume_cft"], 0.00, "keep_volume_cft while still UNDECIDED")


def test_exactly_forty_miles_stays_inside_the_first_travel_band():
    """PRD §3.11: "The miles from there up to forty are charged at 317 cents each —
    that is, the lesser of the mileage and forty, less fifteen, floored at zero. Every
    mile beyond forty is charged at 486 cents — the mileage less forty, floored at zero."

    Design: Corner/calculations/travel_surcharge_at_exactly_forty_miles_stays_inside_band_one
    """
    world = setup_engagement(
        with_client_party=False, mileage_miles=40, origin_stairs_flights=1, origin_long_carry_feet=75
    )
    expected_travel = travel_surcharge_cents(40)
    summary = read_summary(world["engagement_id"])
    assert_money(
        summary["projected_total_cents"],
        expected_travel + coordination_fee_cents(expected_travel),
        "projected_total_cents",
    )
    assert summary["billing_mode"] == "HOURLY"
    assert_money(summary["accrued_labor_cents"], 0, "accrued_labor_cents")
    assert_money(
        read_invoice(invoice_of(world["engagement_id"])["id"])["subtotal_cents"],
        0,
        "subtotal_cents before any line is written",
    )


def test_the_forty_first_mile_opens_the_second_travel_band_marginally():
    """PRD §3.11: "The travel surcharge is marginal, not average. The first fifteen
    miles of the engagement's `mileage_miles` are free."
    PRD §3.11: "Each band is rounded half-up to whole cents separately and the two
    results are then added."

    Design: Corner/calculations/travel_surcharge_at_forty_one_miles_opens_band_two
    """
    world = setup_engagement(
        with_client_party=False, mileage_miles=41, origin_stairs_flights=1, origin_long_carry_feet=75
    )
    at_forty_one = travel_surcharge_cents(41)
    at_forty = travel_surcharge_cents(40)
    expected_total = at_forty_one + coordination_fee_cents(at_forty_one)
    baseline_total = at_forty + coordination_fee_cents(at_forty)

    summary = read_summary(world["engagement_id"])
    assert_money(summary["projected_total_cents"], expected_total, "projected_total_cents")
    assert expected_total - baseline_total == (at_forty_one - at_forty) + (
        coordination_fee_cents(at_forty_one) - coordination_fee_cents(at_forty)
    )


def _package_house_engagement_with_a_manual_line(amount_cents):
    set_clock("2026-05-02T09:00:00.000Z")
    client = new_client(email=None)
    engagement = new_engagement(
        client["id"],
        billing_mode="PACKAGE",
        package_tier="HOUSE",
        home_tier="HOUSE",
        mileage_miles=15,
        origin_stairs_flights=1,
        origin_long_carry_feet=75,
    )
    invoice = invoice_of(engagement["id"])
    append_manual_line(invoice["id"], amount_cents, "Packing materials and specialty crating")
    return engagement, invoice


def test_the_tier_two_cap_binds_at_exactly_eight_hundred_thousand():
    """PRD §3.11: "Second the tier is keyed on that pre-fee `subtotal_cents`, never
    on `total_cents`: a subtotal of at most 300000 cents takes a cap of 18000, a
    subtotal above that but at most 800000 takes a cap of 42000, and anything above
    800000 takes a cap of 75000."

    Design: Corner/calculations/coordination_fee_tier_two_cap_binds_at_exactly_eight_hundred_thousand
    """
    engagement, invoice = _package_house_engagement_with_a_manual_line(
        800000 - PACKAGE_BASE_CENTS["HOUSE"]
    )
    assert_money(read_invoice(invoice["id"])["subtotal_cents"], 800000, "subtotal_cents")

    summary = read_summary(engagement["id"])
    assert coordination_fee_cents(800000) == COORD_FEE_TIER2_CAP_CENTS
    assert_money(
        summary["projected_total_cents"],
        800000 + COORD_FEE_TIER2_CAP_CENTS,
        "projected_total_cents",
    )


def test_one_cent_above_the_tier_two_edge_makes_the_fee_jump():
    """PRD §3.11: "Because the caps are flat, the fee is not monotone across the
    tier-two boundary: a subtotal of 800000 pays 42000 while a subtotal of 800001
    pays 48000."

    Design: Corner/calculations/coordination_fee_is_non_monotone_one_cent_above_the_tier_two_edge
    """
    engagement, invoice = _package_house_engagement_with_a_manual_line(
        800000 - PACKAGE_BASE_CENTS["HOUSE"]
    )
    append_manual_line(invoice["id"], 1, "Rounding adjustment")

    assert_money(read_invoice(invoice["id"])["subtotal_cents"], 800001, "subtotal_cents")
    summary = read_summary(engagement["id"])
    assert_money(
        summary["projected_total_cents"],
        800001 + coordination_fee_cents(800001),
        "projected_total_cents",
    )
    assert (
        800001 + coordination_fee_cents(800001)
    ) - (800000 + coordination_fee_cents(800000)) == 6001

    _, meta = validate_paginated(
        api_client.list_invoice_lines(BILLING_ADMIN, params={"invoice_id": invoice["id"]})
    )
    assert meta["total_count"] == 3


def _scheduled_junk_haul_order():
    world = setup_engagement()
    vendor = new_vendor("Bayside Junk Haul", "JUNK_HAUL", "2026-12-31")
    order = new_vendor_assignment(
        world["engagement_id"], vendor["id"], "HAUL_AWAY", "2026-06-15", 45000
    )
    accept_vendor_assignment(order["id"], vendor["id"])
    schedule_vendor_assignment(order["id"])
    set_clock("2026-06-15T10:00:00.000Z")
    world["vendor"] = vendor
    world["order"] = order
    return world


def test_the_interim_payout_withholds_the_holdback_at_performance():
    """PRD §3.8: "It stamps `performed_at_utc`, sets `paid_cents` to the interim
    payout — the `quoted_cents` less the `holdback_cents` — and appends a
    `VENDOR_PASSTHROUGH` ledger line for the full `quoted_cents` to the engagement's
    invoice, recomputing the invoice totals."
    PRD §2.11: "For every vendor assignment in status `PERFORMED`, `SIGNED_OFF` or
    `PAID`, `paid_cents` plus the outstanding holdback — that is `holdback_cents`
    when `holdback_released` is false, and zero once it is true — always equals
    `quoted_cents`."

    Design: Corner/calculations/vendor_payout_interim_variant_withholds_the_holdback_at_perform
    """
    world = _scheduled_junk_haul_order()
    performed = validate_success(
        api_client.perform_vendor_assignment(
            world["order"]["id"],
            {"performed_at_utc": "2026-06-15T10:00:00.000Z"},
            make_vendor_headers(world["vendor"]["id"]),
        )
    )
    assert performed["status"] == "PERFORMED"
    assert_money(performed["holdback_cents"], 4500, "holdback_cents")
    assert_money(performed["paid_cents"], 40500, "interim paid_cents")
    assert performed["holdback_released"] is False
    assert_vendor_payout_conservation(performed)

    invoice = invoice_of(world["engagement_id"])
    assert_exactly_one_line(invoice_lines(invoice["id"]), "VENDOR_PASSTHROUGH", 45000)
    assert_money(read_invoice(invoice["id"])["subtotal_cents"], 45000, "subtotal_cents")


def test_sign_off_moves_the_holdback_between_buckets_without_a_new_ledger_line():
    """PRD §2.11: "Sign-off moves money from the holdback bucket to the paid bucket;
    it never creates or destroys any."
    PRD §3.8: "Sign-off follows: the move manager, the client or a power of attorney
    supplies a `signed_off_by_party_id` that must resolve to a seat on the same
    engagement, `holdback_released` becomes true and `paid_cents` becomes the final
    payout, the full `quoted_cents`."

    Design: Corner/calculations/vendor_payout_final_variant_releases_the_holdback_at_sign_off
    """
    world = _scheduled_junk_haul_order()
    validate_success(
        api_client.perform_vendor_assignment(
            world["order"]["id"],
            {"performed_at_utc": "2026-06-15T10:00:00.000Z"},
            make_vendor_headers(world["vendor"]["id"]),
        )
    )
    signed = validate_success(
        api_client.sign_off_vendor_assignment(
            world["order"]["id"],
            {"signed_off_by_party_id": world["client_party"]["id"]},
            MOVE_MANAGER,
        )
    )
    assert signed["status"] == "SIGNED_OFF"
    assert_money(signed["paid_cents"], 45000, "final paid_cents")
    assert signed["holdback_released"] is True
    assert_money(signed["holdback_cents"], 4500, "holdback_cents is unchanged")
    assert_money(signed["quoted_cents"], 45000, "quoted_cents")
    assert_vendor_payout_conservation(signed)

    invoice = invoice_of(world["engagement_id"])
    _, meta = validate_paginated(
        api_client.list_invoice_lines(BILLING_ADMIN, params={"invoice_id": invoice["id"]})
    )
    assert meta["total_count"] == 1
    assert_money(read_invoice(invoice["id"])["subtotal_cents"], 45000, "subtotal_cents")
