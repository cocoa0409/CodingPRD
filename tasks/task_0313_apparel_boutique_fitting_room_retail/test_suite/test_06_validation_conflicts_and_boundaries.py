"""Validation precedence pairs, boundary-exact checks, and cross-entity state gates.

Queue A (Difficulty): priority_pair_validation_conflict (return state>temporal,
capture inventory>credit), boundary_precision_check (return-window inclusive day,
zero-availability hold), cross_entity_state_dependency (return requires order completed).
Queue B (Corner): validations (insufficient store credit).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, ApiErrorId,
    create_boutique, create_customer, create_style, create_variant,
    create_fitting_room, create_hold, open_order_with_line,
    create_completed_order, create_captured_order, file_refund_return,
    advance_clock,
)

ASSOCIATE = TEST_USERS["store_associate_headers"]
MANAGER = TEST_USERS["store_manager_headers"]


# ─── Queue A: priority_pair_validation_conflict ───────────────────────────

def test_return_state_check_beats_temporal_window(api):
    """PRD §3.7: "Approving a return (REQUESTED -> APPROVED) is a StoreAssociate action
    gated by an ordered sequence of checks, and the order is significant because state is
    checked before time. The return must still be REQUESTED; the underlying order's
    fulfillment_status must be COMPLETED, or approval is rejected with
    ERR_ORDER_NOT_RETURNABLE_STATE (HTTP 409); and only then is the window checked".

    An order left OPEN (never completed) AND past the would-be window returns
    ERR_ORDER_NOT_RETURNABLE_STATE — state outranks the temporal window check.

    Design: Difficulty/priority_pair_validation_conflict/return_state_beats_temporal_window
    """
    bq = create_boutique(tax_rate_bps=0, return_window_days=30)
    cu = create_customer(bq["id"])
    style = create_style(bq["id"], list_price_cents=5000, category="OUTERWEAR", season="WINTER")
    variant = create_variant(style["id"], size="M", color="Gray", on_hand=5)

    # Captured but NOT completed (fulfillment OPEN).
    captured, line = create_captured_order(cu["id"], variant["id"], qty=1)
    assert captured["fulfillment_status"] == "OPEN"

    advance_clock(bq["id"], 100)  # far past 30 days
    rr = file_refund_return(captured["id"], line["id"])

    res = api.approve_return(rr["id"], ASSOCIATE)
    validate_error(res, ApiErrorId.ERR_ORDER_NOT_RETURNABLE_STATE.value)


def test_return_state_check_fires_for_open_order_within_window(api):
    """PRD §3.7: "the order is significant because state is checked before time. The
    return must still be REQUESTED; the underlying order's fulfillment_status must be
    COMPLETED, or approval is rejected with ERR_ORDER_NOT_RETURNABLE_STATE (HTTP 409); and
    only then is the window checked".

    Even an order still OPEN but well within the would-be window (clock at 0) surfaces
    ERR_ORDER_NOT_RETURNABLE_STATE — the state gate precedes and pre-empts the temporal
    window check.

    Design: Difficulty/priority_pair_validation_conflict/return_state_beats_temporal_window
    """
    bq = create_boutique(tax_rate_bps=0, return_window_days=30)
    cu = create_customer(bq["id"])
    style = create_style(bq["id"], list_price_cents=5000, category="OUTERWEAR", season="WINTER")
    variant = create_variant(style["id"], size="M", color="Gray", on_hand=5)

    captured, line = create_captured_order(cu["id"], variant["id"], qty=1)
    assert captured["fulfillment_status"] == "OPEN"
    rr = file_refund_return(captured["id"], line["id"])  # clock still at 0, within window

    res = api.approve_return(rr["id"], ASSOCIATE)
    validate_error(res, ApiErrorId.ERR_ORDER_NOT_RETURNABLE_STATE.value)


def test_capture_inventory_check_beats_store_credit(api):
    """PRD §3.6: "First, inventory is re-checked: every order line's variant must have
    available at least that line's qty, or capture is rejected with
    ERR_INSUFFICIENT_INVENTORY (HTTP 409). Second, the optional redeem_store_credit
    amount the caller supplies must not exceed the customer's current store_credit_cents,
    or capture is rejected with ERR_INSUFFICIENT_STORE_CREDIT (HTTP 422); the inventory
    check is evaluated before the store-credit check."

    A capture where the sku is out of stock AND redeem_store_credit exceeds the (zero)
    wallet returns ERR_INSUFFICIENT_INVENTORY — inventory outranks the fiscal credit check.

    Design: Difficulty/priority_pair_validation_conflict/capture_inventory_beats_store_credit
    """
    bq = create_boutique(tax_rate_bps=0)
    cu = create_customer(bq["id"])
    style = create_style(bq["id"], list_price_cents=5000, category="ACCESSORIES", season="SPRING")
    variant = create_variant(style["id"], size="M", color="Brown", on_hand=1)

    # Order 1 authorized for the single unit.
    order1, _ = open_order_with_line(cu["id"], variant["id"], qty=1)
    get_success_data(api.authorize_order(order1["id"], ASSOCIATE))
    # Order 2 authorized for the same unit.
    order2, _ = open_order_with_line(cu["id"], variant["id"], qty=1)
    get_success_data(api.authorize_order(order2["id"], ASSOCIATE))
    # Capture order 1, consuming the only on_hand unit (available -> 0).
    get_success_data(api.capture_order(order1["id"], ASSOCIATE))

    # Capture order 2: out of stock AND redeem exceeds (zero) wallet.
    res = api.capture_order(order2["id"], ASSOCIATE, payload={"redeem_store_credit": 5000})
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_INVENTORY.value)


def test_capture_store_credit_check_reached_only_when_inventory_passes(api):
    """PRD §3.6: "First, inventory is re-checked: every order line's variant must have
    available at least that line's qty, or capture is rejected with
    ERR_INSUFFICIENT_INVENTORY (HTTP 409). Second, the optional redeem_store_credit amount
    the caller supplies must not exceed the customer's current store_credit_cents, or
    capture is rejected with ERR_INSUFFICIENT_STORE_CREDIT (HTTP 422); the inventory check
    is evaluated before the store-credit check."

    When inventory IS available, the inventory check passes and the second-in-line
    store-credit check is reached: an over-redemption surfaces ERR_INSUFFICIENT_STORE_CREDIT
    — proving the inventory check precedes (and gates) the fiscal check.

    Design: Difficulty/priority_pair_validation_conflict/capture_inventory_beats_store_credit
    """
    bq = create_boutique(tax_rate_bps=0)
    cu = create_customer(bq["id"])
    style = create_style(bq["id"], list_price_cents=5000, category="ACCESSORIES", season="SPRING")
    variant = create_variant(style["id"], size="M", color="Brown", on_hand=5)

    order, _ = open_order_with_line(cu["id"], variant["id"], qty=1)
    get_success_data(api.authorize_order(order["id"], ASSOCIATE))

    res = api.capture_order(order["id"], ASSOCIATE, payload={"redeem_store_credit": 5000})
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_STORE_CREDIT.value)


# ─── Queue A: boundary_precision_check ────────────────────────────────────

def test_return_window_inclusive_boundary_day_30_succeeds(api):
    """PRD §3.7: "only then is the window checked — the boutique's current_business_date
    minus the order's completion anchor must be at most the boutique's return_window_days,
    or approval is rejected with ERR_RETURN_WINDOW_CLOSED (HTTP 422)."

    With return_window_days=30 and completion at date 0, approving at date 30
    (delta == 30, the inclusive <= boundary) SUCCEEDS and grants the 5000 refund.

    Design: Difficulty/boundary_precision_check/return_window_inclusive_boundary_exact
    """
    bq = create_boutique(tax_rate_bps=0, return_window_days=30)
    cu = create_customer(bq["id"])
    style = create_style(bq["id"], list_price_cents=5000, category="OUTERWEAR", season="FALL")
    variant = create_variant(style["id"], size="M", color="Olive", on_hand=5)

    order, line = create_completed_order(cu["id"], variant["id"], qty=1)
    advance_clock(bq["id"], 30)
    rr = file_refund_return(order["id"], line["id"])

    approved = validate_success(api.approve_return(rr["id"], ASSOCIATE), 200)
    assert approved["status"] == "APPROVED"

    customer_after = get_success_data(api.get_customer(cu["id"], ASSOCIATE))
    assert customer_after["store_credit_cents"] == 5000


def test_return_window_one_day_past_boundary_rejected(api):
    """PRD §3.7: "only then is the window checked — the boutique's current_business_date
    minus the order's completion anchor must be at most the boutique's return_window_days,
    or approval is rejected with ERR_RETURN_WINDOW_CLOSED (HTTP 422)."

    With return_window_days=30 and completion at date 0, approving at date 31
    (delta 31 > 30) is rejected with ERR_RETURN_WINDOW_CLOSED — the exclusive far side of
    the inclusive boundary.

    Design: Difficulty/boundary_precision_check/return_window_inclusive_boundary_exact
    """
    bq = create_boutique(tax_rate_bps=0, return_window_days=30)
    cu = create_customer(bq["id"])
    style = create_style(bq["id"], list_price_cents=5000, category="OUTERWEAR", season="FALL")
    variant = create_variant(style["id"], size="M", color="Olive", on_hand=5)

    order, line = create_completed_order(cu["id"], variant["id"], qty=1)
    advance_clock(bq["id"], 31)
    rr = file_refund_return(order["id"], line["id"])

    res = api.approve_return(rr["id"], ASSOCIATE)
    validate_error(res, ApiErrorId.ERR_RETURN_WINDOW_CLOSED.value)


def test_hold_on_zero_availability_sku_rejected(api):
    """PRD §3.3: "the variant must be reservable: its available must be at least the one
    unit requested and its status must be STOCKED, otherwise the create is rejected with
    ERR_INSUFFICIENT_INVENTORY (HTTP 409)."

    A sku at available 0 (its single unit already held) rejects a second hold attempt with
    ERR_INSUFFICIENT_INVENTORY.

    Design: Difficulty/boundary_precision_check/hold_empty_availability_zero_unit_boundary
    """
    bq = create_boutique(tax_rate_bps=875)
    cu = create_customer(bq["id"])
    style = create_style(bq["id"], list_price_cents=5000, category="ACCESSORIES", season="SUMMER")
    variant = create_variant(style["id"], size="S", color="Gold", on_hand=1)
    room = create_fitting_room(bq["id"])

    create_hold(room["id"], cu["id"], variant["id"], start_minute=600, end_minute=660)

    res = api.create_hold(
        {"fitting_room_id": room["id"], "customer_id": cu["id"], "sku_variant_id": variant["id"],
         "start_minute": 700, "end_minute": 760}, ASSOCIATE)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_INVENTORY.value)

    variant_after = get_success_data(api.get_sku_variant(variant["id"], ASSOCIATE))
    assert variant_after["available"] == 0


def test_zero_availability_hold_rejection_error_id(api):
    """PRD §3.3: "its available must be at least the one unit requested and its status must
    be STOCKED, otherwise the create is rejected with ERR_INSUFFICIENT_INVENTORY (HTTP
    409)."

    Second hold on a sku whose only unit is reserved surfaces ERR_INSUFFICIENT_INVENTORY
    with HTTP 409 (the registered status for that error).

    Design: Difficulty/boundary_precision_check/hold_empty_availability_zero_unit_boundary
    """
    bq = create_boutique(tax_rate_bps=875)
    cu = create_customer(bq["id"])
    style = create_style(bq["id"], list_price_cents=5000, category="ACCESSORIES", season="SUMMER")
    variant = create_variant(style["id"], size="S", color="Gold", on_hand=1)
    room = create_fitting_room(bq["id"])
    create_hold(room["id"], cu["id"], variant["id"], start_minute=600, end_minute=660)

    res = api.create_hold(
        {"fitting_room_id": room["id"], "customer_id": cu["id"], "sku_variant_id": variant["id"],
         "start_minute": 900, "end_minute": 960}, ASSOCIATE)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_INVENTORY.value, expected_status=409)


# ─── Queue A: cross_entity_state_dependency (return <- order completed) ───

def test_return_approve_requires_order_completed(api):
    """PRD §3.7: "the underlying order's fulfillment_status must be COMPLETED, or approval
    is rejected with ERR_ORDER_NOT_RETURNABLE_STATE (HTTP 409)".

    A captured order left at fulfillment OPEN (never completed), within window, blocks
    return approval with ERR_ORDER_NOT_RETURNABLE_STATE.

    Design: Difficulty/cross_entity_state_dependency/return_approve_requires_order_completed
    """
    bq = create_boutique(tax_rate_bps=0, return_window_days=30)
    cu = create_customer(bq["id"])
    style = create_style(bq["id"], list_price_cents=5000, category="TOPS", season="FALL")
    variant = create_variant(style["id"], size="M", color="Cream", on_hand=5)

    captured, line = create_captured_order(cu["id"], variant["id"], qty=1)
    assert captured["fulfillment_status"] == "OPEN"
    rr = file_refund_return(captured["id"], line["id"])

    res = api.approve_return(rr["id"], ASSOCIATE)
    validate_error(res, ApiErrorId.ERR_ORDER_NOT_RETURNABLE_STATE.value)


def test_return_approve_succeeds_once_order_completed(api):
    """PRD §3.7: "the underlying order's fulfillment_status must be COMPLETED, or approval
    is rejected with ERR_ORDER_NOT_RETURNABLE_STATE (HTTP 409)".

    The same return that is blocked while the order is OPEN approves successfully once the
    order's fulfillment_status reaches COMPLETED — confirming the cross-entity gate keys on
    the parent SalesOrder state.

    Design: Difficulty/cross_entity_state_dependency/return_approve_requires_order_completed
    """
    bq = create_boutique(tax_rate_bps=0, return_window_days=30)
    cu = create_customer(bq["id"])
    style = create_style(bq["id"], list_price_cents=5000, category="TOPS", season="FALL")
    variant = create_variant(style["id"], size="M", color="Cream", on_hand=5)

    order, line = create_completed_order(cu["id"], variant["id"], qty=1)
    completed = get_success_data(api.get_sales_order(order["id"], ASSOCIATE))
    assert completed["fulfillment_status"] == "COMPLETED"

    rr = file_refund_return(order["id"], line["id"])
    approved = validate_success(api.approve_return(rr["id"], ASSOCIATE), 200)
    assert approved["status"] == "APPROVED"


# ─── Queue B: validations (insufficient store credit) ─────────────────────

def test_capture_redeem_exceeding_wallet_rejected(api):
    """PRD §3.6: "the optional redeem_store_credit amount the caller supplies must not
    exceed the customer's current store_credit_cents, or capture is rejected with
    ERR_INSUFFICIENT_STORE_CREDIT (HTTP 422)".

    Capturing with redeem_store_credit 9999 while the wallet holds 0 (inventory available)
    returns ERR_INSUFFICIENT_STORE_CREDIT.

    Design: Corner/validations/insufficient_store_credit_on_capture
    """
    bq = create_boutique(tax_rate_bps=0)
    cu = create_customer(bq["id"])
    style = create_style(bq["id"], list_price_cents=5000, category="TOPS", season="SPRING")
    variant = create_variant(style["id"], size="M", color="Blue", on_hand=5)

    order, _ = open_order_with_line(cu["id"], variant["id"], qty=1)
    get_success_data(api.authorize_order(order["id"], ASSOCIATE))

    res = api.capture_order(order["id"], ASSOCIATE, payload={"redeem_store_credit": 9999})
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_STORE_CREDIT.value)
