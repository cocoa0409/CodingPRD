"""Inventory-lot OCC adjustment (stale + correct version) and point-of-sale
loyalty-redemption sufficiency."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS,
    adjust_lot_payload, create_product_sale_payload,
    make_store, make_product, make_customer, make_lot,
)

INVMGR = TEST_USERS["inventory_manager_headers"]
CLERK = TEST_USERS["store_clerk_headers"]


# ---------------------------------------------------------------------------
# Corner: cross_cutting / OCC stale lot version on adjust
# ---------------------------------------------------------------------------
def test_occ_stale_lot_version_on_adjust_returns_412(api):
    """PRD §2.10: "A request to adjust an inventory lot's on-hand quantity must
    carry `expected_lot_version` matching the target lot's current `version`. If
    the lot's version has advanced since the client last read it ... the
    adjustment is rejected with `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_lot_version_on_adjust_returns_412
    """
    store = make_store()
    product = make_product()
    lot = make_lot(store["id"], product["id"], quantity_on_hand=10)
    original_version = lot["version"]
    # First adjust succeeds and bumps the version (1 → 2).
    validate_success(
        api.adjust_inventory_lot(
            lot["id"], adjust_lot_payload(5, original_version), INVMGR
        ), 200,
    )
    # Second adjust carries the now-stale original version.
    res = api.adjust_inventory_lot(
        lot["id"], adjust_lot_payload(3, original_version), INVMGR
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)


# ---------------------------------------------------------------------------
# Corner: cross_cutting / OCC correct lot version adjust succeeds
# ---------------------------------------------------------------------------
def test_occ_correct_lot_version_adjust_succeeds_and_bumps_version(api):
    """PRD §3.2: "When the version matches, the `delta` is added to
    `quantity_on_hand` ... The adjustment increments the lot's `version`."
    PRD §2.4: "The `version` field is an integer that begins at its initial value
    when the resource is created and increments by one on every mutation."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_lot_version_adjust_succeeds_and_bumps_version
    """
    store = make_store()
    product = make_product()
    lot = make_lot(store["id"], product["id"], quantity_on_hand=10)
    res = api.adjust_inventory_lot(
        lot["id"], adjust_lot_payload(5, lot["version"]), INVMGR
    )
    adjusted = validate_success(res, 200)
    assert adjusted["quantity_on_hand"] == 15
    assert adjusted["version"] == 2


# ---------------------------------------------------------------------------
# Corner: validations / redeem more loyalty points than balance
# ---------------------------------------------------------------------------
def test_redeem_more_points_than_balance_rejected(api):
    """PRD §3.12: "The redemption check requires the requested `redeem_points`
    not to exceed the customer's current `loyalty_points` balance (otherwise
    `ERR_INSUFFICIENT_LOYALTY_POINTS`)."

    Design: Corner/validations/redeem_more_points_than_balance_rejected
    """
    store = make_store()
    product = make_product()
    make_lot(store["id"], product["id"], quantity_on_hand=10)
    customer = make_customer(store["id"])  # new customer: loyalty_points == 0
    res = api.create_product_sale(
        create_product_sale_payload(
            store["id"], product["id"], customer["id"],
            quantity=1, redeem_points=100,
        ), CLERK,
    )
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_LOYALTY_POINTS)
