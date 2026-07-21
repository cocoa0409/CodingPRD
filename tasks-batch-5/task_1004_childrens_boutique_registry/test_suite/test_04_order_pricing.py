"""Order pricing: loyalty discount (per-line rounding), the completion discount
variants, and immediate consistency of the create response.
"""
from test_helpers import (
    validate_success,
    make_customer_headers,
    new_store,
    new_customer,
    new_sku,
    create_order_payload,
    order_line,
    set_clock,
    setup_active_registry_with_item,
    setup_store_customer_sku,
)


def test_order_pricing_bronze_no_discount_total_equals_subtotal(api):
    """PRD §3.3: "Each tier carries a percentage: `BRONZE` earns nothing
    (0 percent), `SILVER` earns 5 percent, `GOLD` earns 10 percent, and
    `PLATINUM` earns 15 percent."
    PRD §3.3: "The `total_before_credit_cents` is then `subtotal_cents` minus
    `applied_discount_cents`."

    Design: Corner/calculations/order_pricing_bronze_no_discount_total_equals_subtotal
    """
    base = setup_store_customer_sku(api, sku_overrides={"base_price_cents": 4000,
                                                        "initial_on_hand_qty": 10})
    cust = base["customer"]["id"]
    resp = api.create_order(
        create_order_payload(cust, base["store"]["id"], [order_line(base["sku"]["id"], 1)]),
        make_customer_headers(cust),
    )
    data = validate_success(resp, 201)
    assert data["subtotal_cents"] == 4000
    assert data["loyalty_discount_cents"] == 0
    assert data["total_before_credit_cents"] == 4000


def test_order_loyalty_discount_rounded_per_line_then_summed_gold(api):
    """PRD §3.3: "The `loyalty_discount_cents` is computed by taking, for every
    line, that line's `line_total_cents` multiplied by the buyer's tier
    percentage, rounding each such line amount half up to whole cents, and then
    summing those per-line results — the rounding happens per line and the sum
    is taken afterward, never by multiplying the whole subtotal by the
    percentage."
    PRD §3.3: "Each tier carries a percentage: `BRONZE` earns nothing
    (0 percent), `SILVER` earns 5 percent, `GOLD` earns 10 percent, and
    `PLATINUM` earns 15 percent."

    Design: Difficulty/combinatorial_formula/order_loyalty_discount_rounded_per_line_then_summed
    """
    store = new_store(api)
    customer = new_customer(api, initial_lifetime_spend_cents=150000)  # -> GOLD
    cust = customer["id"]
    x = new_sku(api, store["id"], base_price_cents=3333, initial_on_hand_qty=100)
    y = new_sku(api, store["id"], base_price_cents=3333, initial_on_hand_qty=100)
    resp = api.create_order(
        create_order_payload(cust, store["id"],
                             [order_line(x["id"], 1), order_line(y["id"], 1)]),
        make_customer_headers(cust),
    )
    data = validate_success(resp, 201)
    assert customer["loyalty_tier"] == "GOLD"
    assert data["subtotal_cents"] == 6666
    # round(333.3)+round(333.3) = 333+333 = 666, NOT round(6666*0.10)=667.
    assert data["loyalty_discount_cents"] == 666
    assert data["total_before_credit_cents"] == 6000


def test_order_loyalty_discount_rounded_per_line_then_summed_silver(api):
    """PRD §3.3: "the rounding happens per line and the sum is taken afterward,
    never by multiplying the whole subtotal by the percentage."
    PRD §3.3: "Each tier carries a percentage: `BRONZE` earns nothing
    (0 percent), `SILVER` earns 5 percent, `GOLD` earns 10 percent, and
    `PLATINUM` earns 15 percent."

    Design: Difficulty/combinatorial_formula/order_loyalty_discount_rounded_per_line_then_summed
    """
    store = new_store(api)
    customer = new_customer(api, initial_lifetime_spend_cents=60000)  # -> SILVER
    cust = customer["id"]
    x = new_sku(api, store["id"], base_price_cents=3333, initial_on_hand_qty=100)
    y = new_sku(api, store["id"], base_price_cents=3333, initial_on_hand_qty=100)
    resp = api.create_order(
        create_order_payload(cust, store["id"],
                             [order_line(x["id"], 1), order_line(y["id"], 1)]),
        make_customer_headers(cust),
    )
    data = validate_success(resp, 201)
    assert customer["loyalty_tier"] == "SILVER"
    # round(166.65)+round(166.65) = 167+167 = 334, NOT round(6666*0.05)=333.
    assert data["loyalty_discount_cents"] == 334
    assert data["total_before_credit_cents"] == 6332


def _setup_registrant_registry_order(api, event_date, clock_iso=None):
    """Store + SKU(10000, on_hand 100) + registrant customer + ACTIVE
    BABY_REGISTRY (item desired 5, no gifts, completion 0). Optionally advance
    the clock. Returns (store_id, customer_id, sku_id, registry_id)."""
    ctx = setup_active_registry_with_item(
        api, base_price_cents=10000, desired_qty=5, on_hand=100, event_date=event_date
    )
    if clock_iso is not None:
        set_clock(api, clock_iso)
    return ctx["store"]["id"], ctx["customer"]["id"], ctx["sku"]["id"], ctx["registry"]["id"]


def test_completion_discount_final_variant_ignores_unlock_gate(api):
    """PRD §3.3: "Under the **FINAL** variant — in force when the order's
    creation time is at or after the `event_date` — the discount is granted on
    the same eligible lines regardless of `completion_pct` or unlock status, as
    a post-event "finish the registry" perk."
    PRD §3.3: "For each eligible line, the still-needed quantity is the greater
    of zero and that registry item's `desired_qty` minus its `fulfilled_qty`,
    and the discountable quantity is the lesser of the line's `qty` and that
    still-needed quantity."
    PRD §3.3: "The `completion_discount_cents` is the sum, across eligible lines,
    of the discountable quantity multiplied by the SKU's `base_price_cents`
    multiplied by the completion discount rate of 15 percent, each per-line
    product rounded half up to whole cents before summing."

    Design: Difficulty/dual_variant_calc/registry_completion_discount_final_variant_ignores_unlock_gate
    """
    s_id, c_id, a_id, r_id = _setup_registrant_registry_order(
        api, event_date="2026-07-10T00:00:00Z", clock_iso="2026-07-11T09:00:00Z"
    )
    resp = api.create_order(
        create_order_payload(
            c_id, s_id, [order_line(a_id, 3)], registry_id=r_id,
            pickup_start="2026-07-11T10:00:00Z", pickup_end="2026-07-11T10:30:00Z",
        ),
        make_customer_headers(c_id),
    )
    data = validate_success(resp, 201)
    assert data["subtotal_cents"] == 30000
    assert data["completion_discount_cents"] == 4500
    assert data["applied_discount_cents"] == 4500
    assert data["total_before_credit_cents"] == 25500


def test_completion_discount_provisional_variant_zero_when_not_unlocked(api):
    """PRD §3.3: "Under the **PROVISIONAL** variant — in force when the order's
    creation time is strictly before the registry's `event_date` — the discount
    is granted only if the registry is in `COMPLETION_UNLOCKED` (that is, its
    `completion_pct` is at least 0.80) at order time; if the registry is not
    unlocked, `completion_discount_cents` is zero."

    Design: Difficulty/dual_variant_calc/registry_completion_discount_final_variant_ignores_unlock_gate
    """
    # Clock stays at the startup default 2026-07-01, strictly before event_date.
    s_id, c_id, a_id, r_id = _setup_registrant_registry_order(
        api, event_date="2026-07-10T00:00:00Z", clock_iso=None
    )
    resp = api.create_order(
        create_order_payload(
            c_id, s_id, [order_line(a_id, 3)], registry_id=r_id,
            pickup_start="2026-07-01T10:00:00Z", pickup_end="2026-07-01T10:30:00Z",
        ),
        make_customer_headers(c_id),
    )
    data = validate_success(resp, 201)
    assert data["subtotal_cents"] == 30000
    assert data["completion_discount_cents"] == 0
    assert data["total_before_credit_cents"] == 30000


def test_order_create_response_reflects_reservation_and_pricing_immediately(api):
    """PRD §3.4: "On success the order is created with `payment_status` of
    `UNPAID` and `fulfillment_status` of `RESERVED`."
    PRD §3.4: "Each line's SKU has its `reserved_qty` raised by the line `qty`
    and its availability recomputed, and the full pricing sequence of the
    previous subsection runs to populate `subtotal_cents`,
    `loyalty_discount_cents`, `completion_discount_cents`,
    `applied_discount_cents`, `total_before_credit_cents`, and
    `amount_due_cents`."

    Design: Corner/consistency_model/order_create_response_reflects_reservation_and_pricing_immediately
    """
    base = setup_store_customer_sku(api, sku_overrides={"base_price_cents": 4000,
                                                        "initial_on_hand_qty": 10})
    cust = base["customer"]["id"]
    resp = api.create_order(
        create_order_payload(cust, base["store"]["id"], [order_line(base["sku"]["id"], 1)]),
        make_customer_headers(cust),
    )
    data = validate_success(resp, 201)
    assert data["fulfillment_status"] == "RESERVED"
    assert data["payment_status"] == "UNPAID"
    assert data["subtotal_cents"] == 4000
