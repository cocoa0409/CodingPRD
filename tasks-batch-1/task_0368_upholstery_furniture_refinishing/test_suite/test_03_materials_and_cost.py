"""Material orders, provisional vs finalized cost, the estimate/final-invoice divergence.

The two financial views (forward-looking estimate vs chronological actual invoice),
the provisional-vs-finalized cost gap on a material order, materials reconciliation,
receive idempotency, soft-delete of a referenced fabric SKU, and FK-filtered lists.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    create_line_item_payload,
    register_customer, register_fabric_sku, register_foam_spec, register_shop_day,
    create_approved_order, create_ready_for_fulfillment_order,
    place_material_order, receive_material_order,
    open_intake_work_order, create_estimating_work_order,
    reupholstery_line_item, get_work_order, current_version,
    make_customer_headers, factories,
    TEST_USERS,
)

CLERK = TEST_USERS["intake_clerk_headers"]
ESTIMATOR = TEST_USERS["estimator_headers"]
MANAGER = TEST_USERS["shop_manager_headers"]


# ---------------------------------------------------------------------------
# Estimate (forward-looking) vs final invoice (chronological actuals) diverge
# ---------------------------------------------------------------------------
def test_estimate_and_final_invoice_diverge_on_received_prices(api):
    """PRD §3.7: "The order's `final_invoice_cents` is the labor component plus the
    chronological materials actuals plus that carried rush surcharge. Because received
    prices can differ from the catalog prices used in the estimate, this figure diverges
    from `estimate_total_cents` precisely by the accumulated provisional-versus-finalized
    deltas."

    Design: Difficulty/dual_variant_calc/workorder_estimate_vs_final_invoice_diverge
    """
    fab = register_fabric_sku(price_cents_per_yard=1800, in_stock_yards=100)
    foam = register_foam_spec(price_cents_per_board_foot=350)
    _, wo, day, leg, _ = create_ready_for_fulfillment_order(
        service_type="REUPHOLSTERY",
        line_items=[reupholstery_line_item(fab["id"], yardage_required=6, labor_hours=4,
                                           foam_spec_id=foam["id"], board_feet_required=10,
                                           piece_label="Sofa 3-cushion")],
        deposit_amount_cents=12090,
        shop_day_date="2026-04-01", shop_capacity=8,
        material_orders=[
            ({"fabric_sku_id": fab["id"], "yards_ordered": 6},
             {"received_fabric_price_cents_per_yard": 2000}),
            ({"foam_spec_id": foam["id"], "board_feet_ordered": 10},
             {"received_foam_price_cents_per_board_foot": 400}),
        ],
    )
    assert wo["estimate_total_cents"] == 40300
    assert wo["final_invoice_cents"] == 42000


def test_final_invoice_diverges_from_estimate_by_1700(api):
    """PRD §3.7: "Its materials component, however, is the chronological sum of finalized
    actual costs: walk the order's `RECEIVED` material orders in `created_at` ascending order
    and accumulate their `finalized_cost_cents`, excluding any `CANCELLED` material order
    entirely."

    Design: Difficulty/dual_variant_calc/workorder_estimate_vs_final_invoice_diverge
    """
    fab = register_fabric_sku(price_cents_per_yard=1800, in_stock_yards=100)
    foam = register_foam_spec(price_cents_per_board_foot=350)
    _, wo, day, leg, _ = create_ready_for_fulfillment_order(
        service_type="REUPHOLSTERY",
        line_items=[reupholstery_line_item(fab["id"], yardage_required=6, labor_hours=4,
                                           foam_spec_id=foam["id"], board_feet_required=10,
                                           piece_label="Sofa 3-cushion")],
        deposit_amount_cents=12090,
        shop_day_date="2026-04-02", shop_capacity=8,
        material_orders=[
            ({"fabric_sku_id": fab["id"], "yards_ordered": 6},
             {"received_fabric_price_cents_per_yard": 2000}),
            ({"foam_spec_id": foam["id"], "board_feet_ordered": 10},
             {"received_foam_price_cents_per_board_foot": 400}),
        ],
    )
    assert wo["final_invoice_cents"] - wo["estimate_total_cents"] == 1700


# ---------------------------------------------------------------------------
# Provisional vs finalized cost on a single material order
# ---------------------------------------------------------------------------
def test_material_order_provisional_cost_from_catalog(api):
    """PRD §3.5: "At order time the material order's `provisional_cost_cents` is computed
    forward-looking from catalog prices: the `yards_ordered` times the fabric SKU's
    `price_cents_per_yard` rounded to whole cents, plus the `board_feet_ordered` times the
    foam spec's `price_cents_per_board_foot` rounded to whole cents, the two rounded terms
    then summed."

    Design: Difficulty/dual_variant_calc/materialorder_provisional_vs_finalized_cost_diverge
    """
    fab = register_fabric_sku(price_cents_per_yard=1800, in_stock_yards=100)
    _, wo, _, _ = create_approved_order(
        service_type="REUPHOLSTERY",
        line_items=[reupholstery_line_item(fab["id"], yardage_required=6, labor_hours=4,
                                           piece_label="Armchair")],
    )
    mo = place_material_order(wo["id"], fabric_sku_id=fab["id"], yards_ordered=6)
    assert mo["provisional_cost_cents"] == 10800  # 6 * 1800


def test_material_order_finalized_cost_from_received_price(api):
    """PRD §3.5: "The order's `finalized_cost_cents` is then computed as the `yards_ordered`
    times `received_fabric_price_cents_per_yard` rounded to whole cents, plus the
    `board_feet_ordered` times `received_foam_price_cents_per_board_foot` rounded to whole
    cents, the two terms summed."

    Design: Difficulty/dual_variant_calc/materialorder_provisional_vs_finalized_cost_diverge
    """
    fab = register_fabric_sku(price_cents_per_yard=1800, in_stock_yards=100)
    _, wo, _, _ = create_approved_order(
        service_type="REUPHOLSTERY",
        line_items=[reupholstery_line_item(fab["id"], yardage_required=6, labor_hours=4,
                                           piece_label="Armchair")],
    )
    mo = place_material_order(wo["id"], fabric_sku_id=fab["id"], yards_ordered=6)
    received = receive_material_order(mo["id"], received_fabric_price_cents_per_yard=2000)
    assert received["provisional_cost_cents"] == 10800
    assert received["finalized_cost_cents"] == 12000  # 6 * 2000
    assert received["finalized_cost_cents"] - received["provisional_cost_cents"] == 1200


# ---------------------------------------------------------------------------
# Receive idempotency
# ---------------------------------------------------------------------------
def test_receive_already_received_material_order_returns_invalid_state(api):
    """PRD §3.5: "A `ShopManager` receives an `ORDERED` order whose parent work order is in
    either `APPROVED` or `IN_PRODUCTION` status; otherwise the receive is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/receive_already_received_material_order_returns_invalid_state
    """
    fab = register_fabric_sku(price_cents_per_yard=1800, in_stock_yards=100)
    _, wo, _, _ = create_approved_order(
        service_type="REUPHOLSTERY", deposit_amount_cents=12090,
        line_items=[reupholstery_line_item(fab["id"], yardage_required=6, labor_hours=4,
                                           piece_label="S")],
    )
    mo = place_material_order(wo["id"], fabric_sku_id=fab["id"], yards_ordered=6)
    receive_material_order(mo["id"], received_fabric_price_cents_per_yard=2000)
    res = api.receive_material_order(
        mo["id"], {"received_fabric_price_cents_per_yard": 3000}, MANAGER)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = validate_success(api.get_material_order(mo["id"], MANAGER), 200)
    assert after["finalized_cost_cents"] == 12000


# ---------------------------------------------------------------------------
# Materials committed reconciliation on cancel of a single material order
# ---------------------------------------------------------------------------
def test_materials_committed_reconciled_on_material_cancel(api):
    """PRD §3.5: "Cancelling returns any fabric yards that were reserved against on-hand
    stock to the fabric SKU's `in_stock_yards`, decrements the parent work order's
    `materials_committed_cents` by this order's `provisional_cost_cents`, and moves the order
    to `CANCELLED`."

    Design: Corner/cross_cutting_complexity_layers/materials_committed_reconciled_on_material_cancel
    """
    fab = register_fabric_sku(price_cents_per_yard=1800, in_stock_yards=100)
    _, wo, _, _ = create_approved_order(
        service_type="REUPHOLSTERY", deposit_amount_cents=12090,
        line_items=[reupholstery_line_item(fab["id"], yardage_required=6, labor_hours=4,
                                           piece_label="Couch")],
    )
    mo = place_material_order(wo["id"], fabric_sku_id=fab["id"], yards_ordered=6)
    validate_success(api.cancel_material_order(mo["id"], MANAGER), 200)
    after = validate_success(api.get_material_order(mo["id"], MANAGER), 200)
    assert after["status"] == "CANCELLED"
    assert get_work_order(wo["id"])["materials_committed_cents"] == 0
    fab_after = validate_success(api.get_fabric_sku(fab["id"], MANAGER), 200)
    assert fab_after["in_stock_yards"] == 100


# ---------------------------------------------------------------------------
# Soft-delete: a discontinued fabric SKU keeps existing references resolvable
# ---------------------------------------------------------------------------
def test_discontinued_fabric_existing_reference_still_resolves(api):
    """PRD §3.1: "A fabric SKU begins `LISTED` and can later be marked `DISCONTINUED`; only
    a `LISTED` fabric may be selected on a new line item."

    Design: Corner/cross_cutting_complexity_layers/discontinued_fabric_existing_reference_still_resolves
    """
    fab = register_fabric_sku(price_cents_per_yard=1800, in_stock_yards=100)
    _, wo = open_intake_work_order(service_type="REUPHOLSTERY")
    li = validate_success(api.create_line_item(
        wo["id"],
        reupholstery_line_item(fab["id"], yardage_required=4, labor_hours=3, piece_label="Chair"),
        CLERK), 201)
    discontinued = validate_success(api.discontinue_fabric_sku(fab["id"], MANAGER), 200)
    assert discontinued["status"] == "DISCONTINUED"
    li_after = validate_success(api.get_line_item(li["id"], CLERK), 200)
    assert li_after["fabric_sku_id"] == fab["id"]


# ---------------------------------------------------------------------------
# FK-filtered list endpoints
# ---------------------------------------------------------------------------
def test_list_line_items_by_work_order(api):
    """PRD §2.8: "List endpoints that accept a foreign-key filter (such as filtering line
    items by `work_order_id`, `fabric_sku_id`, or `foam_spec_id`, material orders or
    fulfillment legs by their references, or estimates by `supersedes_estimate_id`) simply
    return the matching subset and never error on an absent filter match."

    Design: Corner/endpoints/list_line_items_by_work_order
    """
    cust, wo, items = create_estimating_work_order(
        service_type="REPAIR",
        line_items=[create_line_item_payload(piece_label="Only piece", yardage_required=0, labor_hours=2)],
    )
    res = api.list_work_order_line_items(wo["id"], ESTIMATOR)
    body = res.json()
    assert body["response_type"] == "array"
    assert len(body["data"]) == 1


def test_list_material_orders_by_fabric_sku(api):
    """PRD §2.8: "List endpoints that accept a foreign-key filter (such as filtering line
    items by `work_order_id`, `fabric_sku_id`, or `foam_spec_id`, material orders or
    fulfillment legs by their references, or estimates by `supersedes_estimate_id`) simply
    return the matching subset and never error on an absent filter match."

    Design: Corner/endpoints/list_material_orders_by_fabric_sku
    """
    fab = register_fabric_sku(price_cents_per_yard=1800, in_stock_yards=100)
    _, wo, _, _ = create_approved_order(
        service_type="REUPHOLSTERY", deposit_amount_cents=12090,
        line_items=[reupholstery_line_item(fab["id"], yardage_required=6, labor_hours=4,
                                           piece_label="Chair")],
    )
    place_material_order(wo["id"], fabric_sku_id=fab["id"], yards_ordered=6)
    res = api.list_material_orders(MANAGER, params={"fabric_sku_id": fab["id"]})
    body = res.json()
    assert body["response_type"] == "array"
    assert len(body["data"]) == 1
