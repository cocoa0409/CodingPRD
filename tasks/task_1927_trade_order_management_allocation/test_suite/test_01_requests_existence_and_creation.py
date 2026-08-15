"""Request shape, resource existence, and creation-default claims (PRD §2.8, §2.9, §3.1, §3.4, §3.6)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_account,
    assert_fill,
    create_account_payload,
    create_order_payload,
    create_security_payload,
    get_success_data,
    setup_routed_block,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["desk_admin_headers"]
TRADER = TEST_USERS["trader_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_account_create_applies_defaults(api, desk_admin_headers):
    """PRD §3.1: "New accounts start ACTIVE, and creation writes an `ACCOUNT_CREATED` audit event."
    PRD §2.4: "Every persisted resource carries a server-minted `id`, a UUID with no type prefix, and a `created_at` timestamp rendered as ISO 8601 UTC with three fractional digits."
    PRD §4: "Status codes follow one convention throughout: creating a new resource returns 201 — this covers accounts, securities, brokers, commission budgets, restrictions, orders, blocks, fills, allocation plans, and flagging a trade error, which creates the error record — while state-changing actions on an existing resource, single-resource retrievals, and listings return 200."

    Design: Corner/entities/account_create_applies_defaults
    """
    res = api.create_account(
        create_account_payload(account_code="A1", display_name="A1", custodian_name="CUSTO"),
        desk_admin_headers,
    )
    account = validate_success(res, 201)
    assert_account(account)
    assert account["status"] == "ACTIVE", f"New account must start ACTIVE, got {account['status']}"
    assert account["account_code"] == "A1"
    assert account["display_name"] == "A1"
    assert account["account_type"] == "DISCRETIONARY"
    assert account["custodian_name"] == "CUSTO"


def test_order_create_missing_required_side_returns_invalid_request(api, trader_headers, desk_admin_headers):
    """PRD §3.4: "A `Trader` creates an order with an `account_id`, a `security_id`, a `side` of BUY or SELL, a strictly positive `order_qty` that must be a whole multiple of the security's `lot_size` (otherwise `ERR_LOT_SIZE_VIOLATION`), and an `order_type` of MARKET or LIMIT."
    PRD §2.8: "Request shape — required fields present, enum values valid, integers positive where required, and conditional field requirements honored: a LIMIT order carries `limit_price_cents` while a MARKET order must not; a MAX_POSITION_UNITS restriction carries `threshold_units` while a PROHIBITED one must not; a WRONG_ACCOUNT correction carries `target_account_id`, a WRONG_QTY correction carries `corrected_qty`, and a WRONG_PRICE correction carries `corrected_price_cents`."
    PRD §3.4: "Orders are listed with optional `account_id`, `security_id`, `block_id`, and `status` filters, and fetched individually by id; each order also exposes its computed `allocated_qty` and `avg_executed_price_cents` once allocation begins (§3.7)."

    Design: Corner/entities/order_create_missing_required_returns_invalid_request
    """
    account = validate_success(api.create_account(create_account_payload(), desk_admin_headers), 201)
    security = validate_success(api.create_security(create_security_payload(), desk_admin_headers), 201)

    payload = create_order_payload(account["id"], security["id"])
    del payload["side"]
    res = api.create_order(payload, trader_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    data, meta = validate_paginated(api.list_orders(TRADER, params={"account_id": account["id"]}))
    assert meta["total_count"] == 0, f"Rejected create must persist nothing, got total_count={meta['total_count']}"


def test_order_create_limit_missing_price_returns_invalid_request(api, trader_headers, desk_admin_headers):
    """PRD §3.4: "The `limit_price_cents` field is required exactly for LIMIT orders — strictly positive when present, and forbidden on MARKET orders."
    PRD §2.8: "All of this surfaces as `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/order_create_limit_missing_price_returns_invalid_request
    """
    account = validate_success(api.create_account(create_account_payload(), desk_admin_headers), 201)
    security = validate_success(api.create_security(create_security_payload(), desk_admin_headers), 201)

    payload = create_order_payload(account["id"], security["id"], order_type="LIMIT")
    res = api.create_order(payload, trader_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_order_create_computed_field_input_ignored(api, trader_headers, desk_admin_headers):
    """PRD §2.8: "Unknown or undeclared request fields are ignored, not rejected."
    PRD §3.4: "Creation runs no compliance evaluation at all: the order lands in `PENDING_COMPLIANCE` with `allocated_qty` zero, writes `ORDER_CREATED`, and waits."

    Design: Corner/entities/order_create_computed_field_input_ignored
    """
    account = validate_success(api.create_account(create_account_payload(), desk_admin_headers), 201)
    security = validate_success(api.create_security(create_security_payload(), desk_admin_headers), 201)

    payload = create_order_payload(account["id"], security["id"], allocated_qty=999)
    order = validate_success(api.create_order(payload, trader_headers), 201)
    assert order["status"] == "PENDING_COMPLIANCE"
    assert order["allocated_qty"] == 0, (
        f"Client-supplied computed field must be ignored; expected allocated_qty 0, got {order['allocated_qty']}"
    )


def test_order_lot_size_violation_rejected(api, trader_headers, desk_admin_headers):
    """PRD §3.4: "A `Trader` creates an order with an `account_id`, a `security_id`, a `side` of BUY or SELL, a strictly positive `order_qty` that must be a whole multiple of the security's `lot_size` (otherwise `ERR_LOT_SIZE_VIOLATION`), and an `order_type` of MARKET or LIMIT."

    Design: Corner/entities/order_lot_size_type_constraint_rejected
    """
    account = validate_success(api.create_account(create_account_payload(), desk_admin_headers), 201)
    security = validate_success(
        api.create_security(create_security_payload(lot_size=2), desk_admin_headers), 201
    )

    res = api.create_order(
        create_order_payload(account["id"], security["id"], order_qty=7), trader_headers
    )
    validate_error(res, ApiErrorId.ERR_LOT_SIZE_VIOLATION)

    data, meta = validate_paginated(api.list_orders(TRADER, params={"account_id": account["id"]}))
    assert meta["total_count"] == 0, f"Rejected create must persist nothing, got total_count={meta['total_count']}"


def test_fill_immutable_event_shape(api):
    """PRD §3.6: "Each accepted fill receives a per-block monotone `fill_seq` starting at 1, the authoritative chronological ordering key since broker timestamps may tie or wander, and its computed `gross_amount_cents` is the fill quantity multiplied by the fill price."
    PRD §3.6: "A fill is immutable: it carries `id` and `created_at` only, with no `updated_at` and no `version` (§2.4)."

    Design: Corner/entities/fill_immutable_event_shape
    """
    scenario = setup_routed_block(order_qtys=(100,))
    block_id = scenario["block"]["id"]

    fill = validate_success(
        api.record_fill(
            block_id,
            {"fill_qty": 40, "fill_price_cents": 1000, "executed_at": "2026-08-01T09:00:00Z"},
            TEST_USERS["execution_desk_headers"],
        ),
        201,
    )
    assert_fill(fill)
    assert fill["fill_seq"] == 1, f"First fill of a block must have fill_seq 1, got {fill['fill_seq']}"
    assert fill["gross_amount_cents"] == 40 * 1000, (
        f"gross_amount_cents must be fill_qty * fill_price_cents, got {fill['gross_amount_cents']}"
    )


def test_order_create_body_account_fk_integrity_rejected(api, trader_headers, desk_admin_headers):
    """PRD §2.9: "Resource ids in a URL resolve from left to right: the leftmost path parameter is looked up first, and only if it exists is the next one examined; ids referenced in the request body are resolved after all path ids."
    PRD §2.9: "A missing resource yields the 404 specific to its kind — `ERR_ACCOUNT_NOT_FOUND`, `ERR_SECURITY_NOT_FOUND`, `ERR_BROKER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_BLOCK_NOT_FOUND`, `ERR_BUDGET_NOT_FOUND`, `ERR_RESTRICTION_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, `ERR_TRADE_ERROR_NOT_FOUND`, `ERR_INSTRUCTION_NOT_FOUND`, or `ERR_POSITION_NOT_FOUND`."

    Design: Corner/entities/order_create_body_fk_integrity_rejected
    """
    security = validate_success(api.create_security(create_security_payload(), desk_admin_headers), 201)

    res = api.create_order(
        create_order_payload(NON_EXISTENT_UUID, security["id"]), trader_headers
    )
    validate_error(res, ApiErrorId.ERR_ACCOUNT_NOT_FOUND)


@pytest.mark.parametrize(
    "path,error_id",
    [
        ("/trading/accounts", ApiErrorId.ERR_ACCOUNT_NOT_FOUND),
        ("/trading/securities", ApiErrorId.ERR_SECURITY_NOT_FOUND),
        ("/trading/brokers", ApiErrorId.ERR_BROKER_NOT_FOUND),
        ("/trading/orders", ApiErrorId.ERR_ORDER_NOT_FOUND),
        ("/trading/blocks", ApiErrorId.ERR_BLOCK_NOT_FOUND),
        ("/trading/commission-budgets", ApiErrorId.ERR_BUDGET_NOT_FOUND),
        ("/trading/restrictions", ApiErrorId.ERR_RESTRICTION_NOT_FOUND),
        ("/trading/allocation-plans", ApiErrorId.ERR_PLAN_NOT_FOUND),
        ("/trading/allocations", ApiErrorId.ERR_ALLOCATION_NOT_FOUND),
        ("/trading/trade-errors", ApiErrorId.ERR_TRADE_ERROR_NOT_FOUND),
        ("/trading/settlement-instructions", ApiErrorId.ERR_INSTRUCTION_NOT_FOUND),
        ("/trading/positions", ApiErrorId.ERR_POSITION_NOT_FOUND),
    ],
)
def test_get_by_id_with_unknown_id_returns_entity_specific_404(api, path, error_id, auditor_headers):
    """PRD §2.9: "A missing resource yields the 404 specific to its kind — `ERR_ACCOUNT_NOT_FOUND`, `ERR_SECURITY_NOT_FOUND`, `ERR_BROKER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_BLOCK_NOT_FOUND`, `ERR_BUDGET_NOT_FOUND`, `ERR_RESTRICTION_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, `ERR_TRADE_ERROR_NOT_FOUND`, `ERR_INSTRUCTION_NOT_FOUND`, or `ERR_POSITION_NOT_FOUND`."

    Design: Corner/validations/not_found_sweep_returns_404_per_entity
    """
    res = api.get(f"{path}/{NON_EXISTENT_UUID}", headers=auditor_headers)
    validate_error(res, error_id)


def test_account_suspended_order_create_rejected(api, trader_headers, desk_admin_headers):
    """PRD §3.4: "The owning account must be ACTIVE (`ERR_ACCOUNT_SUSPENDED`) and must not be an ERROR-type account (`ERR_ACCOUNT_TYPE_FORBIDDEN`)."
    PRD §3.1: "An administrator flips an account between ACTIVE and SUSPENDED by submitting `to_status`."

    Design: Corner/validations/account_suspended_order_create_rejected
    """
    account = validate_success(api.create_account(create_account_payload(), desk_admin_headers), 201)
    validate_success(
        api.set_account_status(account["id"], {"to_status": "SUSPENDED"}, desk_admin_headers)
    )
    security = validate_success(api.create_security(create_security_payload(), desk_admin_headers), 201)

    res = api.create_order(create_order_payload(account["id"], security["id"]), trader_headers)
    validate_error(res, ApiErrorId.ERR_ACCOUNT_SUSPENDED)

    data, meta = validate_paginated(api.list_orders(TRADER, params={"account_id": account["id"]}))
    assert meta["total_count"] == 0, f"Rejected create must persist nothing, got total_count={meta['total_count']}"


def test_error_type_account_cannot_originate_order(api, trader_headers, desk_admin_headers):
    """PRD §3.1: "The ERROR type is special: such accounts exist to absorb residual quantities from trade-error corrections (§3.8), and they may not originate orders — attempting to create an order on one is rejected with `ERR_ACCOUNT_TYPE_FORBIDDEN`."

    Design: Corner/validations/error_account_origin_forbidden
    """
    error_account = validate_success(
        api.create_account(
            create_account_payload(account_code="ERR", display_name="Desk Error", account_type="ERROR"),
            desk_admin_headers,
        ),
        201,
    )
    security = validate_success(api.create_security(create_security_payload(), desk_admin_headers), 201)

    res = api.create_order(create_order_payload(error_account["id"], security["id"]), trader_headers)
    validate_error(res, ApiErrorId.ERR_ACCOUNT_TYPE_FORBIDDEN)
