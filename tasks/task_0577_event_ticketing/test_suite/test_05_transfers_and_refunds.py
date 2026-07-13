"""Ticket transfers (scan gating, recipient authorization), refund progression, store
credit conservation, refund OCC, and refund/hold terminal-state rejections."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId, NON_EXISTENT_UUID, TEST_USERS,
    create_transfer_payload, create_refund_request_payload,
    make_buyer_headers,
    register_buyer, setup_paid_order,
)

BOX = TEST_USERS["box_office_headers"]
GATE = TEST_USERS["gate_scanner_headers"]


def _order_version(api, order_id, headers):
    return validate_success(api.get_order(order_id, headers), 200)["version"]


# ─── Difficulty: transfer gated by ticket scan_status ─────────────────────
def test_transfer_create_on_scanned_ticket_rejected(api):
    """PRD §3.5: "A ticket is transferable only while it is `VALID` and `UNSCANNED`: an
    attempt to transfer a `REFUNDED` or `VOID` ticket is rejected with
    `ERR_TICKET_NOT_TRANSFERABLE`, and an attempt to transfer one already `SCANNED` with
    `ERR_TICKET_ALREADY_SCANNED`."

    Design: Difficulty/cross_entity_state_dependency/transfer_gated_by_ticket_scan_status
    """
    p = setup_paid_order(num_seats=1, delivery_method="MOBILE")  # ticket auto-DELIVERED
    ticket_id = p["tickets"][0]["id"]
    validate_success(api.scan_ticket(ticket_id, GATE), 200)  # now SCANNED (event ONSALE)
    recipient = register_buyer()

    res = api.create_transfer(
        create_transfer_payload(ticket_id, recipient["id"], kind="GIFT"),
        make_buyer_headers(p["buyer"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_TICKET_ALREADY_SCANNED.value, expected_status=409)


def test_transfer_create_on_unscanned_ticket_succeeds(api):
    """PRD §3.5: "A ticket is transferable only while it is `VALID` and `UNSCANNED`: an
    attempt to transfer a `REFUNDED` or `VOID` ticket is rejected with
    `ERR_TICKET_NOT_TRANSFERABLE`, and an attempt to transfer one already `SCANNED` with
    `ERR_TICKET_ALREADY_SCANNED`." PRD §3.5: "A new transfer starts `INITIATED`."

    Design: Difficulty/cross_entity_state_dependency/transfer_gated_by_ticket_scan_status
    """
    p = setup_paid_order(num_seats=1, delivery_method="MOBILE")  # UNSCANNED at issuance
    ticket_id = p["tickets"][0]["id"]
    recipient = register_buyer()

    transfer = validate_success(
        api.create_transfer(
            create_transfer_payload(ticket_id, recipient["id"], kind="GIFT"),
            make_buyer_headers(p["buyer"]["id"]),
        ),
        201,
    )
    assert transfer["status"] == "INITIATED"


# ─── Corner: transfer recipient authorization + not-found ─────────────────
def test_transfer_accept_by_non_recipient_cannot(api):
    """PRD §3.5: "Only the buyer named as `to_buyer_id` may accept or decline it." PRD §2.1:
    "Accepting or declining a transfer instead compares the transfer's `to_buyer_id` to
    `X-User-ID`."

    Design: Corner/state_machines/transfer_accept_by_non_recipient_cannot
    """
    p = setup_paid_order(num_seats=1, delivery_method="MOBILE")
    recipient = register_buyer()
    outsider = register_buyer()
    transfer = validate_success(
        api.create_transfer(
            create_transfer_payload(p["tickets"][0]["id"], recipient["id"], kind="GIFT"),
            make_buyer_headers(p["buyer"]["id"]),
        ),
        201,
    )
    res = api.accept_transfer(transfer["id"], make_buyer_headers(outsider["id"]))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)


def test_transfer_accept_nonexistent_returns_transfer_not_found(api):
    """PRD §2.9: "an unresolved transfer yields `ERR_TRANSFER_NOT_FOUND`; and an unresolved
    refund yields `ERR_REFUND_NOT_FOUND`."

    Design: Corner/errors/transfer_accept_nonexistent_returns_transfer_not_found
    """
    buyer = register_buyer()
    res = api.accept_transfer(NON_EXISTENT_UUID, make_buyer_headers(buyer["id"]))
    validate_error(res, ApiErrorId.ERR_TRANSFER_NOT_FOUND.value, expected_status=404)


# ─── Corner: partial then full refund progression ─────────────────────────
def test_refund_partial_then_full_order_status_progression(api):
    """PRD §3.6: "The order's `refunded_amount_cents` is the sum of `amount_cents` over its
    `COMPLETED` refund requests; once that total reaches or exceeds the order's
    `face_total_cents` the order becomes `REFUNDED`, and otherwise it becomes
    `PARTIALLY_REFUNDED`."

    Design: Corner/calculations/refund_partial_then_full_order_status_progression
    """
    p = setup_paid_order(num_seats=2, delivery_method="MOBILE")
    o = p["order"]["id"]
    hb = make_buyer_headers(p["buyer"]["id"])
    t1, t2 = p["tickets"][0]["id"], p["tickets"][1]["id"]

    ov1 = _order_version(api, o, hb)
    rr1 = validate_success(
        api.create_refund_request(
            o, create_refund_request_payload("CUSTOMER_REQUEST", "ORIGINAL", ov1, ticket_ids=[t1]), hb
        ),
        201,
    )
    validate_success(api.approve_refund_request(rr1["id"], BOX), 200)
    after_first = validate_success(api.get_order(o, hb), 200)
    assert after_first["status"] == "PARTIALLY_REFUNDED"
    assert after_first["refunded_amount_cents"] == 9990

    ov2 = _order_version(api, o, hb)
    rr2 = validate_success(
        api.create_refund_request(
            o, create_refund_request_payload("CUSTOMER_REQUEST", "ORIGINAL", ov2, ticket_ids=[t2]), hb
        ),
        201,
    )
    validate_success(api.approve_refund_request(rr2["id"], BOX), 200)
    after_second = validate_success(api.get_order(o, hb), 200)
    assert after_second["status"] == "REFUNDED"
    assert after_second["refunded_amount_cents"] == 19980


# ─── Difficulty: money conservation on CREDIT refund ──────────────────────
def test_credit_refund_raises_balance_by_exactly_amount(api):
    """PRD §3.6: "When the destination is `CREDIT`, the refund's `amount_cents` is added to
    the buyer's `credit_balance_cents`". PRD §3.6: "The request's `amount_cents` is computed
    as the sum of the `face_value_cents` of the included tickets".

    Design: Difficulty/compensating_invariant/money_conservation_credit_refund_equals_amount
    """
    p = setup_paid_order(num_seats=1, delivery_method="MOBILE")  # ticket face 9990
    o = p["order"]["id"]
    hb = make_buyer_headers(p["buyer"]["id"])
    ov = _order_version(api, o, hb)

    rr = validate_success(
        api.create_refund_request(
            o, create_refund_request_payload("CUSTOMER_REQUEST", "CREDIT", ov), hb
        ),
        201,
    )
    assert rr["amount_cents"] == 9990
    validate_success(api.approve_refund_request(rr["id"], BOX), 200)

    buyer = validate_success(api.get_buyer(p["buyer"]["id"], hb), 200)
    assert buyer["credit_balance_cents"] == 9990


def test_original_refund_does_not_move_credit_balance(api):
    """PRD §3.6: for store credit "a credit refund raises it by precisely the refund amount
    and nothing else ever does" — an ORIGINAL-destination refund leaves credit_balance_cents
    at 0 even as it drives the order to REFUNDED.

    Design: Difficulty/compensating_invariant/money_conservation_credit_refund_equals_amount
    """
    p = setup_paid_order(num_seats=1, delivery_method="MOBILE")
    o = p["order"]["id"]
    hb = make_buyer_headers(p["buyer"]["id"])
    ov = _order_version(api, o, hb)

    rr = validate_success(
        api.create_refund_request(
            o, create_refund_request_payload("CUSTOMER_REQUEST", "ORIGINAL", ov), hb
        ),
        201,
    )
    validate_success(api.approve_refund_request(rr["id"], BOX), 200)

    order = validate_success(api.get_order(o, hb), 200)
    assert order["status"] == "REFUNDED"
    buyer = validate_success(api.get_buyer(p["buyer"]["id"], hb), 200)
    assert buyer["credit_balance_cents"] == 0


# ─── Corner: refund OCC + terminal-state rejections ───────────────────────
def test_refund_create_stale_order_version_returns_412(api):
    """PRD §2.7: "A request that creates a refund against an order must carry
    `expected_order_version`, a non-optional field whose value is the `version` of the target
    `Order` as the client last observed it." PRD §2.7: "If it does not match the order's
    current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/refund_create_stale_order_version_returns_412
    """
    p = setup_paid_order(num_seats=2, delivery_method="MOBILE")
    o = p["order"]["id"]
    hb = make_buyer_headers(p["buyer"]["id"])
    t1, t2 = p["tickets"][0]["id"], p["tickets"][1]["id"]
    ov = _order_version(api, o, hb)

    validate_success(
        api.create_refund_request(
            o, create_refund_request_payload("CUSTOMER_REQUEST", "ORIGINAL", ov, ticket_ids=[t1]), hb
        ),
        201,
    )  # advances Order.version
    res = api.create_refund_request(
        o, create_refund_request_payload("CUSTOMER_REQUEST", "ORIGINAL", ov, ticket_ids=[t2]), hb
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)


def test_refund_reject_then_approve_returns_invalid_state(api):
    """PRD §3.6: "Rejection moves it from `REQUESTED` to `REJECTED` and makes no inventory or
    ledger change." PRD §2.9: "(5) that the target resource is in a state from which the
    requested transition is legal, failing with `ERR_INVALID_STATE`".

    Design: Corner/state_machines/refund_reject_then_approve_returns_invalid_state
    """
    p = setup_paid_order(num_seats=1, delivery_method="MOBILE")
    o = p["order"]["id"]
    hb = make_buyer_headers(p["buyer"]["id"])
    ov = _order_version(api, o, hb)

    rr = validate_success(
        api.create_refund_request(
            o, create_refund_request_payload("CUSTOMER_REQUEST", "ORIGINAL", ov), hb
        ),
        201,
    )
    validate_success(api.reject_refund_request(rr["id"], BOX), 200)
    res = api.approve_refund_request(rr["id"], BOX)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_release_converted_hold_returns_invalid_state(api):
    """PRD §3.3: "release is available to the owning buyer or the box office and is legal only
    while no paid order references the hold." PRD §2.9: "(5) that the target resource is in a
    state from which the requested transition is legal, failing with `ERR_INVALID_STATE`".

    Design: Corner/state_machines/hold_release_when_converted_returns_invalid_state
    """
    p = setup_paid_order(num_seats=1, delivery_method="MOBILE")  # hold is CONVERTED
    res = api.release_hold(p["hold"]["id"], make_buyer_headers(p["buyer"]["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
