"""CRUD surface, computed/default fields, system-field generation, initial
state, invalid-transition lockdown, and role-based access control.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    is_iso8601_timestamp,
    set_spot_rate,
    create_product,
    create_inventory_lot,
    create_customer,
    create_placed_sell_order,
    setup_layaway,
    NON_EXISTENT_UUID,
    TEST_USERS,
    make_customer_headers,
)

TRADER = TEST_USERS["trader_headers"]
SALES = TEST_USERS["sales_agent_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


# ─── Creation / retrieval / listing ───────────────────────────────────────

def test_create_product_returns_201_with_fields(api):
    """PRD §3.1: "A product carries a sku (a human catalog identifier, unique
    across products), a product_type of either BULLION or NUMISMATIC, the metal
    whose spot rate governs its value".

    Design: Corner/entities/create_product_returns_201_with_all_fields
    """
    res = api.create_product(
        {"sku": "AG-1OZ", "product_type": "BULLION", "metal": "SILVER",
         "weight_troy_oz": 1.0, "purity": 0.999, "min_sell_spread_pct": 0.06,
         "buy_spread_pct": 0.05}, TRADER)
    product = validate_success(res, 201)
    assert product["sku"] == "AG-1OZ"
    assert product["product_type"] == "BULLION"


def test_get_customer_returns_stored_data(api):
    """PRD §3.10: "lifetime_buy_payout_cents, the running sum of all settled
    buy-order payouts from the customer (initialized to 0), and store_credit_cents,
    the refundable credit balance (initialized to 0)".

    Design: Corner/entities/get_customer_returns_stored_data
    """
    customer = create_customer("Read Me")
    fetched = validate_success(api.get_customer(customer["id"], SALES), 200)
    assert fetched["full_name"] == "Read Me"
    assert fetched["lifetime_buy_payout_cents"] == 0
    assert fetched["store_credit_cents"] == 0


def test_list_inventory_lots_paginated_envelope(api):
    """PRD §2.3: "the meta object carries limit, offset, total_count (the total
    number of matching records before pagination), and has_more (true when records
    remain beyond the current page)."

    Design: Corner/entities/list_inventory_lots_returns_paginated_envelope
    """
    product = create_product(sku="PT-1OZ", product_type="BULLION", metal="PLATINUM",
                             weight_troy_oz=1.0, purity=0.9995, min_sell_spread_pct=0.07,
                             buy_spread_pct=0.06)
    create_inventory_lot(product["id"], total_qty=4, acquisition_unit_cost_cents=90_000)
    data, meta = validate_paginated(api.list_inventory_lots(TRADER))
    assert meta["total_count"] >= 1
    assert isinstance(meta["has_more"], bool)


def test_get_product_not_found_returns_404(api):
    """PRD §2.9: "Every such foreign key must resolve to an existing entity at
    request time, checked left to right after any path id, and an unresolved
    reference yields ERR_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/get_product_not_found_returns_404
    """
    res = api.get_product(NON_EXISTENT_UUID, TRADER)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_sell_order_missing_quantity_invalid_request(api):
    """PRD §2.7: "verifies that required body fields are present and well-typed ...
    a violation yields ERR_INVALID_REQUEST (HTTP 400)."

    Design: Corner/entities/create_sell_order_missing_required_returns_invalid_request
    """
    set_spot_rate("GOLD", 200_000)
    product = create_product(sku="AU-REQ", product_type="BULLION", metal="GOLD",
                             weight_troy_oz=1.0, purity=1.0, min_sell_spread_pct=0.05,
                             buy_spread_pct=0.04)
    customer = create_customer("No Qty")
    res = api.create_sell_order(
        {"customer_id": customer["id"], "product_id": product["id"]}, SALES)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_bullion_product_defaults_premium_and_ira_flag(api):
    """PRD §3.1: "A product may carry a numismatic_premium_cents, the per-unit
    collectible premium over metal value, which is a non-negative integer defaulting
    to 0." PRD §3.1: "ira_eligible (a boolean defaulting to false)".

    Design: Corner/entities/create_product_defaults_numismatic_premium_zero
    """
    product = create_product(sku="AU-DEFAULT", product_type="BULLION", metal="GOLD",
                             weight_troy_oz=1.0, purity=1.0, min_sell_spread_pct=0.05,
                             buy_spread_pct=0.04)
    assert product["numismatic_premium_cents"] == 0
    assert product["ira_eligible"] is False


def test_inventory_lot_computed_fields_initialized(api):
    """PRD §3.2: "the lot's available_qty is initialized to total_qty, while
    reserved_qty and sold_qty both start at 0, and the lot's status is AVAILABLE."

    Design: Corner/entities/inventory_lot_computed_fields_input_ignored
    """
    product = create_product(sku="AU-COMP", product_type="BULLION", metal="GOLD",
                             weight_troy_oz=1.0, purity=1.0, min_sell_spread_pct=0.05,
                             buy_spread_pct=0.04)
    lot = create_inventory_lot(product["id"], total_qty=7, acquisition_unit_cost_cents=100_000)
    assert lot["available_qty"] == 7
    assert lot["reserved_qty"] == 0
    assert lot["status"] == "AVAILABLE"


def test_create_product_invalid_metal_enum_rejected(api):
    """PRD §2.7: "enum fields fall within their declared domain ... a violation
    yields ERR_INVALID_REQUEST (HTTP 400)."

    Design: Corner/entities/create_product_invalid_enum_returns_invalid_request
    """
    res = api.create_product(
        {"sku": "BAD-METAL", "product_type": "BULLION", "metal": "COPPER",
         "weight_troy_oz": 1.0, "purity": 1.0, "min_sell_spread_pct": 0.05,
         "buy_spread_pct": 0.04}, TRADER)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_ira_account_bad_customer_fk_not_found(api):
    """PRD §2.9: "an unresolved reference yields ERR_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/create_ira_account_bad_customer_fk_returns_not_found
    """
    res = api.create_ira_account(
        {"customer_id": NON_EXISTENT_UUID, "custodian_name": "Ghost",
         "custodian_account_ref": "G-1"}, COMPLIANCE)
    validate_error(res, "ERR_NOT_FOUND")


# ─── System fields ─────────────────────────────────────────────────────────

def test_customer_create_stamps_version_and_created_at(api):
    """PRD §2.4: "an integer version that begins at 1 on creation and increments by
    exactly one on every mutation" and "a created_at timestamp in ISO 8601 UTC
    format with three fractional digits."

    Design: Corner/endpoints/system_fields_generated_on_customer_create
    """
    customer = create_customer("System Fields")
    assert customer["version"] == 1
    assert is_iso8601_timestamp(customer["created_at"])
    assert customer["created_at"]


# ─── Initial state & invalid transitions ────────────────────────────────────

def _placed_sell_order():
    set_spot_rate("GOLD", 200_000)
    product = create_product(sku="AU-SM2", product_type="BULLION", metal="GOLD",
                             weight_troy_oz=1.0, purity=1.0, min_sell_spread_pct=0.05,
                             buy_spread_pct=0.04)
    customer = create_customer("Fresh Order")
    return create_placed_sell_order(product["id"], customer["id"], quantity=1)


def test_new_sell_order_starts_placed(api):
    """PRD §3.3: "records the provisional_cogs_cents from the provisional
    cost-of-goods estimate, leaves final_cogs_cents and realized_margin_cents null,
    and sets the order status to PLACED."

    Design: Corner/state_machines/new_sell_order_starts_in_placed
    """
    order = _placed_sell_order()
    assert order["status"] == "PLACED"


def test_cancel_already_cancelled_sell_order_invalid_state(api):
    """PRD §3.3: "A placed sell order may instead be cancelled by a SalesAgent,
    which is allowed only from PLACED". PRD §2.7: "state — the target resource is in
    a state from which the requested transition is defined, else ERR_INVALID_STATE
    (409)".

    Design: Corner/state_machines/cancel_sell_order_already_cancelled_returns_invalid_state
    """
    order = _placed_sell_order()
    validate_success(api.cancel_sell_order(order["id"], SALES), 200)
    res = api.cancel_sell_order(order["id"], SALES)
    validate_error(res, "ERR_INVALID_STATE")
    stayed = validate_success(api.get_sell_order(order["id"], SALES), 200)
    assert stayed["status"] == "CANCELLED"


# ─── RBAC ────────────────────────────────────────────────────────────────────

def test_sales_agent_cannot_create_spot_rate(api):
    """PRD §2.1: "When both headers are present but the named role is not permitted
    to invoke the target endpoint, the request is rejected with ERR_UNAUTHORIZED
    (HTTP 403)."

    Design: Corner/rbac/sales_agent_cannot_create_spot_rate_unauthorized
    """
    res = api.create_spot_rate({"metal": "GOLD", "price_per_troy_oz_cents": 200_000}, SALES)
    validate_error(res, "ERR_UNAUTHORIZED")


def test_customer_cannot_deposit_other_customers_layaway(api):
    """PRD §2.1: "when a Customer applies a deposit to a layaway or cancels a
    layaway, the layaway's customer_id must equal the caller's X-User-ID; otherwise
    the request is rejected with ERR_NOT_RESOURCE_OWNER (HTTP 403)."

    Design: Corner/rbac/customer_cannot_deposit_other_customers_layaway_not_owner
    """
    ctx = setup_layaway(quantity=1, customer_name="Owner A")
    intruder = create_customer("Intruder B")
    lay = ctx["layaway"]

    res = api.deposit_layaway(
        lay["id"], {"amount_cents": 1000, "expected_layaway_version": lay["version"]},
        make_customer_headers(intruder["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER")


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request missing either header is rejected with
    ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    res = api.create_product(
        {"sku": "AU-NOAUTH", "product_type": "BULLION", "metal": "GOLD",
         "weight_troy_oz": 1.0, "purity": 1.0, "min_sell_spread_pct": 0.05,
         "buy_spread_pct": 0.04}, {})
    validate_error(res, "ERR_UNAUTHENTICATED")
