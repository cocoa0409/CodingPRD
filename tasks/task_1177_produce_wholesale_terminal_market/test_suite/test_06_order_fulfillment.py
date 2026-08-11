"""Order confirm gates, pick/deliver unit conversion, and cancel rules (PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_lot_unit_conservation,
    create_customer,
    create_pending_order,
    confirm_order,
    get_customer,
    get_lot,
    get_order,
    patch_customer,
    setup_accepted_lot,
    validate_error,
    validate_success,
)
from test_helpers import ADMIN_HEADERS, RECEIVER_HEADERS, SALES_HEADERS


def _setup_pending_order(customer_limit=1000000, line_quantity=1,
                         line_unit_price=10.00):
    base = setup_accepted_lot(defect_pct=0)
    customer = create_customer(credit_limit_cents=customer_limit)
    order = create_pending_order(customer["id"], base["lot"]["id"],
                                 quantity=line_quantity, unit_price=line_unit_price)
    base["customer"] = customer
    base["order"] = order
    return base


# --- Confirm gated on the owning customer's status (cross-entity) -------------

def _suspend_customer(base):
    fresh = get_customer(base["customer"]["id"])
    patch_customer(fresh["id"], fresh["version"], status="SUSPENDED")


def test_confirm_with_suspended_customer_returns_customer_inactive(api):
    """PRD §3.6: "The preconditions, all enforced at confirm time, are: the customer's
    `status` must be `ACTIVE` (otherwise `ERR_CUSTOMER_INACTIVE`)"

    Design: Difficulty/cross_entity_state_dependency/confirm_requires_customer_active
    """
    base = _setup_pending_order()
    _suspend_customer(base)
    resp = api.confirm_order(base["order"]["id"], SALES_HEADERS)
    validate_error(resp, ApiErrorId.ERR_CUSTOMER_INACTIVE)
    assert get_order(base["order"]["id"])["status"] == "PENDING"


def test_rejected_confirm_leaves_order_pending_without_reservation(api):
    """PRD §3.6: "On success, each line reserves its quantity on the lot
    (`reserved_units` increases by the line quantity, `available_units` recomputes)"
    — a confirm rejected by the customer-active gate is not a success, so no
    reservation may be written.
    PRD §3.6: "The preconditions, all enforced at confirm time, are: the customer's
    `status` must be `ACTIVE` (otherwise `ERR_CUSTOMER_INACTIVE`)"

    Design: Difficulty/cross_entity_state_dependency/confirm_requires_customer_active
    """
    base = _setup_pending_order()
    _suspend_customer(base)
    resp = api.confirm_order(base["order"]["id"], SALES_HEADERS)
    validate_error(resp, ApiErrorId.ERR_CUSTOMER_INACTIVE)
    lot = get_lot(base["lot"]["id"])
    assert lot["reserved_units"] == 0
    assert lot["available_units"] == 100
    assert get_customer(base["customer"]["id"])["status"] == "SUSPENDED"


# --- Priority pair: state legality beats the money gate -----------------------

def _setup_cancelled_over_limit_order():
    """Customer with a 1000-cent limit; order (1 @ 100.00, subtotal 10000) created
    PENDING and then cancelled by SalesDesk — both the state gate and the credit
    gate would fail a confirm."""
    base = setup_accepted_lot(defect_pct=0)
    customer = create_customer(credit_limit_cents=1000)
    order = create_pending_order(customer["id"], base["lot"]["id"],
                                 quantity=1, unit_price=100.00)
    cancelled = validate_success(api_client.cancel_order(order["id"], SALES_HEADERS),
                                 200)
    assert cancelled["status"] == "CANCELLED"
    base["customer"] = customer
    base["order"] = cancelled
    return base


def test_confirm_cancelled_order_returns_invalid_state_not_credit_error(api):
    """PRD §2.8: "the target entity's own state legality (`ERR_INVALID_STATE`,
    including the specialized `ERR_INVOICE_EXISTS` and `ERR_INSPECTION_OPEN` variants
    where they apply); cross-entity state gates such as customer active status and lot
    acceptance (`ERR_CUSTOMER_INACTIVE`, `ERR_LOT_NOT_ACCEPTED`)"
    PRD §2.8: "and finally money gates (`ERR_CREDIT_LIMIT_EXCEEDED`,
    `ERR_OVERPAYMENT`), which always run last."

    Design: Difficulty/priority_pair_validation_conflict/confirm_cancelled_order_state_beats_credit_limit
    """
    base = _setup_cancelled_over_limit_order()
    resp = api.confirm_order(base["order"]["id"], SALES_HEADERS)
    # Both failures hold simultaneously (CANCELLED state; 0 + 10000 > 1000 limit);
    # the state gate outranks the money gate.
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_rejected_confirm_on_cancelled_order_writes_no_reservation(api):
    """PRD §3.6: "Cancelling a `DELIVERED` or later order is `ERR_INVALID_STATE`."
    (a fortiori, confirm from `CANCELLED` is not a legal transition and must not
    mutate anything)
    PRD §2.8: "and finally money gates (`ERR_CREDIT_LIMIT_EXCEEDED`,
    `ERR_OVERPAYMENT`), which always run last."

    Design: Difficulty/priority_pair_validation_conflict/confirm_cancelled_order_state_beats_credit_limit
    """
    base = _setup_cancelled_over_limit_order()
    resp = api.confirm_order(base["order"]["id"], SALES_HEADERS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    order = get_order(base["order"]["id"])
    assert order["status"] == "CANCELLED"
    lot = get_lot(base["lot"]["id"])
    assert lot["reserved_units"] == 0
    assert get_customer(base["customer"]["id"])["credit_exposure_cents"] == 0


# --- Breadth: terminal cancel, deliver conversion, clean fiscal gate ----------

def test_cancel_delivered_order_returns_invalid_state(api):
    """PRD §3.6: "Cancelling a `DELIVERED` or later order is `ERR_INVALID_STATE`."
    PRD §3.6: "on delivery each line's quantity is moved out of `reserved_units` and
    into `sold_units` on the lot, `available_units` recomputes, and the customer's
    `credit_exposure_cents` is recomputed."

    Design: Corner/state_machines/cancel_delivered_order_returns_invalid_state
    """
    base = setup_accepted_lot(defect_pct=0)
    customer = create_customer(credit_limit_cents=1000000)
    order = create_pending_order(customer["id"], base["lot"]["id"],
                                 quantity=1, unit_price=10.00)
    confirm_order(order["id"])
    validate_success(api_client.pick_order(order["id"], RECEIVER_HEADERS), 200)
    validate_success(api_client.deliver_order(order["id"], RECEIVER_HEADERS), 200)

    resp = api.cancel_order(order["id"], SALES_HEADERS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    lot = get_lot(base["lot"]["id"])
    assert lot["sold_units"] == 1, "no compensation fires on a rejected cancel"
    assert lot["reserved_units"] == 0


def test_deliver_converts_reserved_units_to_sold(api):
    """PRD §3.6: "Delivering, also a `Receiver` action, applies the same cold-chain
    gate and moves the order to `DELIVERED`; on delivery each line's quantity is moved
    out of `reserved_units` and into `sold_units` on the lot, `available_units`
    recomputes, and the customer's `credit_exposure_cents` is recomputed."

    Design: Corner/endpoints/deliver_converts_reserved_units_to_sold
    """
    base = setup_accepted_lot(defect_pct=0)
    customer = create_customer(credit_limit_cents=1000000)
    order = create_pending_order(customer["id"], base["lot"]["id"],
                                 quantity=10, unit_price=10.00)
    confirm_order(order["id"])
    mid = get_lot(base["lot"]["id"])
    assert mid["reserved_units"] == 10 and mid["sold_units"] == 0
    assert mid["available_units"] == 90
    validate_success(api_client.pick_order(order["id"], RECEIVER_HEADERS), 200)

    delivered = validate_success(api_client.deliver_order(order["id"],
                                                          RECEIVER_HEADERS), 200)
    assert delivered["status"] == "DELIVERED"
    lot = get_lot(base["lot"]["id"])
    assert lot["reserved_units"] == 0, "reservation converted, not released"
    assert lot["sold_units"] == 10
    assert lot["available_units"] == 90
    assert_lot_unit_conservation(lot)


def test_confirm_over_credit_limit_returns_credit_limit_exceeded(api):
    """PRD §3.6: "the customer's `credit_exposure_cents` plus this order's
    `subtotal_cents` must be less than or equal to `credit_limit_cents` — equality is
    allowed, and strictly-greater overshoot is rejected as
    `ERR_CREDIT_LIMIT_EXCEEDED`"

    Design: Corner/errors/confirm_over_credit_limit_returns_credit_limit_exceeded
    """
    base = setup_accepted_lot(defect_pct=0)
    customer = create_customer(credit_limit_cents=1000)
    order = create_pending_order(customer["id"], base["lot"]["id"],
                                 quantity=1, unit_price=100.00)
    assert order["subtotal_cents"] == 10000
    resp = api.confirm_order(order["id"], SALES_HEADERS)
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)  # 0 + 10000 > 1000
    assert get_order(order["id"])["status"] == "PENDING"
    assert get_lot(base["lot"]["id"])["reserved_units"] == 0
