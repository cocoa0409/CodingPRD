"""Event-day pricing and order-total (round-per-line) calculations.

Queue A (Difficulty): combinatorial_formula instances.
Queue B (Corner): calculations/pricing_off_peak_base_value.
"""
import pytest
from test_helpers import (
    api_client, validate_success,
    create_venue, create_product, setup_cart_order, make_patron_headers,
    TEST_USERS, create_menu_item_payload,
)
from test_helpers.fixtures import (
    create_event_doors_open, create_stand_opened_with_staff, setup_sellable_stand,
)

MANAGER = TEST_USERS["manager_headers"]


# ===========================================================================
# Queue A — event_day_pricing_multiplicative_surge_selection
# Off-peak HIGH price 1326 = round(850*1.20*1.30); peak 1428 = round(850*1.20*1.40).
# ===========================================================================
def test_event_day_price_picks_up_peak_bonus_on_window_open(api):
    """PRD §3.4: "if and only if the event's peak window is open, a peak bonus of
    10 is added to that surge percentage."
    PRD §3.3: "opening the peak window triggers a two-part cascade: the event-day
    price (price_cents) is recomputed for every menu item under every stand of the
    event, picking up the peak surge bonus".

    base 850, mult 120, HIGH tier 130 + peak bonus 10 = 140 -> round(850*1.20*1.40)=1428.

    Design: Difficulty/combinatorial_formula/event_day_pricing_multiplicative_surge_selection
    """
    venue = create_venue(venue_share_pct=10, service_fee_pct=0)
    product = create_product(venue["id"], sku="HOTDOG", name="Hot Dog", base_price_cents=850, unit_cost_cents=200)
    base = create_stand_opened_with_staff(
        venue_id=venue["id"],
        event_overrides={"event_multiplier_pct": 120},
        stand_overrides={"demand_tier": "HIGH", "expected_orders_per_hour": 160},
    )
    mi = validate_success(api.create_menu_item(create_menu_item_payload(base["stand"]["id"], product["id"]), MANAGER), 201)
    api.open_peak_window(base["event"]["id"], MANAGER)
    data = validate_success(api.get_menu_item(mi["id"], MANAGER), 200)
    assert data["price_cents"] == 1428, f"expected 1428 (peak), got {data['price_cents']}"


def test_event_day_price_off_peak_high_tier_multiplicative_chain(api):
    """PRD §3.4: "a surge percentage is selected from the demand tier — 100 for a
    LOW stand, 115 for a MID stand, and 130 for a HIGH stand".
    PRD §3.4: "The raw price is then the product's base price multiplied by the
    event multiplier expressed as a fraction (the multiplier percentage divided by
    100) and again by the surge percentage expressed as a fraction".

    Off-peak HIGH: base 850, mult 120, surge 130 -> round(850*1.20*1.30)=1326.

    Design: Difficulty/combinatorial_formula/event_day_pricing_multiplicative_surge_selection
    """
    venue = create_venue(venue_share_pct=10, service_fee_pct=0)
    product = create_product(venue["id"], sku="HOTDOG", name="Hot Dog", base_price_cents=850, unit_cost_cents=200)
    base = create_event_doors_open(venue["id"], event_multiplier_pct=120)
    # create_event_doors_open builds a default MID stand; create a HIGH stand explicitly.
    stand = validate_success(api.create_stand({"event_id": base["event"]["id"], "name": "HighStand",
                                               "demand_tier": "HIGH", "expected_orders_per_hour": 40}, MANAGER), 201)
    data = validate_success(api.create_menu_item(create_menu_item_payload(stand["id"], product["id"]), MANAGER), 201)
    assert data["price_cents"] == 1326, f"expected 1326 (off-peak), got {data['price_cents']}"


# ===========================================================================
# Queue B — calculations/pricing_off_peak_base_value (same off-peak HIGH formula,
# pinning the no-bonus branch independently of the difficulty instance).
# ===========================================================================
def test_pricing_off_peak_base_value_high_tier(api):
    """PRD §3.4: "The menu item's price_cents is that raw value rounded half-up to
    whole cents, with the rounding applied exactly once at the very end of the full
    multiplicative chain rather than at any intermediate step."

    base 850, mult 120, HIGH tier 130, no peak -> round(850*1.20*1.30)=1326.

    Design: Corner/calculations/pricing_off_peak_base_value
    """
    venue = create_venue(venue_share_pct=10, service_fee_pct=0)
    product = create_product(venue["id"], sku="HOTDOG", name="Hot Dog", base_price_cents=850, unit_cost_cents=200)
    base = create_event_doors_open(venue["id"], event_multiplier_pct=120)
    stand = validate_success(api.create_stand({"event_id": base["event"]["id"], "name": "HS18",
                                               "demand_tier": "HIGH", "expected_orders_per_hour": 40}, MANAGER), 201)
    data = validate_success(api.create_menu_item(create_menu_item_payload(stand["id"], product["id"]), MANAGER), 201)
    assert data["price_cents"] == 1326


# ===========================================================================
# Queue A — order_total_round_per_line_then_sum
# Three lines subtotal 50 each, service_fee_pct=9 -> per-line fee round(4.5)=5,
# summed service_fee=15, total=165. (Sum-then-round would give 164.)
# ===========================================================================
def _round_per_line_scenario():
    # LOW demand tier (surge 100) + event multiplier 100 so the menu price equals
    # the 50c base exactly, matching the round-per-line design instance.
    scenario = setup_sellable_stand(
        venue_overrides={"venue_share_pct": 10, "service_fee_pct": 9},
        product_overrides={"sku": "WATER", "name": "Water", "base_price_cents": 50, "unit_cost_cents": 10},
        event_overrides={"event_multiplier_pct": 100},
        stand_overrides={"demand_tier": "LOW", "expected_orders_per_hour": 40},
        lot_overrides={"received_qty": 50, "unit_cost_cents": 10, "par_level": 50, "reorder_point": 10},
    )
    return setup_cart_order(scenario=scenario, line_qtys=(1, 1, 1))


def test_order_total_rounds_fee_per_line_then_sums(api):
    """PRD §3.8: "its service_fee_cents is the sum of the already-rounded per-line
    fees — the fee is rounded on each line first and only then summed, never summed
    first and rounded once; and its total_cents is subtotal_cents plus
    service_fee_cents."

    Three lines (water 50c at a LOW-tier, multiplier-100 stand so unit price is 50,
    each line subtotal 50); service_fee_pct=9 -> per-line round(4.5)=5, summed=15,
    total=165.

    Design: Difficulty/combinatorial_formula/order_total_round_per_line_then_sum
    """
    state = _round_per_line_scenario()
    order = validate_success(api.place_order(state["order"]["id"], state["patron_headers"]), 200)
    assert order["service_fee_cents"] == 15, f"expected 15 (5+5+5), got {order['service_fee_cents']}"
    assert order["total_cents"] == 165, f"expected 165, got {order['total_cents']}"


def test_order_subtotal_sums_line_subtotals(api):
    """PRD §3.8: "The order's subtotal_cents is the sum of the line subtotals".
    PRD §3.8: "each line's line_subtotal_cents is its snapshot unit_price_cents
    times its qty".

    Three lines each subtotal 50 -> order subtotal 150.

    Design: Difficulty/combinatorial_formula/order_total_round_per_line_then_sum
    """
    state = _round_per_line_scenario()
    order = validate_success(api.place_order(state["order"]["id"], state["patron_headers"]), 200)
    assert order["subtotal_cents"] == 150, f"expected 150, got {order['subtotal_cents']}"
