"""Cancellation compensation chain and its conserved-quantity invariants.

The depth-3 cancel cascade (work order -> material orders -> fabric stock), the
fabric-yard conservation invariant, the wallet-refund money invariant, and terminal
state lockdown on decline.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    create_line_item_payload,
    register_customer, register_fabric_sku,
    create_approved_order, create_awaiting_approval_order,
    place_material_order, reupholstery_line_item,
    get_work_order, current_version,
    make_customer_headers, factories,
    TEST_USERS,
)

CLERK = TEST_USERS["intake_clerk_headers"]
ESTIMATOR = TEST_USERS["estimator_headers"]
MANAGER = TEST_USERS["shop_manager_headers"]


# ---------------------------------------------------------------------------
# Depth-3 cancel cascade: WO -> MaterialOrder -> FabricSku.in_stock_yards
# ---------------------------------------------------------------------------
def test_cancel_cascade_returns_material_and_fabric_stock(api):
    """PRD §3.8: "Every material order still in `ORDERED` status moves to `CANCELLED`, and
    its reserved fabric yards are returned to the corresponding `FabricSku.in_stock_yards`;
    the order's `materials_committed_cents` is reconciled to 0."

    Design: Difficulty/transitive_cascade/cancel_cascade_materialorder_then_fabric_stock_depth3
    """
    fab = register_fabric_sku(price_cents_per_yard=1800, in_stock_yards=100)
    cust, wo, _, _ = create_approved_order(
        service_type="REUPHOLSTERY", deposit_amount_cents=12090,
        line_items=[reupholstery_line_item(fab["id"], yardage_required=6, labor_hours=4,
                                           piece_label="Bench")],
    )
    mo = place_material_order(wo["id"], fabric_sku_id=fab["id"], yards_ordered=6)
    v = current_version(wo["id"])
    validate_success(api.cancel_work_order(
        wo["id"], factories.cancel_payload(v, refund_destination="ORIGINAL"), MANAGER), 200)

    mo_after = validate_success(api.get_material_order(mo["id"], MANAGER), 200)
    assert mo_after["status"] == "CANCELLED"
    fab_after = validate_success(api.get_fabric_sku(fab["id"], MANAGER), 200)
    assert fab_after["in_stock_yards"] == 100
    wo_after = get_work_order(wo["id"])
    assert wo_after["materials_committed_cents"] == 0
    assert wo_after["status"] == "CANCELLED"


def test_cancel_cascade_refunds_paid_amount_to_zero(api):
    """PRD §3.8: "A `REFUND` payment is recorded for the full `amount_paid_cents` directed to
    the chosen `refund_destination`; when the destination is `WALLET`, the customer's
    `store_credit_cents` increases by that amount. The order's `amount_paid_cents` is
    reconciled to 0, its `balance_due_cents` is reconciled, the order moves to `CANCELLED`,
    and its `version` increments by one."

    Design: Difficulty/transitive_cascade/cancel_cascade_materialorder_then_fabric_stock_depth3
    """
    fab = register_fabric_sku(price_cents_per_yard=1800, in_stock_yards=100)
    cust, wo, _, _ = create_approved_order(
        service_type="REUPHOLSTERY", deposit_amount_cents=12090,
        line_items=[reupholstery_line_item(fab["id"], yardage_required=6, labor_hours=4,
                                           piece_label="Bench2")],
    )
    place_material_order(wo["id"], fabric_sku_id=fab["id"], yards_ordered=6)
    v = current_version(wo["id"])
    validate_success(api.cancel_work_order(
        wo["id"], factories.cancel_payload(v, refund_destination="ORIGINAL"), MANAGER), 200)
    wo_after = get_work_order(wo["id"])
    assert wo_after["amount_paid_cents"] == 0
    assert wo_after["status"] == "CANCELLED"


def test_cancel_conserves_fabric_yards(api):
    """PRD §2.7: "When a work order is cancelled, every fabric yard that was reserved from
    stock is returned to its `FabricSku.in_stock_yards` (the yard-conservation invariant),
    and every cent the customer paid is refunded in full (the refund invariant) — to the
    original method, or, when the refund is directed to the wallet, credited to the
    customer's `store_credit_cents`."

    Design: Difficulty/compensating_invariant/cancel_conserves_fabric_yards
    """
    fab = register_fabric_sku(price_cents_per_yard=1800, in_stock_yards=100)
    cust, wo, _, _ = create_approved_order(
        service_type="REUPHOLSTERY", deposit_amount_cents=12090,
        line_items=[reupholstery_line_item(fab["id"], yardage_required=6, labor_hours=4,
                                           piece_label="Settee")],
    )
    place_material_order(wo["id"], fabric_sku_id=fab["id"], yards_ordered=6)
    # confirm reservation occurred before cancel
    fab_reserved = validate_success(api.get_fabric_sku(fab["id"], MANAGER), 200)
    assert fab_reserved["in_stock_yards"] == 94
    v = current_version(wo["id"])
    validate_success(api.cancel_work_order(
        wo["id"], factories.cancel_payload(v, refund_destination="ORIGINAL"), MANAGER), 200)
    fab_after = validate_success(api.get_fabric_sku(fab["id"], MANAGER), 200)
    assert fab_after["in_stock_yards"] == 100


def test_cancel_conserves_fabric_yards_larger_reservation(api):
    """PRD §2.7: "When a work order is cancelled, every fabric yard that was reserved from
    stock is returned to its `FabricSku.in_stock_yards` (the yard-conservation invariant),
    and every cent the customer paid is refunded in full (the refund invariant) — to the
    original method, or, when the refund is directed to the wallet, credited to the
    customer's `store_credit_cents`."

    Design: Difficulty/compensating_invariant/cancel_conserves_fabric_yards
    """
    fab = register_fabric_sku(price_cents_per_yard=1800, in_stock_yards=100)
    cust, wo, _, _ = create_approved_order(
        service_type="REUPHOLSTERY", deposit_amount_cents=30000,
        line_items=[reupholstery_line_item(fab["id"], yardage_required=10, labor_hours=4,
                                           piece_label="Big settee")],
    )
    place_material_order(wo["id"], fabric_sku_id=fab["id"], yards_ordered=10)
    fab_reserved = validate_success(api.get_fabric_sku(fab["id"], MANAGER), 200)
    assert fab_reserved["in_stock_yards"] == 90
    v = current_version(wo["id"])
    validate_success(api.cancel_work_order(
        wo["id"], factories.cancel_payload(v, refund_destination="ORIGINAL"), MANAGER), 200)
    fab_after = validate_success(api.get_fabric_sku(fab["id"], MANAGER), 200)
    assert fab_after["in_stock_yards"] == 100


def test_wallet_refund_conserves_money_to_store_credit(api):
    """PRD §3.8: "A `REFUND` payment is recorded for the full `amount_paid_cents` directed to
    the chosen `refund_destination`; when the destination is `WALLET`, the customer's
    `store_credit_cents` increases by that amount. The order's `amount_paid_cents` is
    reconciled to 0, its `balance_due_cents` is reconciled, the order moves to `CANCELLED`,
    and its `version` increments by one."

    Design: Difficulty/compensating_invariant/wallet_refund_conserves_money_to_store_credit
    """
    fab = register_fabric_sku(price_cents_per_yard=1800, in_stock_yards=100)
    cust, wo, _, _ = create_approved_order(
        service_type="REUPHOLSTERY", deposit_amount_cents=12090,
        line_items=[reupholstery_line_item(fab["id"], yardage_required=6, labor_hours=4,
                                           piece_label="Daybed")],
    )
    v = current_version(wo["id"])
    validate_success(api.cancel_work_order(
        wo["id"], factories.cancel_payload(v, refund_destination="WALLET"), MANAGER), 200)
    cust_after = validate_success(api.get_customer(cust["id"], MANAGER), 200)
    assert cust_after["store_credit_cents"] == 12090
    wo_after = get_work_order(wo["id"])
    assert wo_after["amount_paid_cents"] == 0
    assert wo_after["status"] == "CANCELLED"


def test_wallet_refund_records_full_refund_payment(api):
    """PRD §3.8: "A reversal is therefore always modeled as a new `REFUND` payment rather
    than by mutating an existing one."
    PRD §3.8: "A `REFUND` payment is recorded for the full `amount_paid_cents` directed to
    the chosen `refund_destination`; when the destination is `WALLET`, the customer's
    `store_credit_cents` increases by that amount."

    Design: Difficulty/compensating_invariant/wallet_refund_conserves_money_to_store_credit
    """
    fab = register_fabric_sku(price_cents_per_yard=1800, in_stock_yards=100)
    cust, wo, _, _ = create_approved_order(
        service_type="REUPHOLSTERY", deposit_amount_cents=12090,
        line_items=[reupholstery_line_item(fab["id"], yardage_required=6, labor_hours=4,
                                           piece_label="Daybed2")],
    )
    v = current_version(wo["id"])
    validate_success(api.cancel_work_order(
        wo["id"], factories.cancel_payload(v, refund_destination="WALLET"), MANAGER), 200)
    payments_resp = api.list_work_order_payments(wo["id"], MANAGER)
    payments = payments_resp.json()["data"]
    refunds = [p for p in payments if p["kind"] == "REFUND"]
    assert len(refunds) == 1
    assert refunds[0]["amount_cents"] == 12090


# ---------------------------------------------------------------------------
# Terminal state lockdown — decline after decline
# ---------------------------------------------------------------------------
def test_decline_after_decline_returns_invalid_state(api):
    """PRD §3.4: "Declining moves the active estimate to `DECLINED` and the order to
    `DECLINED`, a terminal state."
    PRD §3.3: "A revision or approval attempt made when the order is not in a permitted
    status is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/decline_after_decline_returns_invalid_state
    """
    cust, wo, est, _ = create_awaiting_approval_order(
        service_type="REPAIR",
        line_items=[create_line_item_payload(piece_label="P", yardage_required=0, labor_hours=1)],
    )
    headers = make_customer_headers(cust["id"])
    validate_success(api.decline_work_order(wo["id"], headers), 200)
    res = api.decline_work_order(wo["id"], headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    assert get_work_order(wo["id"])["status"] == "DECLINED"
