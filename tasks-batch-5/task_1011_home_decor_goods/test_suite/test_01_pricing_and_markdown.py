"""Markdown cadence and clearance pricing derived from the logical clock.

Covers the combinatorial pricing formula (treasure-hunt ladder with a
clearance-floor max) and the regular four-rung ladder boundary at week 12.
"""
from test_helpers import (
    validate_success, set_clock, new_product, api_client, TEST_USERS,
)

MERCH = TEST_USERS["merch_headers"]


# ─── treasure_hunt_ladder_with_clearance_floor_max (queue A) ───

def test_treasure_hunt_week8_reaches_clearance_tier():
    """PRD §3.1: "A treasure-hunt SKU uses a compressed two-rung ladder: it stays
    at `FULL` price (no discount) while `weeks_on_shelf` is less than 8, and drops
    to `CLEARANCE` (40% off) once `weeks_on_shelf` reaches 8 or more."
    PRD §3.1: "The number of whole weeks a SKU has been on the floor,
    `weeks_on_shelf`, is the number of whole 7-day periods between the product's
    `first_received_at` and the current clock time, computed by taking the elapsed
    time, dividing by seven days, discarding any fractional week, and treating any
    negative result as zero."

    Design: Difficulty/combinatorial_formula/treasure_hunt_ladder_with_clearance_floor_max
    """
    set_clock("2026-07-01T00:00:00Z")
    product = new_product(sku="SKU-TH1", name="Accent Lamp", category="SEASONAL",
                          base_price_cents=1000, clearance_floor_cents=800,
                          first_received_at="2026-05-01T00:00:00Z", is_treasure_hunt=True)
    data = validate_success(api_client.get_product(product["id"], MERCH))
    assert data["weeks_on_shelf"] == 8, f"expected 8 weeks, got {data['weeks_on_shelf']}"
    assert data["markdown_tier"] == "CLEARANCE", f"expected CLEARANCE, got {data['markdown_tier']}"


def test_treasure_hunt_clearance_price_floored_at_clearance_floor():
    """PRD §3.1: "The `current_price_cents` is then the base price reduced by the
    tier's discount percentage, rounded to a whole cent half-up, but never below
    the SKU's clearance floor — that is, it is whichever is larger of the rounded
    discounted price and `clearance_floor_cents`."

    Design: Difficulty/combinatorial_formula/treasure_hunt_ladder_with_clearance_floor_max
    """
    set_clock("2026-07-01T00:00:00Z")
    # 40% off 1000 = 600, but clearance floor 800 dominates.
    product = new_product(sku="SKU-TH1", name="Accent Lamp", category="SEASONAL",
                          base_price_cents=1000, clearance_floor_cents=800,
                          first_received_at="2026-05-01T00:00:00Z", is_treasure_hunt=True)
    data = validate_success(api_client.get_product(product["id"], MERCH))
    assert data["current_price_cents"] == 800, (
        f"expected floor 800 to dominate the 600 clearance price, got {data['current_price_cents']}")


# ─── markdown_clearance_threshold_at_week_12 (queue A) ───

def test_regular_sku_reaches_clearance_exactly_at_week_12():
    """PRD §3.1: "A regular SKU uses the four-rung ladder: `FULL` with no discount
    while `weeks_on_shelf` is below 4; `MARKDOWN_1` at 15% off when `weeks_on_shelf`
    is at least 4 but below 8; `MARKDOWN_2` at 30% off when `weeks_on_shelf` is at
    least 8 but below 12; and `CLEARANCE` at 50% off once `weeks_on_shelf` reaches
    12 or more."

    Design: Difficulty/boundary_precision_check/markdown_clearance_threshold_at_week_12
    """
    set_clock("2026-07-01T00:00:00Z")
    product = new_product(sku="SKU-B1", name="Wall Clock", category="DECOR",
                          base_price_cents=10000, clearance_floor_cents=1000,
                          first_received_at="2026-04-08T00:00:00Z", is_treasure_hunt=False)
    data = validate_success(api_client.get_product(product["id"], MERCH))
    assert data["weeks_on_shelf"] == 12, f"expected 12 weeks, got {data['weeks_on_shelf']}"
    assert data["markdown_tier"] == "CLEARANCE", f"expected CLEARANCE, got {data['markdown_tier']}"


def test_regular_sku_clearance_price_at_week_12():
    """PRD §3.1: "The `current_price_cents` is then the base price reduced by the
    tier's discount percentage, rounded to a whole cent half-up, but never below
    the SKU's clearance floor — that is, it is whichever is larger of the rounded
    discounted price and `clearance_floor_cents`."

    Design: Difficulty/boundary_precision_check/markdown_clearance_threshold_at_week_12
    """
    set_clock("2026-07-01T00:00:00Z")
    # 50% off 10000 = 5000, above the 1000 floor.
    product = new_product(sku="SKU-B1", name="Wall Clock", category="DECOR",
                          base_price_cents=10000, clearance_floor_cents=1000,
                          first_received_at="2026-04-08T00:00:00Z", is_treasure_hunt=False)
    data = validate_success(api_client.get_product(product["id"], MERCH))
    assert data["current_price_cents"] == 5000, (
        f"expected 5000 clearance price, got {data['current_price_cents']}")
