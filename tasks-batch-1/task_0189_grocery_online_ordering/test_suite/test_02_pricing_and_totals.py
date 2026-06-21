"""Weighted/unit line pricing and order-total reconciliation.

Difficulty queue A: dual-variant estimated-vs-final (line and order level),
round-per-line ordering. Corner queue B: unit line charge, derived total
reconciliation on cart edit.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    ApiErrorId,
    assert_order,
    assert_order_line,
    make_customer_headers,
    make_picker_headers,
    create_store,
    create_customer,
    create_picker,
    create_product,
    create_slot,
    place_order,
    get_line_ids,
    claim_order,
    pick_line,
    stage_order,
    ADMIN,
    OPS,
)


def test_weighted_line_estimated_vs_final_diverge(api):
    """PRD §3.4: "For a `WEIGHT` product the charge is `unit_price_cents` multiplied by the weight in kilograms, with that single product rounded half-up to a whole number of cents. The estimated charge, `estimated_line_cents`, is computed at line creation using the `requested_qty` for a `UNIT` product or the `estimated_weight_kg` for a `WEIGHT` product. The final charge, `final_line_cents`, is computed when the line is actually resolved, using the `picked_qty` for a `UNIT` product or the `actual_weight_kg` for a `WEIGHT` product ... "

    Design: Difficulty/dual_variant_calc/dvc_weighted_line_estimated_vs_final
    """
    store = create_store()
    customer = create_customer(email="c@x.com", snap_ebt_balance_cents=100000)
    picker = create_picker(store["id"])
    banana = create_product(store["id"], sku="BAN", name="Bananas",
                            pricing_mode="WEIGHT", unit_price_cents=199, ebt_eligible=True)
    slot = create_slot(store["id"], capacity=1)
    order = place_order(
        store["id"], customer["id"], slot["id"], slot["version"],
        [{"product_id": banana["id"], "requested_qty": 1, "estimated_weight_kg": 1.50,
          "substitution_policy": "NO_SUBSTITUTION"}],
    )
    line_id = get_line_ids(order["id"], product_id=banana["id"],
                           headers=make_picker_headers(picker["id"]))[0]
    claim_order(order["id"], picker["id"])

    resp = api.pick_order_line(line_id, {"actual_weight_kg": 1.83},
                               make_picker_headers(picker["id"]))
    data = validate_success(resp)
    assert_order_line(data)
    assert data["estimated_line_cents"] == 299, "round_half_up(199 * 1.50) = 299"
    assert data["final_line_cents"] == 364, "round_half_up(199 * 1.83) = 364"
    assert data["status"] == "PICKED"


def test_weighted_line_estimated_value_at_creation(api):
    """PRD §3.4: "The estimated charge, `estimated_line_cents`, is computed at line creation using the `requested_qty` for a `UNIT` product or the `estimated_weight_kg` for a `WEIGHT` product."
    PRD §2.5: "the system rounds that single product to the nearest whole cent using round-half-up ... "

    Design: Difficulty/dual_variant_calc/dvc_weighted_line_estimated_vs_final
    """
    store = create_store()
    customer = create_customer(email="c-est@x.com")
    banana = create_product(store["id"], sku="BAN", name="Bananas",
                            pricing_mode="WEIGHT", unit_price_cents=199)
    slot = create_slot(store["id"], capacity=1)
    order = place_order(
        store["id"], customer["id"], slot["id"], slot["version"],
        [{"product_id": banana["id"], "requested_qty": 1, "estimated_weight_kg": 1.50}],
    )
    line_id = get_line_ids(order["id"])[0]
    line = validate_success(api.get_order_line(line_id, OPS))
    assert line["estimated_line_cents"] == 299, "round_half_up(199 * 1.50)"
    assert line["status"] == "PENDING"


def test_order_total_estimated_vs_final_diverge(api):
    """PRD §3.5: "The `estimated_total_cents` is the sum of `estimated_line_cents` over all of the order's lines, plus the order's `tip_cents`."
    PRD §3.5: "The `final_total_cents` is the sum of `final_line_cents` over only the lines whose status is `PICKED` or `SUBSTITUTED`, plus the order's `tip_cents`; lines that are `OUT_OF_STOCK` or `CANCELLED` contribute 0."

    Design: Difficulty/dual_variant_calc/dvc_order_total_estimated_vs_final
    """
    store = create_store()
    customer = create_customer(email="c2@x.com", snap_ebt_balance_cents=100000)
    picker = create_picker(store["id"])
    banana = create_product(store["id"], sku="BAN", name="Bananas",
                            pricing_mode="WEIGHT", unit_price_cents=199, ebt_eligible=True)
    milk = create_product(store["id"], sku="MILK", name="Milk",
                          pricing_mode="UNIT", unit_price_cents=349, ebt_eligible=True)
    slot = create_slot(store["id"], capacity=1)
    order = place_order(
        store["id"], customer["id"], slot["id"], slot["version"],
        [{"product_id": banana["id"], "requested_qty": 1, "estimated_weight_kg": 1.50},
         {"product_id": milk["id"], "requested_qty": 2}],
        tip_cents=0,
    )
    assert order["estimated_total_cents"] == 997, "banana est 299 + milk 698"

    ph = make_picker_headers(picker["id"])
    ban_line = get_line_ids(order["id"], product_id=banana["id"], headers=ph)[0]
    milk_line = get_line_ids(order["id"], product_id=milk["id"], headers=ph)[0]
    claim_order(order["id"], picker["id"])
    pick_line(ban_line, picker["id"], actual_weight_kg=1.83)
    pick_line(milk_line, picker["id"], picked_qty=2)

    resp = api.stage_order(order["id"], ph)
    data = validate_success(resp)
    assert_order(data)
    assert data["estimated_total_cents"] == 997
    assert data["final_total_cents"] == 1062, "banana final 364 + milk 698"
    assert data["fulfillment_status"] == "STAGED"


def test_order_total_final_equals_estimated_when_no_divergence(api):
    """PRD §3.5: "The `final_total_cents` is the sum of `final_line_cents` over only the lines whose status is `PICKED` or `SUBSTITUTED`, plus the order's `tip_cents`; lines that are `OUT_OF_STOCK` or `CANCELLED` contribute 0."
    PRD §3.5: "The estimated totals are pinned at placement. The `estimated_total_cents` is the sum of `estimated_line_cents` over all of the order's lines, plus the order's `tip_cents`."

    Design: Difficulty/dual_variant_calc/dvc_order_total_estimated_vs_final
    """
    store = create_store()
    customer = create_customer(email="c2b@x.com")
    picker = create_picker(store["id"])
    milk = create_product(store["id"], sku="MILK", name="Milk",
                          pricing_mode="UNIT", unit_price_cents=349)
    slot = create_slot(store["id"], capacity=1)
    order = place_order(store["id"], customer["id"], slot["id"], slot["version"],
                        [{"product_id": milk["id"], "requested_qty": 2}], tip_cents=0)
    assert order["estimated_total_cents"] == 698
    line_id = get_line_ids(order["id"])[0]
    claim_order(order["id"], picker["id"])
    pick_line(line_id, picker["id"], picked_qty=2)  # picked exactly as estimated

    staged = stage_order(order["id"], picker["id"])
    # No WEIGHT divergence and nothing out of stock -> final equals estimated.
    assert staged["final_total_cents"] == 698
    assert staged["estimated_total_cents"] == 698


def test_round_per_line_then_sum_ordering(api):
    """PRD §2.5: "Order and payment totals are formed by rounding each line to whole cents first and then summing the already-rounded line charges; the system never sums fractional products and rounds once at the end."

    Design: Difficulty/combinatorial_formula/cf_weighted_rounding_order
    """
    store = create_store()
    customer = create_customer(email="c4@x.com")
    gram = create_product(store["id"], sku="GRAM", name="Gram",
                          pricing_mode="WEIGHT", unit_price_cents=100)
    slot = create_slot(store["id"], capacity=1)
    resp = api.create_order(
        {"store_id": store["id"], "customer_id": customer["id"], "slot_id": slot["id"],
         "expected_slot_version": slot["version"], "tip_cents": 0,
         "lines": [{"product_id": gram["id"], "requested_qty": 1, "estimated_weight_kg": 0.005},
                   {"product_id": gram["id"], "requested_qty": 1, "estimated_weight_kg": 0.005}]},
        make_customer_headers(customer["id"]),
    )
    data = validate_success(resp, 201)
    assert_order(data)
    # round_half_up(0.5)+round_half_up(0.5)=1+1=2; sum-then-round would give 1.
    assert data["estimated_total_cents"] == 2
    assert data["fulfillment_status"] == "PLACED"


def test_single_weighted_line_rounds_half_up_per_line(api):
    """PRD §2.5: "the system rounds that single product to the nearest whole cent using round-half-up, then treats every later aggregation as an exact integer sum."
    PRD §3.4: "For a `WEIGHT` product the charge is `unit_price_cents` multiplied by the weight in kilograms, with that single product rounded half-up to a whole number of cents."

    Design: Difficulty/combinatorial_formula/cf_weighted_rounding_order
    """
    store = create_store()
    customer = create_customer(email="c4b@x.com")
    gram = create_product(store["id"], sku="GRAM", name="Gram",
                          pricing_mode="WEIGHT", unit_price_cents=100)
    slot = create_slot(store["id"], capacity=1)
    # One line of 0.005 kg: 100 * 0.005 = 0.5 -> round_half_up -> 1.
    order = place_order(store["id"], customer["id"], slot["id"], slot["version"],
                        [{"product_id": gram["id"], "requested_qty": 1,
                          "estimated_weight_kg": 0.005}], tip_cents=0)
    assert order["estimated_total_cents"] == 1, "round_half_up(0.5) == 1 per line"


def test_unit_line_charge_no_rounding(api):
    """PRD §3.4: "For a `UNIT` product the charge is `unit_price_cents` multiplied by the quantity (a whole each-count)."

    Design: Corner/calculations/calc_unit_line_charge_correct
    """
    store = create_store()
    customer = create_customer(email="cc11@x.com")
    product = create_product(store["id"], unit_price_cents=349)
    slot = create_slot(store["id"], capacity=1)
    order = place_order(store["id"], customer["id"], slot["id"], slot["version"],
                        [{"product_id": product["id"], "requested_qty": 3}])
    line_id = get_line_ids(order["id"], headers=make_customer_headers(customer["id"]))[0]
    line = validate_success(api.get_order_line(line_id, make_customer_headers(customer["id"])))
    assert line["estimated_line_cents"] == 1047, "349 * 3, no rounding for UNIT"


def test_estimated_total_reconciles_when_line_added(api):
    """PRD §2.5: "Whenever a child mutation changes a value that an order total depends on ... the server recomputes the affected order totals as part of the same operation ... "
    PRD §3.2: "Adding a line computes its `estimated_line_cents` and recomputes the order's estimated totals."

    Design: Corner/cross_cutting_complexity_layers/derived_order_estimated_reconciles_on_line_add
    """
    store = create_store()
    customer = create_customer(email="cc29@x.com")
    a = create_product(store["id"], sku="A", name="A", unit_price_cents=349)
    b = create_product(store["id"], sku="B", name="B", unit_price_cents=500)
    slot = create_slot(store["id"], capacity=1)
    ch = make_customer_headers(customer["id"])
    order = place_order(store["id"], customer["id"], slot["id"], slot["version"],
                        [{"product_id": a["id"], "requested_qty": 1}])
    assert order["estimated_total_cents"] == 349

    validate_success(
        api.create_order_line(
            {"order_id": order["id"], "product_id": b["id"], "requested_qty": 1}, ch),
        201,
    )
    after = validate_success(api.get_order(order["id"], ch))
    assert after["estimated_total_cents"] == 849, "349 + 500 after cart edit"
