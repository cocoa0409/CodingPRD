"""Block assembly, routing, fill recording, and their guard ordering (PRD §3.5, §3.6)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    approve_order,
    attach_order,
    create_account,
    create_block,
    create_broker,
    create_order,
    create_security,
    get_block,
    get_order,
    record_fill,
    route_block,
    setup_routed_block,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["desk_admin_headers"]
TRADER = TEST_USERS["trader_headers"]
EXEC = TEST_USERS["execution_desk_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def test_block_create_initial_state(api, trader_headers):
    """PRD §3.5: "Aggregation starts when a `Trader` creates a block for a `security_id` and a `side`: the block lands `OPEN` with `total_qty`, `filled_qty`, and `allocated_through_seq` all zero, its allocation dimension `allocation_status` starting at `UNALLOCATED`, and a `BLOCK_CREATED` event."

    Design: Corner/state_machines/block_initial_state
    """
    security = create_security()
    block = validate_success(
        api.create_block({"security_id": security["id"], "side": "BUY"}, trader_headers), 201
    )
    assert block["status"] == "OPEN"
    assert block["allocation_status"] == "UNALLOCATED"
    assert block["total_qty"] == 0
    assert block["filled_qty"] == 0
    assert block["allocated_through_seq"] == 0


def test_block_cancel_returns_member_orders_to_approved(api):
    """PRD §3.5: "Cancelling a block requires it to be `OPEN` (`ERR_BLOCK_NOT_OPEN` from any other state) with `filled_qty` still zero: every member order returns `BLOCKED → APPROVED` with its `block_id` cleared, the block moves to the terminal `CANCELLED`, its `version` increments, and `BLOCK_CANCELLED` is written."

    Design: Corner/state_machines/block_cancel_cascades_detach
    """
    account = create_account()
    security = create_security()
    order1 = create_order(account["id"], security["id"], order_qty=100)
    approve_order(order1["id"])
    order2 = create_order(account["id"], security["id"], order_qty=200)
    approve_order(order2["id"])
    block = create_block(security["id"])
    attach_order(block["id"], order1["id"])
    attach_order(block["id"], order2["id"])

    cancelled = validate_success(api.cancel_block(block["id"], TRADER))
    assert cancelled["status"] == "CANCELLED"

    after1 = get_order(order1["id"])
    after2 = get_order(order2["id"])
    assert after1["status"] == "APPROVED" and after1["block_id"] is None, (
        f"Member order must return to APPROVED with block_id cleared, got {after1['status']}/{after1['block_id']!r}"
    )
    assert after2["status"] == "APPROVED" and after2["block_id"] is None


def test_block_membership_state_errors(api):
    """PRD §3.5: "Attaching is guarded, and the guards fire in order: the block must be `OPEN` (`ERR_BLOCK_NOT_OPEN`); the order named by `order_id` must not already sit in a block (`ERR_ORDER_ALREADY_BLOCKED`); the order must be `APPROVED` (`ERR_ORDER_NOT_APPROVED`); its security must match the block's (`ERR_BLOCK_SECURITY_MISMATCH`); and its side must match (`ERR_BLOCK_SIDE_MISMATCH`)."
    PRD §3.5: "Detaching mirrors it: again the block must be `OPEN` (`ERR_BLOCK_NOT_OPEN`), evaluated before the membership check, and the order's `block_id` must actually point at this block (`ERR_ORDER_NOT_IN_BLOCK`)."
    PRD §2.8: "Within attach and detach, the block's state is evaluated before the order's membership or ownership, which is evaluated before the order's own state."

    Design: Corner/validations/block_membership_state_errors
    """
    account = create_account()
    security = create_security()
    broker = create_broker(supported_asset_classes=["EQUITY"])

    order_approved = create_order(account["id"], security["id"], order_qty=100)
    approve_order(order_approved["id"])
    order_pending = create_order(account["id"], security["id"], order_qty=50)
    order_foreign = create_order(account["id"], security["id"], order_qty=25)
    approve_order(order_foreign["id"])

    block_a = create_block(security["id"])
    attach_order(block_a["id"], order_approved["id"])
    block_b = create_block(security["id"])
    attach_order(block_b["id"], order_foreign["id"])
    route_block(block_b["id"], broker["id"])

    res1 = api.attach_order_to_block(block_a["id"], {"order_id": order_pending["id"]}, TRADER)
    validate_error(res1, ApiErrorId.ERR_ORDER_NOT_APPROVED)

    res2 = api.attach_order_to_block(block_b["id"], {"order_id": order_approved["id"]}, TRADER)
    validate_error(res2, ApiErrorId.ERR_BLOCK_NOT_OPEN)

    res3 = api.detach_order_from_block(block_a["id"], order_foreign["id"], TRADER)
    validate_error(res3, ApiErrorId.ERR_ORDER_NOT_IN_BLOCK)


class TestRouteRequiresBrokerActive:
    def test_route_rejected_while_broker_suspended(self, api):
        """PRD §3.6: "The broker must exist (`ERR_BROKER_NOT_FOUND`), be ACTIVE (`ERR_BROKER_SUSPENDED`), and count the block security's asset class among its `supported_asset_classes` (`ERR_BROKER_ASSET_CLASS_UNSUPPORTED`); the security itself must be ACTIVE (`ERR_SECURITY_HALTED`)."
        PRD §3.1: "Suspending a broker blocks new block routing with `ERR_BROKER_SUSPENDED` — but, pinned deliberately, blocks already `WORKING` under that broker may continue to receive fills."

        Design: Difficulty/cross_entity_state_dependency/block_route_requires_broker_active
        """
        account = create_account()
        security = create_security()
        broker = create_broker(supported_asset_classes=["EQUITY"])
        validate_success(api.set_broker_status(broker["id"], {"to_status": "SUSPENDED"}, ADMIN))
        order = create_order(account["id"], security["id"], order_qty=100)
        approve_order(order["id"])
        block = create_block(security["id"])
        attach_order(block["id"], order["id"])

        res = api.route_block(block["id"], {"broker_id": broker["id"]}, TRADER)
        validate_error(res, ApiErrorId.ERR_BROKER_SUSPENDED)
        assert get_block(block["id"])["status"] == "OPEN", (
            "Rejected route must leave the block OPEN"
        )

    def test_route_succeeds_after_broker_resumed(self, api):
        """PRD §3.6: "Routing stamps the block's `broker_id` and `routed_at` — the latter read from the logical clock — moves the block `OPEN → WORKING`, increments its `version`, and writes `BLOCK_ROUTED`."

        Design: Difficulty/cross_entity_state_dependency/block_route_requires_broker_active
        """
        account = create_account()
        security = create_security()
        broker = create_broker(supported_asset_classes=["EQUITY"])
        validate_success(api.set_broker_status(broker["id"], {"to_status": "SUSPENDED"}, ADMIN))
        order = create_order(account["id"], security["id"], order_qty=100)
        approve_order(order["id"])
        block = create_block(security["id"])
        attach_order(block["id"], order["id"])
        validate_error(
            api.route_block(block["id"], {"broker_id": broker["id"]}, TRADER),
            ApiErrorId.ERR_BROKER_SUSPENDED,
        )

        validate_success(api.set_broker_status(broker["id"], {"to_status": "ACTIVE"}, ADMIN))
        routed = validate_success(api.route_block(block["id"], {"broker_id": broker["id"]}, TRADER))
        assert routed["status"] == "WORKING"
        assert routed["broker_id"] == broker["id"]


def test_route_to_broker_without_asset_class_rejected(api):
    """PRD §3.6: "The broker must exist (`ERR_BROKER_NOT_FOUND`), be ACTIVE (`ERR_BROKER_SUSPENDED`), and count the block security's asset class among its `supported_asset_classes` (`ERR_BROKER_ASSET_CLASS_UNSUPPORTED`); the security itself must be ACTIVE (`ERR_SECURITY_HALTED`)."

    Design: Corner/validations/broker_asset_class_unsupported_rejected
    """
    account = create_account()
    security = create_security(asset_class="EQUITY")
    broker = create_broker(broker_code="BRKFI", supported_asset_classes=["FIXED_INCOME"])
    order = create_order(account["id"], security["id"], order_qty=100)
    approve_order(order["id"])
    block = create_block(security["id"])
    attach_order(block["id"], order["id"])

    res = api.route_block(block["id"], {"broker_id": broker["id"]}, TRADER)
    validate_error(res, ApiErrorId.ERR_BROKER_ASSET_CLASS_UNSUPPORTED)
    assert get_block(block["id"])["status"] == "OPEN"


def test_overfill_rejected(api):
    """PRD §3.6: "The timestamp must not precede the block's `routed_at` (`ERR_FILL_BEFORE_ROUTE`), the security must still be ACTIVE at recording (`ERR_SECURITY_HALTED`), and the fill must not push the block's cumulative `filled_qty` above its `total_qty` (`ERR_OVERFILL` — a fill that lands exactly on `total_qty` is accepted and completes the block)."

    Design: Corner/validations/overfill_rejected
    """
    scenario = setup_routed_block(order_qtys=(100,))
    block_id = scenario["block"]["id"]
    record_fill(block_id, 60, 1000)
    assert get_block(block_id)["status"] == "PARTIALLY_FILLED"

    # 60 + 41 = 101 pushes cumulative filled_qty above total_qty 100.
    res = api.record_fill(
        block_id,
        {"fill_qty": 41, "fill_price_cents": 1000, "executed_at": "2026-08-01T09:05:00Z"},
        EXEC,
    )
    validate_error(res, ApiErrorId.ERR_OVERFILL)
    assert get_block(block_id)["filled_qty"] == 60, (
        "A rejected overfill must leave filled_qty unchanged"
    )

    # A fill that lands exactly on total_qty is accepted and completes the block.
    record_fill(block_id, 40, 1000, executed_at="2026-08-01T09:10:00Z")
    assert get_block(block_id)["status"] == "FILLED"
    assert get_block(block_id)["filled_qty"] == 100


def test_fill_before_route_timestamp_rejected(api):
    """PRD §3.6: "The timestamp must not precede the block's `routed_at` (`ERR_FILL_BEFORE_ROUTE`), the security must still be ACTIVE at recording (`ERR_SECURITY_HALTED`), and the fill must not push the block's cumulative `filled_qty` above its `total_qty` (`ERR_OVERFILL` — a fill that lands exactly on `total_qty` is accepted and completes the block)."
    PRD §2.5: "Its startup default, before any administrator sets it, is exactly 2026-08-01T00:00:00Z."

    Design: Corner/validations/fill_before_route_temporal_rejected
    """
    scenario = setup_routed_block(order_qtys=(100,))
    block_id = scenario["block"]["id"]

    res = api.record_fill(
        block_id,
        {"fill_qty": 10, "fill_price_cents": 1000, "executed_at": "2026-07-31T23:00:00Z"},
        EXEC,
    )
    validate_error(res, ApiErrorId.ERR_FILL_BEFORE_ROUTE)
    assert get_block(block_id)["filled_qty"] == 0


class TestFillRecordSafetyBeatsTemporal:
    def test_halted_security_error_wins_over_fill_before_route(self, api):
        """PRD §2.8: "When a single request violates several rules, the system does not choose arbitrarily: checks are evaluated in a fixed priority order and the first failure wins."
        PRD §2.8: "8. Business safety gates on related entities, evaluated in this order: the account must be ACTIVE where the action requires it (`ERR_ACCOUNT_SUSPENDED`, HTTP 409), and an order may not originate on an ERROR-type account (`ERR_ACCOUNT_TYPE_FORBIDDEN`, HTTP 422); then the security must be ACTIVE where the action executes or approves (`ERR_SECURITY_HALTED`, HTTP 409); then the broker must be ACTIVE at routing (`ERR_BROKER_SUSPENDED`, HTTP 409) and must support the instrument's asset class (`ERR_BROKER_ASSET_CLASS_UNSUPPORTED`, HTTP 422); then restriction rules, with an applicable PROHIBITED rule (`ERR_TRADE_PROHIBITED`) surfacing before any MAX_POSITION_UNITS breach (`ERR_POSITION_LIMIT_BREACH`)."
        PRD §2.8: "10. Temporal rules (HTTP 422): a fill's execution timestamp must not precede the block's routing timestamp (`ERR_FILL_BEFORE_ROUTE`)."

        Design: Difficulty/priority_pair_validation_conflict/fill_record_safety_beats_temporal
        """
        scenario = setup_routed_block(order_qtys=(100,))
        block_id = scenario["block"]["id"]
        security_id = scenario["security"]["id"]
        validate_success(api.set_security_status(security_id, {"to_status": "HALTED"}, ADMIN))

        # executed_at precedes routed_at (2026-08-01T00:00:00Z) AND the security is HALTED.
        res = api.record_fill(
            block_id,
            {"fill_qty": 10, "fill_price_cents": 1000, "executed_at": "2026-07-31T23:00:00Z"},
            EXEC,
        )
        validate_error(res, ApiErrorId.ERR_SECURITY_HALTED)

    def test_rejected_fill_persists_nothing(self, api):
        """PRD §3.6: "A block's fills are listed ordered by `fill_seq` ascending — the single exception to the default list ordering of §2.3."
        PRD §2.8: "8. Business safety gates on related entities, evaluated in this order: the account must be ACTIVE where the action requires it (`ERR_ACCOUNT_SUSPENDED`, HTTP 409), and an order may not originate on an ERROR-type account (`ERR_ACCOUNT_TYPE_FORBIDDEN`, HTTP 422); then the security must be ACTIVE where the action executes or approves (`ERR_SECURITY_HALTED`, HTTP 409); then the broker must be ACTIVE at routing (`ERR_BROKER_SUSPENDED`, HTTP 409) and must support the instrument's asset class (`ERR_BROKER_ASSET_CLASS_UNSUPPORTED`, HTTP 422); then restriction rules, with an applicable PROHIBITED rule (`ERR_TRADE_PROHIBITED`) surfacing before any MAX_POSITION_UNITS breach (`ERR_POSITION_LIMIT_BREACH`)."

        Design: Difficulty/priority_pair_validation_conflict/fill_record_safety_beats_temporal
        """
        scenario = setup_routed_block(order_qtys=(100,))
        block_id = scenario["block"]["id"]
        security_id = scenario["security"]["id"]
        validate_success(api.set_security_status(security_id, {"to_status": "HALTED"}, ADMIN))

        validate_error(
            api.record_fill(
                block_id,
                {"fill_qty": 10, "fill_price_cents": 1000, "executed_at": "2026-07-31T23:00:00Z"},
                EXEC,
            ),
            ApiErrorId.ERR_SECURITY_HALTED,
        )

        assert get_block(block_id)["filled_qty"] == 0, "Rejected fill must not move filled_qty"
        data, meta = validate_paginated(api.list_block_fills(block_id, TRADER))
        assert meta["total_count"] == 0, "Rejected fill must not persist a Fill row"


def test_compliance_officer_cannot_record_fill(api, compliance_officer_headers):
    """PRD §2.1: "A recognized role that is not on the endpoint's authorized list is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: "| POST | `/trading/blocks/{blockId}/fills` | Record an execution fill against a WORKING or PARTIALLY_FILLED block | ExecutionDesk |"

    Design: Corner/rbac/compliance_officer_cannot_record_fill
    """
    scenario = setup_routed_block(order_qtys=(100,))
    block_id = scenario["block"]["id"]

    res = api.record_fill(
        block_id,
        {"fill_qty": 10, "fill_price_cents": 1000, "executed_at": "2026-08-01T09:00:00Z"},
        compliance_officer_headers,
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)
    assert get_block(block_id)["filled_qty"] == 0
