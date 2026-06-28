"""Auto-ship vs special-order pricing divergence, pinned compose order, and
round-per-line-item rounding discipline."""
from test_helpers import (
    validate_success,
    TEST_USERS,
    create_subscription_payload, run_shipment_payload,
    create_special_order_payload,
    make_store, make_product, make_customer, make_lot,
    raise_customer_to_tier, set_clock,
)

INVMGR = TEST_USERS["inventory_manager_headers"]
CLERK = TEST_USERS["store_clerk_headers"]


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc
# ---------------------------------------------------------------------------
def test_auto_ship_vs_special_order_rounding_diverge(api):
    """PRD §3.10: "take the gross, multiply it by one minus the subscription's
    `discount_pct`, then multiply that result by one minus the loyalty-tier
    discount fraction read at run time ..., and round that final real number
    half up to whole cents exactly once to obtain `net_cents`."
    PRD §3.11: "For each unit, take the product's `unit_price_cents`, multiply by
    one minus the frozen tier discount, and round that half up to whole cents to
    obtain a per-unit net; multiply that per-unit net by the `quantity` to obtain
    the order's gross net in cents."

    Design: Difficulty/dual_variant_calc/auto_ship_vs_special_order_rounding_diverge
    """
    store = make_store(state_code="CA", loyalty_point_value_cents=1)
    product = make_product(unit_price_cents=1990, category="FOOD")
    customer = make_customer(store["id"])
    # Raise to SILVER via one big livestock sale (5,050,000 net).
    raise_customer_to_tier(store["id"], customer["id"], "SILVER")
    make_lot(store["id"], product["id"], quantity_on_hand=100)
    # Both subscription and special order: qty=3, identical price/tier inputs.
    sub = validate_success(
        api.create_subscription(
            create_subscription_payload(
                customer["id"], product["id"], store["id"],
                quantity_per_cycle=3, discount_pct=0,
                next_ship_at="2026-01-10T00:00:00Z",
            ), CLERK,
        ), 201,
    )
    order = validate_success(
        api.create_special_order(
            create_special_order_payload(
                customer["id"], product["id"], store["id"],
                quantity=3, deposit_pct=0.25,
            ), CLERK,
        ), 201,
    )
    shipment = validate_success(
        api.run_shipment(sub["id"], run_shipment_payload(sub["version"]), CLERK),
        201,
    )
    # Auto-ship: gross=5970, sum-then-round SILVER 5% → net=5672.
    assert shipment["gross_cents"] == 5970
    assert shipment["net_cents"] == 5672
    # Special order: round-per-unit SILVER 5% → per-unit 1891, gross_net=5673.
    assert order["deposit_cents"] == 1418
    assert order["balance_cents"] == 4255
    # The two calcs diverge by 1 cent on identical inputs.
    assert shipment["net_cents"] != (order["deposit_cents"] + order["balance_cents"])


def test_tier_timing_frozen_vs_runtime_diverge(api):
    """PRD §3.11: "The tier discount fraction ... is read at request time and
    frozen on the order even if the customer's tier later changes."
    PRD §3.10: "The loyalty tier is read at the moment the shipment runs, not at
    subscription creation."

    Design: Difficulty/dual_variant_calc/tier_timing_frozen_vs_runtime_diverge
    """
    store = make_store(state_code="CA")
    product = make_product(unit_price_cents=2000, category="FOOD")
    customer = make_customer(store["id"])
    # Special order created while BRONZE (deposit_pct=1.0 → full charge at deposit).
    order = validate_success(
        api.create_special_order(
            create_special_order_payload(
                customer["id"], product["id"], store["id"],
                quantity=2, deposit_pct=1.0,
            ), CLERK,
        ), 201,
    )
    # Now push the customer to SILVER, then run an auto-ship cycle.
    raise_customer_to_tier(store["id"], customer["id"], "SILVER")
    make_lot(store["id"], product["id"], quantity_on_hand=50)
    sub = validate_success(
        api.create_subscription(
            create_subscription_payload(
                customer["id"], product["id"], store["id"],
                quantity_per_cycle=2, discount_pct=0,
                next_ship_at="2026-01-10T00:00:00Z",
            ), CLERK,
        ), 201,
    )
    shipment = validate_success(
        api.run_shipment(sub["id"], run_shipment_payload(sub["version"]), CLERK),
        201,
    )
    # Order froze BRONZE (0%): per-unit 2000, gross_net 4000, deposit 4000.
    assert order["deposit_cents"] == 4000
    assert order["balance_cents"] == 0
    # Shipment reads SILVER (5%) at run time: gross 4000, net 3800.
    assert shipment["gross_cents"] == 4000
    assert shipment["net_cents"] == 3800


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula
# ---------------------------------------------------------------------------
def test_auto_ship_pinned_order_base_then_tier_single_round(api):
    """PRD §3.10: "The two discounts then compose multiplicatively on the gross
    sum as a whole, base discount first then loyalty-tier discount, with a single
    rounding only at the very end: take the gross, multiply it by one minus the
    subscription's `discount_pct`, then multiply that result by one minus the
    loyalty-tier discount fraction read at run time ..., and round that final
    real number half up to whole cents exactly once to obtain `net_cents`."

    Design: Difficulty/combinatorial_formula/auto_ship_pinned_order_base_then_tier_single_round
    """
    store = make_store(state_code="CA")
    product = make_product(unit_price_cents=1999, category="FOOD")
    customer = make_customer(store["id"])
    raise_customer_to_tier(store["id"], customer["id"], "GOLD")
    make_lot(store["id"], product["id"], quantity_on_hand=100)
    sub = validate_success(
        api.create_subscription(
            create_subscription_payload(
                customer["id"], product["id"], store["id"],
                quantity_per_cycle=3, discount_pct=0.10,
                next_ship_at="2026-01-10T00:00:00Z",
            ), CLERK,
        ), 201,
    )
    shipment = validate_success(
        api.run_shipment(sub["id"], run_shipment_payload(sub["version"]), CLERK),
        201,
    )
    # gross = 3*1999 = 5997; *0.90 *0.90 = 4857.57 → round once → 4858.
    assert shipment["gross_cents"] == 5997
    assert shipment["net_cents"] == 4858


def test_special_order_round_per_line_item_then_sum(api):
    """PRD §3.11: "For each unit, take the product's `unit_price_cents`, multiply
    by one minus the frozen tier discount, and round that half up to whole cents
    to obtain a per-unit net; multiply that per-unit net by the `quantity` to
    obtain the order's gross net in cents. The `deposit_cents` is that gross net
    multiplied by `deposit_pct`, rounded half up to whole cents ... The
    `balance_cents` is the gross net minus the `deposit_cents`".

    Design: Difficulty/combinatorial_formula/special_order_round_per_line_item_then_sum
    """
    store = make_store(state_code="CA")
    product = make_product(unit_price_cents=1990, category="FOOD")
    customer = make_customer(store["id"])
    raise_customer_to_tier(store["id"], customer["id"], "SILVER")
    order = validate_success(
        api.create_special_order(
            create_special_order_payload(
                customer["id"], product["id"], store["id"],
                quantity=3, deposit_pct=0.25,
            ), CLERK,
        ), 201,
    )
    # per-unit: round(1990*0.95)=round(1890.5)=1891; gross_net=5673;
    # deposit=round(5673*0.25)=round(1418.25)=1418; balance=5673-1418=4255.
    assert order["deposit_cents"] == 1418
    assert order["balance_cents"] == 4255


# ---------------------------------------------------------------------------
# Second tests (≥2 per queue-A instance)
# ---------------------------------------------------------------------------
def test_auto_ship_gross_is_exact_units_times_unit_price(api):
    """PRD §3.10: "The gross is the `units` shipped multiplied by the product's
    `unit_price_cents`, an exact integer recorded as `gross_cents`."

    Design: Difficulty/dual_variant_calc/auto_ship_vs_special_order_rounding_diverge
    """
    store = make_store(state_code="CA", loyalty_point_value_cents=1)
    product = make_product(unit_price_cents=1990, category="FOOD")
    customer = make_customer(store["id"])
    raise_customer_to_tier(store["id"], customer["id"], "SILVER")
    make_lot(store["id"], product["id"], quantity_on_hand=100)
    sub = validate_success(
        api.create_subscription(
            create_subscription_payload(
                customer["id"], product["id"], store["id"],
                quantity_per_cycle=3, discount_pct=0,
                next_ship_at="2026-01-10T00:00:00Z",
            ), CLERK,
        ), 201,
    )
    shipment = validate_success(
        api.run_shipment(sub["id"], run_shipment_payload(sub["version"]), CLERK),
        201,
    )
    # gross = 3 * 1990 = 5970 exactly; sum-then-round SILVER 5% → 5672.
    assert shipment["gross_cents"] == 5970
    assert shipment["net_cents"] == 5672


def test_special_order_deposit_reflects_frozen_request_tier(api):
    """PRD §3.11: "The tier discount fraction (`BRONZE` 0.00, `SILVER` 0.05,
    `GOLD` 0.10) is read at request time and frozen on the order even if the
    customer's tier later changes."

    Design: Difficulty/dual_variant_calc/tier_timing_frozen_vs_runtime_diverge
    """
    store = make_store(state_code="CA")
    product = make_product(unit_price_cents=2000, category="FOOD")
    customer = make_customer(store["id"])
    # BRONZE at request → tier_disc 0%, deposit_pct 1.0 → full charge.
    order = validate_success(
        api.create_special_order(
            create_special_order_payload(
                customer["id"], product["id"], store["id"],
                quantity=2, deposit_pct=1.0,
            ), CLERK,
        ), 201,
    )
    # per-unit round(2000*1.0)=2000; gross_net=4000; deposit=4000; balance=0.
    assert order["deposit_cents"] == 4000
    assert order["balance_cents"] == 0


def test_auto_ship_single_final_round_gold_base_then_tier(api):
    """PRD §3.10: "take the gross, multiply it by one minus the subscription's
    `discount_pct`, then multiply that result by one minus the loyalty-tier
    discount fraction read at run time ..., and round that final real number half
    up to whole cents exactly once to obtain `net_cents`."

    Design: Difficulty/combinatorial_formula/auto_ship_pinned_order_base_then_tier_single_round
    """
    store = make_store(state_code="CA")
    product = make_product(unit_price_cents=1999, category="FOOD")
    customer = make_customer(store["id"])
    raise_customer_to_tier(store["id"], customer["id"], "GOLD")
    make_lot(store["id"], product["id"], quantity_on_hand=100)
    sub = validate_success(
        api.create_subscription(
            create_subscription_payload(
                customer["id"], product["id"], store["id"],
                quantity_per_cycle=3, discount_pct=0.10,
                next_ship_at="2026-01-10T00:00:00Z",
            ), CLERK,
        ), 201,
    )
    shipment = validate_success(
        api.run_shipment(sub["id"], run_shipment_payload(sub["version"]), CLERK),
        201,
    )
    # 5997 * 0.90 * 0.90 = 4857.57 → single round_half_up → 4858.
    assert shipment["net_cents"] == 4858


def test_special_order_balance_is_gross_net_minus_deposit(api):
    """PRD §3.11: "The `balance_cents` is the gross net minus the `deposit_cents`,
    charged at fulfillment."

    Design: Difficulty/combinatorial_formula/special_order_round_per_line_item_then_sum
    """
    store = make_store(state_code="CA")
    product = make_product(unit_price_cents=1990, category="FOOD")
    customer = make_customer(store["id"])
    raise_customer_to_tier(store["id"], customer["id"], "SILVER")
    order = validate_success(
        api.create_special_order(
            create_special_order_payload(
                customer["id"], product["id"], store["id"],
                quantity=3, deposit_pct=0.25,
            ), CLERK,
        ), 201,
    )
    # gross_net = 1891*3 = 5673; deposit=1418; balance = 5673-1418 = 4255.
    assert order["deposit_cents"] + order["balance_cents"] == 5673
    assert order["balance_cents"] == 4255
