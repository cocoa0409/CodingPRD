"""Order placement pricing: the dual provisional/final total, the combinatorial
commercial pricing formula (clamped discount + capped hazmat surcharge), per-line
loyalty accrual, and the placement-time stock/validation gates."""
import pytest

from test_helpers import (
    validate_success, validate_error, api_client,
    new_customer, new_stocked_product, new_active_account, place_commercial_order,
    new_retail_order, pay_order, set_account_tier, ship_order, order_line,
    create_retail_order_payload, TEST_USERS, make_customer_headers,
)

ADMIN = TEST_USERS["store_admin_headers"]


# ─── Difficulty: dual_variant_calc / provisional vs final on tier change ───
def _setup_commercial_order_silver():
    """SILVER commercial account with a placed 20-unit order (subtotal 600000).
    Returns (account, product, order)."""
    account = new_active_account(business_name="Green Farms",
                                 credit_limit_cents=10_000_000, discount_tier="SILVER")
    product, _lot = new_stocked_product(quantity=1000, sku_code="SYS-1",
                                        name="Grow System", category="SYSTEM",
                                        unit_price_cents=30000)
    order = place_commercial_order(account, [order_line(product["id"], 20)])
    return account, product, order


def test_provisional_total_uses_placement_tier(api):
    """PRD §3.4: "At placement this net figure is written to
    `provisional_total_cents` using the discount tier in force at placement time."
    PRD §3.4: "The base rate is 0 for a `STANDARD` account, 0.05 for a `SILVER`
    account, and 0.10 for a `GOLD` account, read from the account's
    `discount_tier`."

    Design: Difficulty/dual_variant_calc/order_provisional_vs_final_on_tier_change
    """
    account, product, order = _setup_commercial_order_silver()
    assert order["subtotal_cents"] == 600000
    assert order["provisional_total_cents"] == 540000


def test_final_total_recomputed_at_ship_tier(api):
    """PRD §3.4: "The order's `final_total_cents` stays empty until the order
    ships, at which point the same routine reruns using the discount tier in force
    at ship time — so a tier change between placement and ship genuinely changes
    the final figure — and writes `final_total_cents`. The unifying field
    `total_cents` reads as `provisional_total_cents` until the order ships and as
    `final_total_cents` thereafter."
    PRD §3.4: "The effective discount rate is the smaller of that base-plus-bonus
    sum and the ceiling of 0.12."

    Design: Difficulty/dual_variant_calc/order_provisional_vs_final_on_tier_change
    """
    account, product, order = _setup_commercial_order_silver()
    set_account_tier(account["id"], "GOLD")
    shipped = ship_order(order["id"])
    assert shipped["final_total_cents"] == 528000
    assert shipped["total_cents"] == 528000


# ─── Difficulty: combinatorial_formula / clamped discount + capped hazmat ──
def _setup_gold_hazmat_order():
    account = new_active_account(business_name="Vert Co",
                                 credit_limit_cents=10_000_000, discount_tier="GOLD")
    product, _lot = new_stocked_product(quantity=1000, sku_code="NUT-9",
                                        name="Bloom Nutrient", category="NUTRIENT",
                                        unit_price_cents=25000, is_hazmat=True,
                                        unit_weight_g=4000)
    order = place_commercial_order(account, [order_line(product["id"], 25)])
    return account, product, order


def test_commercial_discount_clamped_to_max_rate(api):
    """PRD §3.4: "A volume bonus of an additional 0.05 is added when the order's
    `subtotal_cents` is at least 500000 cents; below that threshold the bonus is
    zero. The effective discount rate is the smaller of that base-plus-bonus sum
    and the ceiling of 0.12. The `discount_cents` is the discount rate applied to
    `subtotal_cents`, rounded half up once to whole cents."

    Design: Difficulty/combinatorial_formula/commercial_pricing_nested_min_max_with_hazmat_cap
    """
    account, product, order = _setup_gold_hazmat_order()
    assert order["subtotal_cents"] == 625000
    assert order["discount_cents"] == 75000


def test_hazmat_surcharge_capped_and_net_total(api):
    """PRD §3.4: "the system totals the shipping weight of the whole order as the
    sum over lines of `unit_weight_g` times `quantity`, converts that gram total to
    kilograms by dividing by 1000 and rounding up to the next whole kilogram, and
    computes a surcharge of a 1500-cent base plus 200 cents per whole kilogram. The
    recorded `hazmat_surcharge_cents` is the smaller of that computed surcharge and
    the cap of 5000 cents."
    PRD §3.4: "The order's net total is `subtotal_cents` minus `discount_cents`
    plus `hazmat_surcharge_cents`."

    Design: Difficulty/combinatorial_formula/commercial_pricing_nested_min_max_with_hazmat_cap
    """
    account, product, order = _setup_gold_hazmat_order()
    assert order["hazmat_surcharge_cents"] == 5000
    assert order["provisional_total_cents"] == 555000


# ─── Difficulty: combinatorial_formula / loyalty floor-per-line-then-sum ───
def _setup_paid_two_line_order():
    customer = new_customer(email="loy@x.com", full_name="Loyal")
    pa, _la = new_stocked_product(quantity=100, sku_code="A-1", name="Clay Pebbles",
                                  category="CONSUMABLE", unit_price_cents=1599)
    pb, _lb = new_stocked_product(quantity=100, sku_code="B-1", name="pH Buffer",
                                  category="CONSUMABLE", unit_price_cents=899)
    order = new_retail_order(customer["id"],
                             [order_line(pa["id"], 3), order_line(pb["id"], 2)])
    order = pay_order(order["id"], customer["id"])
    return customer, order


def test_loyalty_points_floored_per_line(api):
    """PRD §3.5: "for each line, divide its `line_total_cents` by 100, multiply by
    the tier multiplier, and take the floor to a whole number of points; the
    earned total is the sum of those per-line floored figures — never the floor of
    a summed total."

    Design: Difficulty/combinatorial_formula/loyalty_points_floor_per_line_then_sum
    """
    customer, order = _setup_paid_two_line_order()
    refetched = validate_success(api.get_customer(customer["id"], ADMIN))
    assert refetched["loyalty_points"] == 64


def test_paying_order_marks_paid_and_bronze_tier(api):
    """PRD §3.5: "A `Customer` pays an order, moving `payment_status`
    `UNPAID → PAID`; payment is allowed only while the order is `UNPAID` and its
    `fulfillment_status` is not `CANCELLED`."
    PRD §3.2: "a customer is `BRONZE` while their `loyalty_points` are below 1000,
    `SILVER` once points reach 1000 and while they remain below 5000, and `GOLD`
    once points reach 5000 or more."

    Design: Difficulty/combinatorial_formula/loyalty_points_floor_per_line_then_sum
    """
    customer, order = _setup_paid_two_line_order()
    assert order["payment_status"] == "PAID"
    refetched = validate_success(api.get_customer(customer["id"], ADMIN))
    assert refetched["loyalty_tier"] == "BRONZE"


# ─── Corner: calculations / retail no discount, no hazmat ──────────────────
def test_retail_order_no_discount_no_hazmat(api):
    """PRD §3.4: "For a `RETAIL` order the discount rate is zero and
    `discount_cents` is zero."
    PRD §3.4: "If no line's product is flagged `is_hazmat`, the order's
    `hazmat_surcharge_cents` is zero."

    Design: Corner/calculations/retail_order_no_discount_no_hazmat
    """
    customer = new_customer()
    product, _lot = new_stocked_product(quantity=50, sku_code="ACC-2",
                                        name="Air Stone", category="ACCESSORY",
                                        unit_price_cents=4000)
    order = new_retail_order(customer["id"], [order_line(product["id"], 3)])
    assert order["subtotal_cents"] == 12000
    assert order["discount_cents"] == 0
    assert order["hazmat_surcharge_cents"] == 0
    assert order["provisional_total_cents"] == 12000


# ─── Corner: entities / retail order missing lines → 422 ───────────────────
def test_create_order_missing_lines_rejected(api):
    """PRD §3.4: "A `Customer` places a **retail order** by naming their own
    `customer_id` and supplying `lines` — an array of at least one line, each
    identifying a `product_id`, a `quantity`, the `unit_price_cents` snapshot
    captured at placement, and a computed `line_total_cents`."
    PRD §2.9: "then body/field validity — required fields present and each value
    of the correct type, enum, and range (`ERR_VALIDATION`)".

    Design: Corner/entities/create_order_missing_lines_returns_422
    """
    customer = new_customer(email="mr@x.com", full_name="Miss Req")
    headers = make_customer_headers(customer["id"])
    res = api.create_order({"customer_id": customer["id"]}, headers)
    validate_error(res, "ERR_VALIDATION")


# ─── Corner: cross_cutting / insufficient stock on confirm → 409 ───────────
def test_confirm_insufficient_stock_rejected(api):
    """PRD §3.5: "Confirmation first requires that every line has sufficient stock
    — each line's `quantity` must be coverable by its product's
    `total_available_units`, or the request is rejected with
    `ERR_INSUFFICIENT_STOCK`."

    Design: Corner/cross_cutting_complexity_layers/insufficient_stock_on_confirm_returns_conflict
    """
    customer = new_customer()
    product, _lot = new_stocked_product(quantity=3, sku_code="SYS-IS",
                                        name="Scarce", category="SYSTEM",
                                        unit_price_cents=5000)
    order = new_retail_order(customer["id"], [order_line(product["id"], 5)])
    headers = make_customer_headers(customer["id"])
    res = api.confirm_order(order["id"], headers)
    validate_error(res, "ERR_INSUFFICIENT_STOCK")
