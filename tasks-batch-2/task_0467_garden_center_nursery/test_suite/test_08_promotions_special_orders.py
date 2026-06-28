"""Seasonal promotion windows and special-order procurement.

Difficulty: promotion_plain_window_overlap.
Corner: receive_unapproved_special_order_rejected, special_order_receive_mints_quarantine_lot,
fk_reverse_special_order_inventory_lots.
"""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error, validate_paginated,
    factories as F, fixtures as X,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INV = TEST_USERS["inventory_manager_headers"]
CLERK = TEST_USERS["sales_clerk_headers"]


# ---------------------------------------------------------------------------
# Difficulty: promotion_plain_window_overlap
# ---------------------------------------------------------------------------
def test_overlapping_colliding_scope_promotion_rejected(api):
    """PRD §3.9: "At creation, a promotion's window must not overlap any other
    scheduled or active promotion on the same nursery whose scope collides with it —
    scopes collide when they are the same category, or when either one is `ALL`."

    Design: Difficulty/resource_temporal_overlap/promotion_plain_window_overlap
    """
    nursery = X.create_nursery()
    X.create_promotion(nursery["id"], name="Spring Plants", category_scope="LIVE_PLANT",
                       discount_pct=10, starts_at="2026-04-01T00:00:00Z", ends_at="2026-05-01T00:00:00Z")
    # ALL scope overlaps the LIVE_PLANT window and collides.
    resp = api.create_promotion(
        nursery["id"],
        F.create_promotion_payload(name="Everything Sale", category_scope="ALL", discount_pct=20,
                                   starts_at="2026-04-15T00:00:00Z", ends_at="2026-04-20T00:00:00Z"),
        CLERK,
    )
    validate_error(resp, ApiErrorId.ERR_PROMOTION_WINDOW_CONFLICT.value)


def test_abutting_promotion_window_allowed(api):
    """PRD §3.9: "Windows that merely abut — one ending exactly when the next begins
    — are permitted."

    Design: Difficulty/resource_temporal_overlap/promotion_plain_window_overlap
    """
    nursery = X.create_nursery()
    X.create_promotion(nursery["id"], name="Spring Plants", category_scope="LIVE_PLANT",
                       discount_pct=10, starts_at="2026-04-01T00:00:00Z", ends_at="2026-05-01T00:00:00Z")
    # Same scope, window starts exactly when the first ends -> abuts, allowed.
    resp = api.create_promotion(
        nursery["id"],
        F.create_promotion_payload(name="Summer Plants", category_scope="LIVE_PLANT", discount_pct=15,
                                   starts_at="2026-05-01T00:00:00Z", ends_at="2026-06-01T00:00:00Z"),
        CLERK,
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Corner: special orders
# ---------------------------------------------------------------------------
def test_receive_unapproved_special_order_rejected(api):
    """PRD §3.7: "Receiving an approved special order, performed by an inventory
    manager, moves it from `APPROVED` to the terminal `RECEIVED` status and is
    permitted only when the order is currently `APPROVED` (otherwise
    `ERR_SPECIAL_ORDER_NOT_APPROVED`)."

    Design: Corner/state_machines/receive_unapproved_special_order_rejected
    """
    nursery = X.create_nursery()
    account = X.create_account(nursery["id"], account_type="LANDSCAPER_B2B",
                               display_name="Acme Land", credit_limit_cents=100000)
    product = X.create_live_plant(nursery["id"], sku="PL-SO", name="Bonsai",
                                  hardiness_min_zone=5, hardiness_max_zone=9,
                                  unit_price_cents=8000, warranty_days=90, warranty_pct=50)
    so = X.create_special_order(account["id"], product["id"], requested_qty=3, quoted_unit_cost_cents=5000)
    resp = api.receive_special_order(so["id"], INV)
    validate_error(resp, ApiErrorId.ERR_SPECIAL_ORDER_NOT_APPROVED.value)


def test_special_order_approve_pins_deposit_and_receive_mints_lot(api):
    """PRD §3.7: "the deposit is that raw amount multiplied by the deposit percentage
    of 30, divided by 100, with the result rounded up to whole cents."
    PRD §3.7: "Receiving mints a brand-new inventory lot for the special order's
    product: the new lot's received quantity equals the special order's requested
    quantity, its unit cost equals the quoted unit cost, its `special_order_id` is
    set to this special order, and it starts in `QUARANTINE`."

    Design: Corner/state_machines/special_order_receive_mints_quarantine_lot
    """
    nursery = X.create_nursery()
    account = X.create_account(nursery["id"], account_type="LANDSCAPER_B2B",
                               display_name="Acme Land", credit_limit_cents=100000)
    product = X.create_live_plant(nursery["id"], sku="PL-SO2", name="Juniper",
                                  hardiness_min_zone=4, hardiness_max_zone=9,
                                  unit_price_cents=1000, warranty_days=60, warranty_pct=50)
    so = X.create_special_order(account["id"], product["id"], requested_qty=7, quoted_unit_cost_cents=333)
    approved = validate_success(api.approve_special_order(so["id"], INV))
    # ceil(7 * 333 * 30 / 100) = ceil(2331*30/100) = ceil(699.3) = 700
    assert approved["deposit_cents"] == 700
    received = validate_success(api.receive_special_order(so["id"], INV))
    assert received["status"] == "RECEIVED"
    assert received["received_lot_id"] is not None
    lot = validate_success(api.get_inventory_lot(received["received_lot_id"], INV))
    assert lot["status"] == "QUARANTINE"
    assert lot["received_qty"] == 7
    assert lot["special_order_id"] == so["id"]


def test_fk_reverse_special_order_inventory_lots(api):
    """PRD §3.7: "Receiving mints a brand-new inventory lot for the special order's
    product ... its `special_order_id` is set to this special order".

    Design: Corner/endpoints/fk_reverse_special_order_inventory_lots
    """
    nursery = X.create_nursery()
    account = X.create_account(nursery["id"], account_type="LANDSCAPER_B2B",
                               display_name="Acme Land", credit_limit_cents=100000)
    product = X.create_live_plant(nursery["id"], sku="PL-FK", name="Yew",
                                  hardiness_min_zone=4, hardiness_max_zone=9,
                                  unit_price_cents=2000, warranty_days=60, warranty_pct=50)
    so = X.create_special_order(account["id"], product["id"], requested_qty=5, quoted_unit_cost_cents=1000)
    validate_success(api.approve_special_order(so["id"], INV))
    validate_success(api.receive_special_order(so["id"], INV))
    data, meta = validate_paginated(api.list_special_order_inventory_lots(so["id"], INV))
    assert meta["total_count"] == 1
    assert data[0]["special_order_id"] == so["id"]
    assert data[0]["received_qty"] == 5
