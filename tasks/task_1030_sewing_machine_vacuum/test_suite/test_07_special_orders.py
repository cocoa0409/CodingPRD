"""Special orders: OCC-guarded amendment, balance recomputation, version bumps,
and lifecycle guards.
"""
from test_helpers import TEST_USERS, setup_special_order, validate_error, validate_success

SA = TEST_USERS["sales_associate_headers"]


def test_amend_with_current_version_recomputes_balance_and_bumps_version(api):
    """PRD §3.8: "A `SalesAssociate` may amend a still-open order's `quantity` and/or
    `deposit_cents`; the amendment recomputes `balance_due_cents` by the same formula
    and bumps the order's `version`."

    Design: Corner/endpoints/special_order_amend_occ_success
    """
    _cust, _prod, order = setup_special_order(quantity=2, unit_price_cents=80000, deposit_cents=20000)
    amended = validate_success(
        api.amend_special_order(
            order["id"], {"quantity": 5, "expected_special_order_version": order["version"]}, SA
        ),
        200,
    )
    assert amended["quantity"] == 5
    assert amended["balance_due_cents"] == 380000
    assert amended["version"] == 2


def test_amend_with_stale_version_rejected(api):
    """PRD §2.8: "If they do not match — because a prior amendment or a state
    transition (receive, fulfill, cancel) has advanced the version since the client
    last read the order — the amendment is rejected with `ERR_STALE_VERSION` (HTTP
    412), and the client must re-read the order before amending again."

    Design: Corner/endpoints/special_order_amend_stale_version_conflict
    """
    _cust, _prod, order = setup_special_order(quantity=2, unit_price_cents=80000, deposit_cents=20000)
    v0 = order["version"]
    validate_success(
        api.amend_special_order(
            order["id"], {"quantity": 3, "expected_special_order_version": v0}, SA
        ),
        200,
    )  # version now advanced past v0
    res = api.amend_special_order(
        order["id"], {"quantity": 9, "expected_special_order_version": v0}, SA
    )
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


def test_fulfill_requested_order_invalid_state(api):
    """PRD §3.8: "A `SalesAssociate` fulfills a `RECEIVED` order (else
    `ERR_INVALID_STATE`), moving it `RECEIVED → FULFILLED` and bumping the
    `version`."

    Design: Corner/state_machines/special_order_fulfill_from_requested_invalid
    """
    _cust, _prod, order = setup_special_order(quantity=2, unit_price_cents=80000, deposit_cents=20000)
    res = api.fulfill_special_order(order["id"], SA)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_receive_increments_version(api):
    """PRD §3.8: "A `SalesAssociate` marks a `REQUESTED` order received (else
    `ERR_INVALID_STATE`), moving it `REQUESTED → RECEIVED` and bumping the
    `version`."

    Design: Corner/cross_cutting/occ_version_increments_on_every_special_order_write
    """
    _cust, _prod, order = setup_special_order(quantity=1, unit_price_cents=80000, deposit_cents=10000)
    received = validate_success(api.receive_special_order(order["id"], SA), 200)
    assert received["status"] == "RECEIVED"
    assert received["version"] == 2
