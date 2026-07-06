"""Product CRUD and defaults, day computed pools, listings, RBAC denials, auth, and
compensation/visibility of derived fields."""
import pytest

from test_helpers import (
    api_client as _ac,
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    TEST_USERS,
    line_item,
    create_product, create_production_day,
    create_planned_batch, create_paid_order,
    setup_selling_day_with_baked_batch,
    setup_account_with_standing_order,
    schedule_delivery,
)

ADMIN = TEST_USERS["shop_admin_headers"]
BAKER = TEST_USERS["bake_manager_headers"]
CASHIER = TEST_USERS["cashier_headers"]
DRIVER = TEST_USERS["route_driver_headers"]

NON_EXISTENT = "00000000-0000-4000-8000-000000000000"


# =====================================================================
# Corner/entities/create_product_returns_201_with_fields  (1)
# =====================================================================
def test_create_product_returns_201_and_active_true(api):
    """PRD §3.1: "The system also tracks an active flag, which is true on creation."

    Design: Corner/entities/create_product_returns_201_with_fields
    """
    resp = _ac.create_product(
        {"sku": "PLAIN", "name": "Plain Bagel", "category": "BAGEL",
         "unit_price_cents": 110, "dozen_price_cents": 1100, "bulk_threshold": 24,
         "bulk_unit_price_cents": 90, "unit_cost_cents": 38},
        ADMIN)
    data = validate_success(resp, expected_status=201)
    assert data["sku"] == "PLAIN"
    assert data["active"] is True


# =====================================================================
# Corner/entities/get_product_not_found  (1)
# =====================================================================
def test_get_missing_product_returns_not_found(api):
    """PRD §2.6: "If any referenced resource in the path or body does not exist, the
    request is rejected with ERR_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/get_product_not_found
    """
    resp = _ac.get_product(NON_EXISTENT, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# =====================================================================
# Corner/entities/create_product_missing_required_field  (1)
# =====================================================================
def test_create_product_missing_unit_price_rejected(api):
    """PRD §2.7: "fourth, request-body well-formedness — required fields present, enum
    values valid, every line quantity at least 1, and line_items non-empty where a body
    supplies them (ERR_INVALID_REQUEST, HTTP 422)."

    Design: Corner/entities/create_product_missing_required_field
    """
    resp = _ac.create_product(
        {"sku": "X", "name": "X", "category": "DONUT",
         "dozen_price_cents": 1500, "bulk_unit_price_cents": 110, "unit_cost_cents": 45},
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# =====================================================================
# Corner/entities/product_bulk_threshold_default_applied  (1)
# =====================================================================
def test_product_bulk_threshold_defaults_to_24(api):
    """PRD §3.1: "The bulk_threshold is optional on creation and defaults to 24 when
    omitted."

    Design: Corner/entities/product_bulk_threshold_default_applied
    """
    resp = _ac.create_product(
        {"sku": "CINN", "name": "Cinnamon Donut", "category": "DONUT",
         "unit_price_cents": 160, "dozen_price_cents": 1600,
         "bulk_unit_price_cents": 120, "unit_cost_cents": 50},
        ADMIN)
    data = validate_success(resp, expected_status=201)
    assert data["bulk_threshold"] == 24, (
        f"omitted bulk_threshold defaults to 24; got {data['bulk_threshold']}")


# =====================================================================
# Corner/entities/production_day_computed_pools_zero_before_reconcile  (1)
# =====================================================================
def test_open_day_pools_read_zero(api):
    """PRD §3.2: "A freshly opened day enters status OPEN, and all of its computed
    reconciliation pools start at zero."

    Design: Corner/entities/production_day_computed_pools_zero_before_reconcile
    """
    day = create_production_day()
    fetched = validate_success(_ac.get_production_day(day["id"], ADMIN))
    assert fetched["status"] == "OPEN"
    assert fetched["gross_sales_cents"] == 0
    assert fetched["reconciliation_variance_cents"] == 0


# =====================================================================
# Corner/entities/list_production_days_paginated_envelope  (1)
# =====================================================================
def test_list_production_days_paginated(api):
    """PRD §2.3: "For every list response, the meta object carries limit, offset,
    total_count (the total number of records matching the query before pagination), and
    has_more (true when records remain beyond the returned page)."

    Design: Corner/entities/list_production_days_paginated_envelope
    """
    create_production_day()
    resp = _ac.list_production_days(ADMIN)
    data, meta = validate_paginated(resp)
    assert isinstance(data, list)
    assert meta["total_count"] >= 1


# =====================================================================
# Corner/endpoints/list_batches_by_day_reverse_reachability  (1)
# =====================================================================
def test_list_bake_batches_for_day(api):
    """PRD §3.3: "Batches for a day can be listed (optionally filtered by product_id)
    and fetched individually."

    Design: Corner/endpoints/list_batches_by_day_reverse_reachability
    """
    glazed = create_product("GLAZED")
    day = create_production_day()
    create_planned_batch(day["id"], glazed["id"], par_qty=30)
    resp = _ac.list_bake_batches(day["id"], BAKER)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, f"one batch under the day; got {meta['total_count']}"


# =====================================================================
# Corner/endpoints/list_deliveries_by_standing_order_reverse_reachability  (1)
# =====================================================================
def test_list_deliveries_for_standing_order(api):
    """PRD §3.6: "the deliveries realized from a given standing order can be listed
    through it."

    Design: Corner/endpoints/list_deliveries_by_standing_order_reverse_reachability
    """
    _account, so, _products = setup_account_with_standing_order([("GLAZED", 12)],
                                                               delivery_dow=3)
    day = create_production_day()
    schedule_delivery(day["id"], so["id"],
                      "2027-06-07T08:00:00Z", "2027-06-07T09:00:00Z")
    resp = _ac.list_standing_order_deliveries(so["id"], ADMIN)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, (
        f"one delivery realized from the standing order; got {meta['total_count']}")


# =====================================================================
# Corner/validations/missing_auth_header_rejected  (1)
# =====================================================================
def test_missing_auth_header_rejected(api):
    """PRD §2.1: "If either header is missing or invalid, the request is rejected with
    ERR_MISSING_AUTH (HTTP 401) before any other processing."

    Design: Corner/validations/missing_auth_header_rejected
    """
    resp = _ac.list_production_days({})
    validate_error(resp, ApiErrorId.ERR_MISSING_AUTH.value)


# =====================================================================
# Corner/rbac/cashier_cannot_create_product  (1)
# =====================================================================
def test_cashier_cannot_create_product(api):
    """PRD §2.1: "When the headers are present but the role is not permitted to perform
    the requested operation, the request is rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."

    Design: Corner/rbac/cashier_cannot_create_product
    """
    resp = _ac.create_product(
        {"sku": "GLAZED", "name": "Glazed Donut", "category": "DONUT",
         "unit_price_cents": 150, "dozen_price_cents": 1500, "bulk_threshold": 24,
         "bulk_unit_price_cents": 110, "unit_cost_cents": 45},
        CASHIER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# =====================================================================
# Corner/rbac/cashier_cannot_reconcile_day  (1)
# =====================================================================
def test_cashier_cannot_reconcile_day(api):
    """PRD §2.1: "When the headers are present but the role is not permitted to perform
    the requested operation, the request is rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."

    Design: Corner/rbac/cashier_cannot_reconcile_day
    """
    day = create_production_day()
    fetched = validate_success(_ac.get_production_day(day["id"], ADMIN))
    resp = _ac.reconcile_day(
        day["id"], {"expected_production_day_version": fetched["version"]}, CASHIER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# =====================================================================
# Corner/rbac/route_driver_cannot_invoice_delivery  (1)
# =====================================================================
def test_route_driver_cannot_invoice_delivery(api):
    """PRD §2.1: "When the headers are present but the role is not permitted to perform
    the requested operation, the request is rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."

    Design: Corner/rbac/route_driver_cannot_invoice_delivery
    """
    _account, so, _products = setup_account_with_standing_order([("GLAZED", 12)],
                                                               delivery_dow=3)
    day = create_production_day()
    delivery = schedule_delivery(day["id"], so["id"],
                                 "2027-06-08T08:00:00Z", "2027-06-08T09:00:00Z")
    validate_success(_ac.pick_delivery(day["id"], delivery["id"], DRIVER))
    validate_success(_ac.deliver_delivery(day["id"], delivery["id"], DRIVER))
    resp = _ac.invoice_delivery(day["id"], delivery["id"], DRIVER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# =====================================================================
# Corner/cross_cutting_complexity_layers/refund_restores_batch_stock_derived_field  (1)
# =====================================================================
def test_refund_restores_batch_remaining_and_sold(api):
    """PRD §3.5: "Both reversals restore each line product's batch sold_qty and
    remaining_qty (and restore markdown_sold_qty for marked-down lines)."

    Design: Corner/cross_cutting_complexity_layers/refund_restores_batch_stock_derived_field
    """
    day, product, batch = setup_selling_day_with_baked_batch("GLAZED", par_qty=30)
    order = create_paid_order(day["id"], [line_item(product["id"], 12)])
    refunded = validate_success(_ac.refund_retail_order(day["id"], order["id"], ADMIN))
    assert refunded["status"] == "REFUNDED"
    fetched = validate_success(_ac.get_bake_batch(day["id"], batch["id"], BAKER))
    assert fetched["remaining_qty"] == 30, f"got {fetched['remaining_qty']}"
    assert fetched["sold_qty"] == 0, f"got {fetched['sold_qty']}"


# =====================================================================
# Corner/consistency_model/immediate_visibility_on_pay  (1)
# =====================================================================
def test_pay_immediately_visible_on_batch(api):
    """PRD §2.8: "Paying a retail order draws down batch stock and accrues loyalty value."
    PRD §3.5: "When a retail order is paid, the stock cascade decrements each line
    product's batch sold_qty and remaining_qty."

    Design: Corner/consistency_model/immediate_visibility_on_pay
    """
    day, product, batch = setup_selling_day_with_baked_batch("GLAZED", par_qty=30)
    create_paid_order(day["id"], [line_item(product["id"], 6)])
    fetched = validate_success(_ac.get_bake_batch(day["id"], batch["id"], BAKER))
    assert fetched["sold_qty"] == 6, f"got {fetched['sold_qty']}"
    assert fetched["remaining_qty"] == 24, f"got {fetched['remaining_qty']}"
