"""Dynamic ticket pricing and pass-discount calculations.

Covers demand-band selection (LOW/MID/HIGH) on confirm, the inclusive HIGH
boundary, and per-line-item pass-discount rounding.
"""
import pytest
from test_helpers import (
    api_client, get_success_data, validate_success,
    setup_priced_ticket_at_demand_ratio, setup_venue_attraction_slot,
    create_pass_product, issue_pass, create_reservation, add_ticket,
    confirm_reservation, create_guest, confirm_payload, get_slot_version,
    TEST_USERS,
)

BOX = TEST_USERS["box_office_headers"]

# Pricing bands pinned to the canonical defaults (base 2410, low_max 0.5,
# high_min 0.8, mid 20%, high 50%).
BANDS = {
    "low_demand_max_ratio": 0.5,
    "high_demand_min_ratio": 0.8,
    "mid_surge_pct": 20,
    "high_surge_pct": 50,
}


def test_ticket_price_low_band_no_surge_at_zero_demand(api):
    """PRD 3.2: "if the ratio is at or below the rule's low_demand_max_ratio, no
    surge applies". PRD 3.6: "The frozen price_cents is the rule's base_price_cents
    multiplied by one hundred plus the chosen surge percentage, divided by one
    hundred, then rounded half up to a whole cent."

    A GA ticket confirmed on a fresh slot (demand_ratio 0, LOW band) freezes at the
    base price 2410 with no surge.

    Design: Difficulty/dual_variant_calc/dvc_dynamic_price_low_vs_high_band_on_ticket
    """
    venue, attraction, slot, reservation, ticket = setup_priced_ticket_at_demand_ratio(
        preload_members=0, capacity=10, pricing_overrides=BANDS
    )
    confirm_reservation(reservation["id"], slot["id"])
    priced = validate_success(api.get_ticket(ticket["id"], BOX), 200)
    assert priced["price_cents"] == 2410, (
        f"LOW band: expected base 2410, got {priced['price_cents']}"
    )


def test_ticket_price_high_band_surge_at_demand_ratio_080(api):
    """PRD 3.2: "if the ratio is at or above the rule's high_demand_min_ratio, the
    high surge applies". PRD 3.6: "The frozen price_cents is the rule's
    base_price_cents multiplied by one hundred plus the chosen surge percentage,
    divided by one hundred, then rounded half up to a whole cent."

    Slot capacity 5 pre-loaded to reserved_count 4 (demand_ratio 0.8 == high_min)
    yields the HIGH band: 2410 * 150 / 100 = 3615.

    Design: Difficulty/dual_variant_calc/dvc_dynamic_price_low_vs_high_band_on_ticket
    """
    venue, attraction, slot, reservation, ticket = setup_priced_ticket_at_demand_ratio(
        preload_members=4, capacity=5, pricing_overrides=BANDS
    )
    confirm_reservation(reservation["id"], slot["id"])
    priced = validate_success(api.get_ticket(ticket["id"], BOX), 200)
    assert priced["price_cents"] == 3615, (
        f"HIGH band: expected 3615, got {priced['price_cents']}"
    )


def test_ticket_price_mid_band_surge_at_demand_ratio_060(api):
    """PRD 3.2: "otherwise — strictly between the two bounds — the mid surge
    applies". PRD 3.6: "The frozen price_cents is the rule's base_price_cents
    multiplied by one hundred plus the chosen surge percentage, divided by one
    hundred, then rounded half up to a whole cent."

    Slot capacity 5 pre-loaded to reserved_count 3 (demand_ratio 0.6, MID band)
    yields 2410 * 120 / 100 = 2892.

    Design: Difficulty/combinatorial_formula/cf_mode_a_tiered_surge_selection_three_inputs
    """
    venue, attraction, slot, reservation, ticket = setup_priced_ticket_at_demand_ratio(
        preload_members=3, capacity=5, pricing_overrides=BANDS
    )
    confirm_reservation(reservation["id"], slot["id"])
    priced = validate_success(api.get_ticket(ticket["id"], BOX), 200)
    assert priced["price_cents"] == 2892, (
        f"MID band: expected 2892, got {priced['price_cents']}"
    )


def test_mid_band_distinct_from_high_band(api):
    """PRD 3.2: "a ratio exactly equal to high_demand_min_ratio is treated as HIGH."
    PRD 3.2: "otherwise — strictly between the two bounds — the mid surge applies".

    The same base 2410 produces 2892 at the MID snapshot 0.6 but 3615 at the HIGH
    snapshot 0.8, confirming the three-input band selection diverges by ratio.

    Design: Difficulty/combinatorial_formula/cf_mode_a_tiered_surge_selection_three_inputs
    """
    _, _, mid_slot, mid_res, mid_ticket = setup_priced_ticket_at_demand_ratio(
        preload_members=3, capacity=5, pricing_overrides=BANDS
    )
    confirm_reservation(mid_res["id"], mid_slot["id"])
    mid_priced = validate_success(api.get_ticket(mid_ticket["id"], BOX), 200)

    _, _, high_slot, high_res, high_ticket = setup_priced_ticket_at_demand_ratio(
        preload_members=4, capacity=5, pricing_overrides=BANDS
    )
    confirm_reservation(high_res["id"], high_slot["id"])
    high_priced = validate_success(api.get_ticket(high_ticket["id"], BOX), 200)

    assert mid_priced["price_cents"] == 2892
    assert high_priced["price_cents"] == 3615
    assert mid_priced["price_cents"] != high_priced["price_cents"]


def test_high_band_inclusive_at_exactly_high_min_ratio(api):
    """PRD 3.2: "a ratio exactly equal to high_demand_min_ratio is treated as HIGH."
    PRD 3.6: "The frozen price_cents is the rule's base_price_cents multiplied by one
    hundred plus the chosen surge percentage, divided by one hundred, then rounded
    half up to a whole cent."

    demand_ratio exactly 0.8 (== high_demand_min_ratio) selects the HIGH band:
    2410 -> 3615 (inclusive >= boundary).

    Design: Difficulty/boundary_precision_check/bpc_demand_ratio_high_band_inclusive_at_080
    """
    venue, attraction, slot, reservation, ticket = setup_priced_ticket_at_demand_ratio(
        preload_members=4, capacity=5, pricing_overrides=BANDS
    )
    confirm_reservation(reservation["id"], slot["id"])
    priced = validate_success(api.get_ticket(ticket["id"], BOX), 200)
    assert priced["price_cents"] == 3615, (
        f"ratio 0.8 is inclusive HIGH: expected 3615, got {priced['price_cents']}"
    )


def test_high_band_boundary_distinct_from_mid_band(api):
    """PRD 3.2: "The boundaries are precise: a ratio exactly equal to
    low_demand_max_ratio is treated as LOW, and a ratio exactly equal to
    high_demand_min_ratio is treated as HIGH."

    At ratio 0.8 the price is the HIGH 3615; at ratio 0.6 it would be the MID 2892 —
    the inclusive boundary is what makes 0.8 a HIGH-band selection.

    Design: Difficulty/boundary_precision_check/bpc_demand_ratio_high_band_inclusive_at_080
    """
    _, _, high_slot, high_res, high_ticket = setup_priced_ticket_at_demand_ratio(
        preload_members=4, capacity=5, pricing_overrides=BANDS
    )
    confirm_reservation(high_res["id"], high_slot["id"])
    high_priced = validate_success(api.get_ticket(high_ticket["id"], BOX), 200)

    _, _, mid_slot, mid_res, mid_ticket = setup_priced_ticket_at_demand_ratio(
        preload_members=3, capacity=5, pricing_overrides=BANDS
    )
    confirm_reservation(mid_res["id"], mid_slot["id"])
    mid_priced = validate_success(api.get_ticket(mid_ticket["id"], BOX), 200)

    assert high_priced["price_cents"] == 3615
    assert mid_priced["price_cents"] == 2892


def test_group_pass_discount_rounds_per_ticket_then_sums(api):
    """PRD 3.6: "Otherwise the discount is computed per line item and then summed:
    for each ticket, multiply its frozen price_cents by the product's discount_pct,
    divide by one hundred, and round half up to a whole cent; the discount_cents is
    the sum of those per-ticket rounded amounts."

    Three GA tickets at 2410 each with a GROUP 15% pass: round(361.5)=362 per ticket,
    summed to 1086; subtotal 7230, total 6144 (sum-then-round would give 1085/6145).

    Design: Difficulty/combinatorial_formula/cf_mode_b_pass_discount_round_per_ticket_then_sum
    """
    venue, attraction, slot = setup_venue_attraction_slot(
        slot_overrides={"capacity": 10}, pricing_overrides=BANDS
    )
    product = create_pass_product(
        venue["id"], kind="GROUP", price_cents=0, discount_pct=15,
        max_redemptions=2, min_party=3,
    )
    guest = create_guest(full_name="Group Buyer", email="grp@x.com")
    pass_ = issue_pass(product["id"], guest["id"])
    reservation = create_reservation(venue["id"], guest["id"], pass_id=pass_["id"])
    for _ in range(3):
        add_ticket(reservation["id"], slot["id"], tier="GA")

    confirmed = confirm_reservation(reservation["id"], slot["id"])
    assert confirmed["subtotal_cents"] == 7230, f"subtotal {confirmed['subtotal_cents']}"
    assert confirmed["discount_cents"] == 1086, (
        f"per-line rounded discount expected 1086, got {confirmed['discount_cents']}"
    )
    assert confirmed["total_cents"] == 6144, f"total {confirmed['total_cents']}"


def test_per_line_rounding_yields_total_distinct_from_sum_then_round(api):
    """PRD 3.6: "This per-line rounding is deliberate — rounding each ticket before
    summing yields a different total than summing first and rounding once, and the
    former is the specified behaviour."

    The per-line discount 1086 (total 6144) is exactly one cent away from the
    sum-then-round discount 1085 (total 6145), proving the pinned rounding order.

    Design: Difficulty/combinatorial_formula/cf_mode_b_pass_discount_round_per_ticket_then_sum
    """
    venue, attraction, slot = setup_venue_attraction_slot(
        slot_overrides={"capacity": 10}, pricing_overrides=BANDS
    )
    product = create_pass_product(
        venue["id"], kind="GROUP", price_cents=0, discount_pct=15,
        max_redemptions=2, min_party=3,
    )
    guest = create_guest(full_name="Group Buyer", email="grp2@x.com")
    pass_ = issue_pass(product["id"], guest["id"])
    reservation = create_reservation(venue["id"], guest["id"], pass_id=pass_["id"])
    for _ in range(3):
        add_ticket(reservation["id"], slot["id"], tier="GA")

    confirmed = confirm_reservation(reservation["id"], slot["id"])
    # Per-line: 3 * round(2410*0.15) = 3 * 362 = 1086. Sum-then-round would be
    # round(7230*0.15) = round(1084.5) = 1085. The contract pins the former.
    assert confirmed["discount_cents"] == 1086
    assert confirmed["total_cents"] == 6144


def test_group_pass_discount_zero_when_party_below_min_party(api):
    """PRD 3.6: "If the pass's product is of GROUP kind and the reservation's
    party_size is below the product's min_party, the discount is zero."

    A GROUP pass with min_party 3 applied to a single-ticket reservation yields
    discount_cents 0; total equals subtotal 2410.

    Design: Corner/calculations/pass_discount_zero_when_group_min_party_not_met
    """
    venue, attraction, slot = setup_venue_attraction_slot(slot_overrides={"capacity": 10})
    product = create_pass_product(
        venue["id"], kind="GROUP", price_cents=0, discount_pct=15,
        max_redemptions=2, min_party=3,
    )
    guest = create_guest(full_name="Solo", email="solo@x.com")
    pass_ = issue_pass(product["id"], guest["id"])
    reservation = create_reservation(venue["id"], guest["id"], pass_id=pass_["id"])
    add_ticket(reservation["id"], slot["id"], tier="GA")

    confirmed = confirm_reservation(reservation["id"], slot["id"])
    assert confirmed["subtotal_cents"] == 2410
    assert confirmed["discount_cents"] == 0, "GROUP min_party unmet -> no discount"
    assert confirmed["total_cents"] == 2410
