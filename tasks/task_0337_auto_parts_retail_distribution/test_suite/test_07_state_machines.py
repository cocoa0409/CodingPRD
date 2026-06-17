"""State-machine preconditions and invalid transitions across orders, warranty
claims, reorder requests, parts, and delivery runs.

Queue B: state_machines.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data, api_client,
    create_price_tier, create_part, create_stocked_part, create_account, create_open_order,
    add_line, allocate, ship, invoice, current_version, create_reorder,
    setup_open_wholesale_order_with_line, setup_allocated_wholesale_order,
    setup_shipped_wholesale_order, setup_warranty_claim, setup_ordered_reorder,
    setup_allocated_hotshot_order,
    allocate_payload, ship_payload, receive_reorder_payload, create_warranty_claim_payload,
    create_order_line_payload,
    ApiErrorId, TEST_USERS,
)

REP = TEST_USERS["wholesale_rep_headers"]
INV = TEST_USERS["inventory_manager_headers"]
ADMIN = TEST_USERS["warranty_admin_headers"]


def _reorders_for_part(part_id):
    data, _ = validate_paginated(api_client.list_reorder_requests(REP, params={"part_id": part_id}))
    return data


# ─── sm_allocate_empty_order_rejected ────────────────────────────────────────

def test_allocate_empty_order_rejected(api):
    """PRD §3.4: "the order must have at least one line (otherwise ERR_EMPTY_ORDER)".

    Design: Corner/state_machines/sm_allocate_empty_order_rejected
    """
    tier = create_price_tier()
    acct = create_account(tier["id"], name="WS Shop", account_type="WHOLESALE")
    order = create_open_order(acct["id"], channel="WHOLESALE")
    v = current_version(order["id"])
    resp = api.allocate_order(order["id"], allocate_payload(v), REP)
    validate_error(resp, ApiErrorId.ERR_EMPTY_ORDER.value)


# ─── sm_allocate_insufficient_stock_rejected ─────────────────────────────────

def test_allocate_insufficient_stock_rejected(api):
    """PRD §3.4: "every non-special-order line must have a part whose available_qty
    is at least that line's qty (otherwise ERR_INSUFFICIENT_STOCK)".

    A line that is NOT special-order (its qty does not exceed available_qty at line
    creation, per PRD §3.3) can still fail allocation if available_qty later drops
    below its qty. Part available 2; two wholesale orders each add a non-special
    qty-2 line (available is still 2 at each line's creation). Allocating the first
    order reserves 2 (available -> 0); allocating the second is then rejected with
    ERR_INSUFFICIENT_STOCK because its non-special qty-2 line no longer has stock.

    Design: Corner/state_machines/sm_allocate_insufficient_stock_rejected
    """
    tier = create_price_tier()
    part = create_stocked_part(
        qty=2, description="Low stock", list_price_cents=4000, cost_cents=1500,
        stockable=True, reorder_point=0, reorder_qty=0)
    account = create_account(tier["id"], name="WS Shop", account_type="WHOLESALE")
    order_a = create_open_order(account["id"], channel="WHOLESALE")
    add_line(order_a["id"], part["id"], 2)  # available 2 >= 2 -> not special
    order_b = create_open_order(account["id"], channel="WHOLESALE")
    add_line(order_b["id"], part["id"], 2)  # available still 2 -> not special
    allocate(order_a["id"])                 # reserves 2 -> available 0
    v = current_version(order_b["id"])
    resp = api.allocate_order(order_b["id"], allocate_payload(v), REP)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK.value)


# ─── sm_ship_from_open_invalid_fulfillment_state ─────────────────────────────

def test_ship_open_order_rejected_no_inventory_move(api):
    """PRD §3.4: "The transition requires that the order currently be ALLOCATED
    (otherwise ERR_INVALID_FULFILLMENT_STATE)".

    Shipping an OPEN (un-allocated) order is rejected and on_hand is untouched.

    Design: Corner/state_machines/sm_ship_from_open_invalid_fulfillment_state
    """
    part, account, order, line = setup_open_wholesale_order_with_line(
        qty=1, stock_qty=5,
        part_overrides=dict(description="Open part", list_price_cents=4000, cost_cents=1500,
                            stockable=True, reorder_point=0, reorder_qty=0))
    v = current_version(order["id"])
    resp = api.ship_order(order["id"], ship_payload(v), REP)
    validate_error(resp, ApiErrorId.ERR_INVALID_FULFILLMENT_STATE.value)
    final = get_success_data(api_client.get_part(part["id"], INV))
    assert final["on_hand_qty"] == 5, "rejected ship must not move inventory"


# ─── sm_pay_before_invoice_rejected ──────────────────────────────────────────

def test_pay_before_invoice_rejected(api):
    """PRD §3.5: "Payment requires the order's settlement_status to be INVOICED
    (otherwise ERR_NOT_INVOICED)".

    Paying a shipped-but-UNBILLED order is rejected.

    Design: Corner/state_machines/sm_pay_before_invoice_rejected
    """
    part, account, order, line = setup_shipped_wholesale_order(
        qty=1, stock_qty=5,
        part_overrides=dict(description="Pay part", list_price_cents=4000, cost_cents=1500,
                            stockable=True, reorder_point=0, reorder_qty=0))
    resp = api.pay_order(order["id"], REP)
    validate_error(resp, ApiErrorId.ERR_NOT_INVOICED.value)


# ─── sm_warranty_approve_from_submitted_rejected ─────────────────────────────

def test_warranty_approve_from_submitted_rejected(api):
    """PRD §3.7: "approving a claim moves it from UNDER_REVIEW to APPROVED, and is
    permitted only when the claim is UNDER_REVIEW (otherwise ERR_CLAIM_NOT_UNDER_REVIEW)".

    Approving a SUBMITTED claim (skipping start-review) is rejected.

    Design: Corner/state_machines/sm_warranty_approve_from_submitted_rejected
    """
    part, account, order, line, claim = setup_warranty_claim(
        resolution="REFUND", qty=1, line_qty=1, warranty_days=365, escalate=False, invoiced=False)
    resp = api.approve_claim(claim["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_UNDER_REVIEW.value)


# ─── sm_warranty_approve_expired_window_rejected ─────────────────────────────

def test_warranty_approve_expired_window_rejected(api):
    """PRD §3.7: "only within the warranty window - the claim's created_at must be no
    later than the referenced line's ship time plus the part's warranty_days days
    (otherwise ERR_WARRANTY_EXPIRED)".

    A part with warranty_days 0 is already expired at ship; approving its UNDER_REVIEW
    claim is rejected.

    Design: Corner/state_machines/sm_warranty_approve_expired_window_rejected
    """
    part, account, order, line, claim = setup_warranty_claim(
        resolution="REFUND", qty=1, line_qty=1, warranty_days=0, escalate=True, invoiced=False)
    resp = api.approve_claim(claim["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_WARRANTY_EXPIRED.value)


# ─── sm_warranty_deny_from_under_review_terminal ─────────────────────────────

def test_warranty_deny_from_under_review(api):
    """PRD §3.7: "denial moves the claim to DENIED and is permitted whenever the claim
    is in SUBMITTED or UNDER_REVIEW (otherwise ERR_CLAIM_NOT_OPEN); a denied claim
    issues no credit and performs no restock."

    Denying an UNDER_REVIEW claim moves it to DENIED with zero credit and no A/R change.

    Design: Corner/state_machines/sm_warranty_deny_from_under_review_terminal
    """
    part, account, order, line, claim = setup_warranty_claim(
        resolution="REFUND", qty=1, line_qty=1, warranty_days=365, escalate=True, invoiced=False)
    denied = get_success_data(api_client.deny_claim(claim["id"], ADMIN))
    assert denied["status"] == "DENIED"
    assert denied["credit_cents"] == 0
    acct = get_success_data(api_client.get_account(account["id"], REP))
    assert acct["ar_balance_cents"] == 0, "denial issues no credit"


# ─── sm_reorder_receive_overshoot_rejected ───────────────────────────────────

def test_reorder_receive_overshoot_rejected(api):
    """PRD §3.8: "A receipt is valid only when receive_qty is at least one and the
    running total of qty_received plus the new receive_qty does not exceed qty_ordered;
    an invalid receive quantity is rejected with ERR_INVALID_RECEIVE_QTY".

    Receiving 11 against a qty_ordered-10 reorder is rejected; no stock added.

    Design: Corner/state_machines/sm_reorder_receive_overshoot_rejected
    """
    part, ro = setup_ordered_reorder(reorder_qty=10, reorder_point=2)
    resp = api.receive_reorder_request(ro["id"], receive_reorder_payload(11), INV)
    validate_error(resp, ApiErrorId.ERR_INVALID_RECEIVE_QTY.value)
    final = get_success_data(api_client.get_part(part["id"], INV))
    assert final["on_hand_qty"] == 0, "rejected receive must not add stock"


# ─── sm_part_discontinue_with_reservations_rejected ──────────────────────────

def test_discontinue_part_with_reservations_rejected(api):
    """PRD §3.1: "when it has no live reservations, meaning its reserved_qty is
    exactly zero (otherwise ERR_PART_HAS_RESERVATIONS)".

    A part reserved by an allocated order cannot be discontinued.

    Design: Corner/state_machines/sm_part_discontinue_with_reservations_rejected
    """
    part, account, order, line = setup_allocated_wholesale_order(
        qty=1, stock_qty=5,
        part_overrides=dict(description="Reserved part", list_price_cents=4000, cost_cents=1500,
                            stockable=True, reorder_point=0, reorder_qty=0))
    resp = api.discontinue_part(part["id"], INV)
    validate_error(resp, ApiErrorId.ERR_PART_HAS_RESERVATIONS.value)


# ─── sm_part_discontinue_cancels_open_reorders_cascade ───────────────────────

def test_discontinue_part_cancels_open_reorders(api):
    """PRD §3.1: "every reorder request for that part that is currently SUGGESTED or
    ORDERED is moved to CANCELLED as part of the same operation, and then the part's
    status becomes DISCONTINUED."

    Design: Corner/state_machines/sm_part_discontinue_cancels_open_reorders_cascade
    """
    part = create_part(description="Disc reorder", list_price_cents=4000, cost_cents=1500,
                       stockable=True, reorder_point=2, reorder_qty=4)
    ro = create_reorder(part["id"])
    discontinued = get_success_data(api_client.discontinue_part(part["id"], INV))
    assert discontinued["status"] == "DISCONTINUED"
    ro_after = get_success_data(api_client.get_reorder_request(ro["id"], INV))
    assert ro_after["status"] == "CANCELLED", "open SUGGESTED reorder must cascade to CANCELLED"


# ─── sm_delivery_run_complete_from_scheduled_rejected ────────────────────────

def test_complete_scheduled_run_rejected(api):
    """PRD §3.9: "Completing a run advances it from DISPATCHED to DELIVERED, and
    requires the run to be DISPATCHED (otherwise ERR_RUN_NOT_DISPATCHED)".

    Completing a SCHEDULED (not dispatched) run is rejected.

    Design: Corner/state_machines/sm_delivery_run_complete_from_scheduled_rejected
    """
    part, account, order, line = setup_allocated_hotshot_order(qty=1, special=True)
    from test_helpers import create_driver, create_bay, schedule_run
    driver = create_driver(name="Drv", turnaround_min=0)
    bay = create_bay()
    run = schedule_run(order["id"], driver["id"], bay["id"], 10, 50)
    resp = api.complete_delivery_run(run["id"], REP)
    validate_error(resp, ApiErrorId.ERR_RUN_NOT_DISPATCHED.value)


# ─── sm_special_order_ship_blocked_when_not_received ─────────────────────────

def test_ship_blocked_special_order_not_received(api):
    """PRD §3.4: "that no special-order line still sits PENDING without received stock
    to fulfill it (otherwise ERR_SPECIAL_ORDER_NOT_READY)".

    An allocated order whose non-stockable special-order line has no received stock
    cannot ship.

    Design: Corner/state_machines/sm_special_order_ship_blocked_when_not_received
    """
    part, account, order, line = setup_allocated_hotshot_order(qty=1, special=True)
    v = current_version(order["id"])
    resp = api.ship_order(order["id"], ship_payload(v), REP)
    validate_error(resp, ApiErrorId.ERR_SPECIAL_ORDER_NOT_READY.value)
