"""Order lifecycle: two independent dimensions (payment × fulfillment),
state transitions, and the fulfill mint (PRD §3.3)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    make_guest_headers, TEST_USERS,
    create_park_payload, create_pricing_policy_payload, create_guest_payload,
    create_order_payload,
)

PM = TEST_USERS["park_manager_headers"]


def _park(**ov):
    return get_success_data(api_client.create_park(create_park_payload(**ov), PM))


def _policy(park_id, **ov):
    return get_success_data(api_client.create_pricing_policy(
        create_pricing_policy_payload(park_id, **ov), PM))


def _guest(**ov):
    return get_success_data(api_client.create_guest(create_guest_payload(**ov), TEST_USERS["guest_headers"]))


def _order(park_id, guest_id, **ov):
    return get_success_data(api_client.create_order(
        create_order_payload(park_id, guest_id, **ov), make_guest_headers(guest_id)))


# ───────────────── Queue A: non_linear_state_machine ─────────────────

def test_order_pay_advances_payment_only_fulfillment_unchanged(api):
    """PRD §3.3: "Paying an order advances payment_status from PENDING to PAID."
    PRD §3.3: "An order tracks two completely independent dimensions of progress.
    The payment dimension, payment_status, begins at PENDING. The fulfillment
    dimension, fulfillment_status, begins at UNFULFILLED."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_fulfillment_dimensions
    """
    park = _park()
    _policy(park["id"], product_type="DAY_TICKET", base_price_cents=4000)
    guest = _guest(zip_code="33333", height_cm=150)
    order = _order(park["id"], guest["id"], product_type="DAY_TICKET", party_size=2)
    gh = make_guest_headers(guest["id"])
    paid = get_success_data(api_client.pay_order(order["id"], gh))
    assert paid["payment_status"] == "PAID"
    assert paid["fulfillment_status"] == "UNFULFILLED", \
        "fulfillment must stay UNFULFILLED after pay"


def test_order_fulfill_advances_fulfillment_only_payment_stays_paid(api):
    """PRD §3.3: "Fulfilling an order is the fulfillment-dimension transition: it
    moves fulfillment_status from UNFULFILLED to FULFILLED and is allowed only once
    payment_status is PAID and fulfillment_status is still UNFULFILLED."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_fulfillment_dimensions
    """
    park = _park()
    _policy(park["id"], product_type="DAY_TICKET", base_price_cents=4000)
    guest = _guest(zip_code="33333")
    order = _order(park["id"], guest["id"], product_type="DAY_TICKET", party_size=2)
    gh = make_guest_headers(guest["id"])
    get_success_data(api_client.pay_order(order["id"], gh))
    fulfilled = get_success_data(api_client.fulfill_order(order["id"], gh))
    assert fulfilled["fulfillment_status"] == "FULFILLED"
    assert fulfilled["payment_status"] == "PAID", "payment must remain PAID after fulfill"


# ───────────────── Queue B: state_machines ─────────────────

def test_order_initial_state_pending_unfulfilled(api):
    """PRD §3.3: "The payment dimension, payment_status, begins at PENDING. The
    fulfillment dimension, fulfillment_status, begins at UNFULFILLED."

    Design: Corner/state_machines/order_initial_state_pending_unfulfilled
    """
    park = _park()
    guest = _guest()
    order = _order(park["id"], guest["id"], product_type="DAY_TICKET", party_size=1)
    assert order["payment_status"] == "PENDING"
    assert order["fulfillment_status"] == "UNFULFILLED"


def test_fulfill_unpaid_order_rejected(api):
    """PRD §3.3: "An attempt to fulfill an order that is not yet paid is rejected
    with ERR_ORDER_NOT_PAID."

    Design: Corner/state_machines/fulfill_unpaid_order_returns_order_not_paid
    """
    park = _park()
    _policy(park["id"], product_type="DAY_TICKET", base_price_cents=5000)
    guest = _guest()
    order = _order(park["id"], guest["id"], product_type="DAY_TICKET", party_size=1)
    res = api_client.fulfill_order(order["id"], make_guest_headers(guest["id"]))
    validate_error(res, "ERR_ORDER_NOT_PAID")


def test_cancel_paid_order_rejected_invalid_state(api):
    """PRD §3.3: "Cancelling an order is available only while payment_status is
    PENDING; it advances payment to the terminal VOID"
    PRD §3.1: "A transition requested from a state in which it is not defined is
    rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/cancel_paid_order_returns_invalid_state
    """
    park = _park()
    _policy(park["id"], product_type="DAY_TICKET", base_price_cents=5000)
    guest = _guest()
    order = _order(park["id"], guest["id"], product_type="DAY_TICKET", party_size=1)
    gh = make_guest_headers(guest["id"])
    get_success_data(api_client.pay_order(order["id"], gh))
    res = api_client.cancel_order(order["id"], gh)
    validate_error(res, "ERR_INVALID_STATE")


def test_pay_already_paid_order_rejected_invalid_state(api):
    """PRD §3.3: "Paying an order advances payment_status from PENDING to PAID. This
    is permitted only while the order is PENDING"
    PRD §3.1: "A transition requested from a state in which it is not defined is
    rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/pay_already_paid_order_idempotency_rejected
    """
    park = _park()
    _policy(park["id"], product_type="DAY_TICKET", base_price_cents=5000)
    guest = _guest()
    order = _order(park["id"], guest["id"], product_type="DAY_TICKET", party_size=1)
    gh = make_guest_headers(guest["id"])
    get_success_data(api_client.pay_order(order["id"], gh))
    res = api_client.pay_order(order["id"], gh)
    validate_error(res, "ERR_INVALID_STATE")


def test_terminal_void_order_cannot_be_paid(api):
    """PRD §3.3: "Cancelling an order is available only while payment_status is
    PENDING; it advances payment to the terminal VOID"
    PRD §3.3: "Paying an order advances payment_status from PENDING to PAID. This is
    permitted only while the order is PENDING"

    Design: Corner/state_machines/terminal_void_order_cannot_pay
    """
    park = _park()
    _policy(park["id"], product_type="DAY_TICKET", base_price_cents=5000)
    guest = _guest()
    order = _order(park["id"], guest["id"], product_type="DAY_TICKET", party_size=1)
    gh = make_guest_headers(guest["id"])
    get_success_data(api_client.cancel_order(order["id"], gh))
    res = api_client.pay_order(order["id"], gh)
    validate_error(res, "ERR_INVALID_STATE")


# ───────────────── Queue B: endpoints ─────────────────

def test_fulfill_mints_party_size_admissions(api):
    """PRD §3.3: "Fulfillment mints party_size admission rows, each created in
    ISSUED status with a ticket_price_cents equal to the order's subtotal_cents
    divided by party_size"

    Design: Corner/endpoints/fulfill_mints_party_size_admissions
    """
    park = _park()
    _policy(park["id"], product_type="DAY_TICKET", base_price_cents=5000, group_threshold=99)
    guest = _guest()
    gh = make_guest_headers(guest["id"])
    order = _order(park["id"], guest["id"], product_type="DAY_TICKET", party_size=3)
    get_success_data(api_client.pay_order(order["id"], gh))
    get_success_data(api_client.fulfill_order(order["id"], gh))
    # subtotal = 5000 * 3 = 15000; each ticket_price_cents = 15000 / 3 = 5000.
    admissions = get_success_data(api_client.list_order_admissions(order["id"], gh))
    assert len(admissions) == 3, f"expected 3 admissions, got {len(admissions)}"
    for adm in admissions:
        assert adm["status"] == "ISSUED"
        assert adm["ticket_price_cents"] == 5000, \
            f"expected 5000, got {adm['ticket_price_cents']}"
