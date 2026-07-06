"""Framing quote tiered rate selection and special-order deposit."""
from test_helpers import (
    validate_success,
    create_customer, create_order, create_framing_order, create_product,
    create_special_order, make_customer_headers, TEST_USERS,
)


def test_framing_quote_small_tier(api):
    """PRD §3.7: "if the united inches are at most 40 the per-inch rate is 15
    cents, else if the united inches are at most 80 the rate is 25 cents,
    otherwise the rate is 40 cents. The perimeter is twice the sum of width and
    height. The quoted price is the base of 2000 cents plus the rate multiplied
    by the perimeter in inches, all rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/framing_quote_tiered_rate_selection
    """
    customer = create_customer()
    order = create_order(customer["id"])
    framing = create_framing_order(order["id"], customer["id"], width_in=20, height_in=20)
    # united=40 -> SMALL rate 15; perimeter 80; 2000 + 15*80 = 3200.
    assert framing["quoted_price_cents"] == 3200


def test_framing_quote_medium_tier(api):
    """PRD §3.7: "else if the united inches are at most 80 the rate is 25 cents,
    otherwise the rate is 40 cents. The perimeter is twice the sum of width and
    height. The quoted price is the base of 2000 cents plus the rate multiplied by
    the perimeter in inches, all rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/framing_quote_tiered_rate_selection
    """
    customer = create_customer()
    order = create_order(customer["id"])
    framing = create_framing_order(order["id"], customer["id"], width_in=30, height_in=30)
    # united=60 -> MED rate 25; perimeter 120; 2000 + 25*120 = 5000.
    assert framing["quoted_price_cents"] == 5000


def test_framing_quote_large_tier(api):
    """PRD §3.7: "otherwise the rate is 40 cents. The perimeter is twice the sum of
    width and height. The quoted price is the base of 2000 cents plus the rate
    multiplied by the perimeter in inches, all rounded half up to whole cents."

    Design: Corner/calculations/framing_quote_large_tier
    """
    customer = create_customer()
    order = create_order(customer["id"])
    framing = create_framing_order(order["id"], customer["id"], width_in=50, height_in=50)
    # united=100 -> LARGE rate 40; perimeter 200; 2000 + 40*200 = 10000.
    assert framing["quoted_price_cents"] == 10000


def test_special_order_deposit_fifty_percent(api):
    """PRD §3.8: "The deposit is the line value — the quoted_unit_price_cents
    multiplied by the quantity — multiplied by 0.50 (half of the line value),
    rounded half up to whole cents."

    Design: Corner/calculations/special_order_deposit_fifty_percent
    """
    customer = create_customer()
    product = create_product(sell_mode="UNIT", unit_price_cents=5000, special_order_only=True)
    special = create_special_order(customer["id"], product["id"], quantity=2)
    resp = api.quote_special_order(
        special["id"], {"quoted_unit_price_cents": 5000}, TEST_USERS["store_manager_headers"]
    )
    data = validate_success(resp)
    # 5000 * 2 * 0.5 = 5000.
    assert data["deposit_cents"] == 5000
    assert data["status"] == "QUOTED"
