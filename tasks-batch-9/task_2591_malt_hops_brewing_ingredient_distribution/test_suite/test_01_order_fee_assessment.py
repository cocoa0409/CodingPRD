"""Order fee assessment: the two fee variants, per-line rounding, and the MOQ."""
import pytest

from test_helpers import (
    add_contract_hop_line,
    add_malt_line,
    approve_credit,
    assert_order_total_identity,
    confirm_order,
    create_brewer,
    create_contract,
    create_malt_product,
    create_order,
    create_program,
    create_released_lot,
    create_variety,
    create_zone,
    depart_shipment,
    get_brewer,
    make_brewer_headers,
    pick_order,
    pin_clock,
    stage_shipment,
    validate_success,
)


@pytest.fixture
def promotion_world():
    """A brewer 1,470 lbs short of the TIER_2 threshold, with a 2,530 lb order.

    The order carries one 880 lb CONTRACT Citra line at 285.50 cents (an exact
    pallet multiple) and one 1,650 lb Pale Ale Malt line at 68.50 cents (not a
    pallet multiple), so the order's own poundage is exactly what decides the
    freight tier between confirmation and delivery.
    """
    pin_clock()
    brewer = create_brewer(name="Ridgeline Brewing", credit_limit_cents=5000000,
                           cold_chain_certified=True, legacy_trailing_lbs=38000)
    program = create_program(crop_year=2026)
    variety = create_variety()
    product = create_malt_product()
    lot = create_released_lot(product["id"], quantity_lbs=20000)
    zone = create_zone()
    contract = create_contract(brewer["id"], variety["id"], program["id"],
                               contracted_lbs=5000, price_per_lb_cents=285.50)
    order = create_order(brewer["id"],
                         requested_ship_date="2026-10-15T00:00:00Z",
                         purchase_order_ref="PO-1001")
    hop_line = add_contract_hop_line(order["id"], brewer["id"], variety["id"],
                                     contract["id"], 880)
    malt_line = add_malt_line(order["id"], brewer["id"], lot["id"], 1650)
    return {
        "brewer": brewer, "variety": variety, "product": product, "lot": lot,
        "zone": zone, "contract": contract, "order": order,
        "hop_line": hop_line, "malt_line": malt_line,
    }


def test_provisional_variant_rates_freight_from_a_trailing_volume_excluding_this_order(
        api, promotion_world):
    """Confirmation prices freight at TIER_1 on 38,000 trailing pounds.

    PRD §3.8: "`PROVISIONAL` is applied at confirmation and reads the brewery's
    freight program tier from a trailing volume that **excludes** this order's
    own `chargeable_lbs`, because the order has not shipped and has not yet
    earned volume credit."

    Design: Difficulty/dual_variant_calc/order_fee_provisional_vs_final_freight_tier_self_promotion
    """
    world = promotion_world
    order = validate_success(api.confirm_order(
        world["order"]["id"], make_brewer_headers(world["brewer"]["id"])))

    assert order["fee_variant"] == "PROVISIONAL", (
        f"confirmation prices the PROVISIONAL variant, got {order['fee_variant']}")
    assert order["chargeable_lbs"] == 2530, (
        f"chargeable_lbs is 880 + 1650 = 2530, got {order['chargeable_lbs']}")
    assert order["freight_tier_applied"] == "TIER_1", (
        "38,000 trailing pounds without this order's 2,530 stays below the "
        f"40,000-pound threshold, got {order['freight_tier_applied']}")
    assert order["freight_cents"] == 48360, (
        "2530 * 12 = 30,360 rated freight beats the 25,000 TIER_1 minimum, then "
        f"the 18,000 reefer surcharge is added, got {order['freight_cents']}")
    assert order["pallet_break_fee_cents"] == 4500, (
        "only the 1,650 lb malt line breaks a pallet, got "
        f"{order['pallet_break_fee_cents']}")
    assert order["small_order_surcharge_cents"] == 0, (
        f"2,530 lbs is above the order minimum, got {order['small_order_surcharge_cents']}")
    assert order["volume_discount_cents"] == 0, (
        f"a 364,265-cent subtotal earns no discount, got {order['volume_discount_cents']}")
    assert order["total_cents"] == 417125, (
        f"PROVISIONAL total is 364265 + 48360 + 4500, got {order['total_cents']}")
    assert_order_total_identity(order)


def test_line_extended_cents_and_pallet_break_flags_build_the_confirmed_subtotal(
        api, promotion_world):
    """Each line rounds to whole cents and only the non-multiple line breaks a pallet.

    PRD §3.8: "Each line also gets a `pallet_break` flag, true when the line's
    applicable pallet quantity — the variety's `pallet_quantity_lbs` for hop
    lines, the malt product's `pallet_quantity_lbs` for malt lines, and absent
    for yeast lines — is greater than zero and the line's `quantity` is not an
    exact multiple of it."

    Design: Difficulty/dual_variant_calc/order_fee_provisional_vs_final_freight_tier_self_promotion
    """
    world = promotion_world
    hop_line = validate_success(api.get_order_line(
        world["hop_line"]["id"], make_brewer_headers(world["brewer"]["id"])))
    malt_line = validate_success(api.get_order_line(
        world["malt_line"]["id"], make_brewer_headers(world["brewer"]["id"])))

    assert hop_line["extended_cents"] == 251240, (
        f"880 * 285.50 = 251240, got {hop_line['extended_cents']}")
    assert malt_line["extended_cents"] == 113025, (
        f"1650 * 68.50 = 113025, got {malt_line['extended_cents']}")
    assert hop_line["pallet_break"] is False, (
        "880 lbs is an exact multiple of the variety's 880 lb pallet, got "
        f"{hop_line['pallet_break']}")
    assert malt_line["pallet_break"] is True, (
        "1,650 lbs is not an exact multiple of the product's 2,200 lb pallet, "
        f"got {malt_line['pallet_break']}")

    order = validate_success(api.confirm_order(
        world["order"]["id"], make_brewer_headers(world["brewer"]["id"])))
    assert order["subtotal_cents"] == 364265, (
        f"251240 + 113025 = 364265, got {order['subtotal_cents']}")
    assert order["requires_cold_chain"] is True, (
        "the Citra line requires cold storage, so the order does too, got "
        f"{order['requires_cold_chain']}")


def test_final_variant_promotes_the_order_into_tier_2_and_books_a_negative_adjustment(
        api, promotion_world, warehouse_operator_headers):
    """Delivery re-rates freight with the order's own poundage inside the window.

    PRD §3.8: "`FINAL` is applied at delivery and recomputes the tier with this
    order's own `chargeable_lbs` **included** in the trailing window, because a
    delivered order counts toward the program. A large order can therefore
    promote itself into a cheaper tier between confirmation and delivery."

    Design: Difficulty/dual_variant_calc/order_fee_provisional_vs_final_freight_tier_self_promotion
    """
    world = promotion_world
    brewer_id = world["brewer"]["id"]
    provisional = confirm_order(world["order"]["id"], brewer_id)
    assert provisional["total_cents"] == 417125

    approve_credit(world["order"]["id"])
    pick_order(world["order"]["id"])
    shipment = stage_shipment(world["order"]["id"], world["zone"]["id"],
                              pallet_count=3,
                              stage_from="2026-08-01T00:00:00Z",
                              stage_until="2026-08-02T00:00:00Z")
    depart_shipment(shipment["id"])
    validate_success(api.ship_order(world["order"]["id"],
                                    warehouse_operator_headers))
    delivered = validate_success(api.deliver_order(world["order"]["id"],
                                                   warehouse_operator_headers))

    assert delivered["fee_variant"] == "FINAL", (
        f"delivery prices the FINAL variant, got {delivered['fee_variant']}")
    assert delivered["freight_tier_applied"] == "TIER_2", (
        "38,000 + 2,530 = 40,530 trailing pounds reaches the 40,000-pound "
        f"threshold, got {delivered['freight_tier_applied']}")
    assert delivered["freight_cents"] == 38240, (
        "2530 * 8 = 20,240 beats the 15,000 TIER_2 minimum, then the 18,000 "
        f"reefer surcharge is added, got {delivered['freight_cents']}")
    assert delivered["total_cents"] == 407005, (
        f"FINAL total is 364265 + 38240 + 4500, got {delivered['total_cents']}")
    assert delivered["final_freight_adjustment_cents"] == -10120, (
        "407005 - 417125 = -10120 booked as the freight adjustment, got "
        f"{delivered['final_freight_adjustment_cents']}")
    assert_order_total_identity(delivered)


def test_delivery_re_rates_the_freight_program_and_settles_the_receivable(
        api, promotion_world, warehouse_operator_headers):
    """The delivered order's own poundage promotes the brewer's own tier too.

    PRD §3.1: "A brewery's `trailing_12mo_volume_lbs` is its
    `legacy_trailing_lbs` plus the sum of `chargeable_lbs` over its own orders
    whose `fulfillment_status` is `DELIVERED` and whose `delivered_at` falls
    inside the trailing 365-day window."

    Design: Difficulty/dual_variant_calc/order_fee_provisional_vs_final_freight_tier_self_promotion
    """
    world = promotion_world
    brewer_id = world["brewer"]["id"]
    confirm_order(world["order"]["id"], brewer_id)
    approve_credit(world["order"]["id"])
    pick_order(world["order"]["id"])
    shipment = stage_shipment(world["order"]["id"], world["zone"]["id"],
                              pallet_count=3,
                              stage_from="2026-08-01T00:00:00Z",
                              stage_until="2026-08-02T00:00:00Z")
    depart_shipment(shipment["id"])
    validate_success(api.ship_order(world["order"]["id"],
                                    warehouse_operator_headers))
    validate_success(api.deliver_order(world["order"]["id"],
                                       warehouse_operator_headers))

    brewer = get_brewer(brewer_id)
    assert brewer["trailing_12mo_volume_lbs"] == 40530, (
        "38,000 seeded pounds plus the delivered order's 2,530, got "
        f"{brewer['trailing_12mo_volume_lbs']}")
    assert brewer["freight_program_tier"] == "TIER_2", (
        "40,530 pounds reaches the 40,000-pound tier, got "
        f"{brewer['freight_program_tier']}")
    assert brewer["ar_balance_cents"] == 407005, (
        "the invoice booked 417125 and delivery booked -10120, got "
        f"{brewer['ar_balance_cents']}")


@pytest.fixture
def half_cent_order():
    """Two identical 55 lb Munich lines at 100.50 cents, each residing on a half cent."""
    pin_clock()
    brewer = create_brewer(name="Halfpenny Brewing", credit_limit_cents=5000000,
                           cold_chain_certified=False, legacy_trailing_lbs=0)
    product = create_malt_product(sku="MUNICH", name="Munich Malt",
                                  list_price_cents_per_lb=100.50,
                                  pallet_quantity_lbs=2200, min_order_lbs=55)
    lot = create_released_lot(product["id"], quantity_lbs=500,
                              color_lovibond=9.00, extract_pct=80.50,
                              moisture_pct=4.10, protein_pct=11.40,
                              diastatic_power=71.00)
    order = create_order(brewer["id"],
                         requested_ship_date="2026-09-15T00:00:00Z",
                         purchase_order_ref="PO-2001")
    line_a = add_malt_line(order["id"], brewer["id"], lot["id"], 55)
    line_b = add_malt_line(order["id"], brewer["id"], lot["id"], 55)
    return {"brewer": brewer, "product": product, "lot": lot, "order": order,
            "line_a": line_a, "line_b": line_b}


def test_each_line_rounds_to_whole_cents_before_the_subtotal_sums_them(
        api, half_cent_order):
    """Two 5527.5-cent lines round up individually and sum to 11056, not 11055.

    PRD §3.8: "**The rounding order is normative**: each line's `extended_cents`
    is rounded to whole cents first and the already-rounded per-line values are
    then summed. Summing the unrounded products and rounding once at the end is
    wrong and produces a different `subtotal_cents` whenever two or more lines
    each carry a half-cent residue."

    Design: Difficulty/combinatorial_formula/subtotal_rounds_each_line_before_summing_mode_b
    """
    world = half_cent_order
    brewer_headers = make_brewer_headers(world["brewer"]["id"])
    line_a = validate_success(api.get_order_line(world["line_a"]["id"],
                                                 brewer_headers))
    line_b = validate_success(api.get_order_line(world["line_b"]["id"],
                                                 brewer_headers))
    assert line_a["extended_cents"] == 5528, (
        f"55 * 100.50 = 5527.5 rounds half up to 5528, got {line_a['extended_cents']}")
    assert line_b["extended_cents"] == 5528, (
        f"the second identical line rounds the same way, got {line_b['extended_cents']}")

    order = validate_success(api.confirm_order(world["order"]["id"],
                                               brewer_headers))
    assert order["subtotal_cents"] == 11056, (
        f"5528 + 5528 = 11056, got {order['subtotal_cents']}")
    assert order["subtotal_cents"] != 11055, (
        "11055 would mean the unrounded 5527.5 values were summed and rounded once")
    assert order["chargeable_lbs"] == 110, (
        f"55 + 55 = 110 chargeable pounds, got {order['chargeable_lbs']}")


def test_fees_stack_on_the_rounded_subtotal_of_two_pallet_breaking_lines(
        api, half_cent_order):
    """Both lines break a pallet and the 110 lb order pays freight minimum and MOQ.

    PRD §3.8: "`pallet_break_fee_cents` is 4,500 cents multiplied by the number
    of lines in the roll-up input set whose `pallet_break` is true."

    Design: Difficulty/combinatorial_formula/subtotal_rounds_each_line_before_summing_mode_b
    """
    world = half_cent_order
    brewer_headers = make_brewer_headers(world["brewer"]["id"])
    order = validate_success(api.confirm_order(world["order"]["id"],
                                               brewer_headers))

    assert order["volume_discount_cents"] == 0, (
        f"an 11,056-cent subtotal earns no discount, got {order['volume_discount_cents']}")
    assert order["freight_tier_applied"] == "TIER_1", (
        f"zero trailing volume rates at TIER_1, got {order['freight_tier_applied']}")
    assert order["freight_cents"] == 25000, (
        "110 * 12 = 1,320 loses to the 25,000 TIER_1 minimum and no reefer "
        f"surcharge applies, got {order['freight_cents']}")
    assert order["pallet_break_fee_cents"] == 9000, (
        f"two pallet-breaking lines at 4,500 each, got {order['pallet_break_fee_cents']}")
    assert order["small_order_surcharge_cents"] == 7500, (
        f"110 lbs is far below the 2,000 lb order minimum, got "
        f"{order['small_order_surcharge_cents']}")
    assert order["total_cents"] == 52556, (
        f"11056 + 25000 + 9000 + 7500 = 52556, got {order['total_cents']}")
    assert_order_total_identity(order)

    line_a = validate_success(api.get_order_line(world["line_a"]["id"],
                                                 brewer_headers))
    line_b = validate_success(api.get_order_line(world["line_b"]["id"],
                                                 brewer_headers))
    assert line_a["pallet_break"] is True and line_b["pallet_break"] is True, (
        "55 lbs is not a multiple of the 2,200 lb pallet on either line")


@pytest.fixture
def moq_pair():
    """Two malt-only orders straddling the 2,000 lb order minimum by one pound."""
    pin_clock()
    brewer = create_brewer(name="Threshold Brewing", credit_limit_cents=5000000,
                           cold_chain_certified=False, legacy_trailing_lbs=0)
    product = create_malt_product()
    lot = create_released_lot(product["id"], quantity_lbs=20000)

    at_moq = create_order(brewer["id"],
                          requested_ship_date="2026-09-20T00:00:00Z",
                          purchase_order_ref="PO-AT-MOQ")
    add_malt_line(at_moq["id"], brewer["id"], lot["id"], 1000)
    add_malt_line(at_moq["id"], brewer["id"], lot["id"], 1000)

    below_moq = create_order(brewer["id"],
                             requested_ship_date="2026-09-20T00:00:00Z",
                             purchase_order_ref="PO-BELOW-MOQ")
    line_999 = add_malt_line(below_moq["id"], brewer["id"], lot["id"], 999)
    add_malt_line(below_moq["id"], brewer["id"], lot["id"], 1000)
    return {"brewer": brewer, "lot": lot, "at_moq": at_moq,
            "below_moq": below_moq, "line_999": line_999}


def test_chargeable_pounds_exactly_at_the_order_minimum_escape_the_surcharge(
        api, moq_pair):
    """2,000 chargeable pounds is not strictly below 2,000, so no surcharge.

    PRD §3.8: "`small_order_surcharge_cents` is 7,500 cents when
    `chargeable_lbs` is strictly below the order minimum of 2,000 pounds, and 0
    otherwise."

    Design: Difficulty/boundary_precision_check/moq_surcharge_at_exactly_two_thousand_chargeable_pounds
    """
    world = moq_pair
    order = validate_success(api.confirm_order(
        world["at_moq"]["id"], make_brewer_headers(world["brewer"]["id"])))

    assert order["chargeable_lbs"] == 2000, (
        f"1000 + 1000 = 2000 chargeable pounds, got {order['chargeable_lbs']}")
    assert order["small_order_surcharge_cents"] == 0, (
        "exactly at the minimum is not strictly below it, got "
        f"{order['small_order_surcharge_cents']}")
    assert order["subtotal_cents"] == 137000, (
        f"two 68,500-cent lines, got {order['subtotal_cents']}")
    assert order["requires_cold_chain"] is False, (
        "a malt-only order needs no reefer, so no 18,000 surcharge hides inside "
        f"freight, got {order['requires_cold_chain']}")
    assert order["freight_cents"] == 25000, (
        f"2000 * 12 = 24,000 loses to the 25,000 minimum, got {order['freight_cents']}")
    assert order["pallet_break_fee_cents"] == 9000, (
        f"neither 1,000 lb line fills a 2,200 lb pallet, got "
        f"{order['pallet_break_fee_cents']}")
    assert order["total_cents"] == 171000, (
        f"137000 + 25000 + 9000 = 171000, got {order['total_cents']}")


def test_one_pound_below_the_order_minimum_adds_the_surcharge_and_rounds_its_line_up(
        api, moq_pair):
    """1,999 chargeable pounds pays 7,500, and the 999 lb line rounds to 68432.

    PRD §3.8: "Eleventh, `small_order_surcharge_cents` is 7,500 cents when
    `chargeable_lbs` is strictly below the order minimum of 2,000 pounds, and 0
    otherwise."

    Design: Difficulty/boundary_precision_check/moq_surcharge_at_exactly_two_thousand_chargeable_pounds
    """
    world = moq_pair
    brewer_headers = make_brewer_headers(world["brewer"]["id"])
    at_moq = validate_success(api.confirm_order(world["at_moq"]["id"],
                                                brewer_headers))
    below = validate_success(api.confirm_order(world["below_moq"]["id"],
                                               brewer_headers))
    line_999 = validate_success(api.get_order_line(world["line_999"]["id"],
                                                   brewer_headers))

    assert below["chargeable_lbs"] == 1999, (
        f"999 + 1000 = 1999 chargeable pounds, got {below['chargeable_lbs']}")
    assert line_999["extended_cents"] == 68432, (
        f"999 * 68.50 = 68431.5 rounds half up to 68432, got "
        f"{line_999['extended_cents']}")
    assert below["subtotal_cents"] == 136932, (
        f"68432 + 68500 = 136932, got {below['subtotal_cents']}")
    assert below["small_order_surcharge_cents"] == 7500, (
        f"1,999 is strictly below the 2,000 lb minimum, got "
        f"{below['small_order_surcharge_cents']}")
    assert below["freight_cents"] == 25000, (
        f"1999 * 12 = 23,988 loses to the 25,000 minimum, got {below['freight_cents']}")
    assert below["total_cents"] == 178432, (
        f"136932 + 25000 + 9000 + 7500 = 178432, got {below['total_cents']}")
    assert below["total_cents"] - at_moq["total_cents"] == 7432, (
        "dropping one pound costs 7,500 in surcharge less the 68 cents of goods "
        f"no longer sold, got {below['total_cents'] - at_moq['total_cents']}")
