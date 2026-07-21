"""After-sale flows: exchange approval cascades, order-cancel cascade, hygiene and
temporal exchange guards, state-vs-temporal precedence, and replacement reminders.

Covers queue-A transitive_cascade, priority_pair_validation_conflict (exchange),
boundary_precision (exchange window), plus queue-B exchange/reminder instances.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    make_customer_headers,
    setup_fulfilled_line, setup_placed_order,
    request_exchange, get_reminder_for_line, set_clock,
)

SM = TEST_USERS["store_manager_headers"]


# ─── Exchange approval depth-3 cascade (queue A) ──────────────────────────
def test_exchange_approve_marks_line_exchanged(api):
    """PRD §3.5: "Approval, which moves the exchange to APPROVED, drives a chain of
    consequences. The OrderLine moves to EXCHANGED; because the line is exchanged, the
    SKU's stock_on_hand is increased by the line quantity and its reserved_count and
    available_units are recomputed".

    Design: Difficulty/transitive_cascade/exchange_approve_cascade_depth3
    """
    ctx = setup_fulfilled_line(base_price_cents=4000, initial_stock=1, quantity=1)
    exch = request_exchange(ctx, "SEALED")
    validate_success(api.approve_exchange(exch["id"], SM), 200)
    line = validate_success(api.get_order_line(ctx["line"]["id"], SM), 200)
    assert line["status"] == "EXCHANGED", line


def test_exchange_approve_restocks_and_flips_stock_status(api):
    """PRD §3.5: "because the line is exchanged, the SKU's stock_on_hand is increased
    by the line quantity ... and because available_units changes, the SKU's
    stock_status is recomputed, so a SKU that had been OUT_OF_STOCK rises to LOW_STOCK
    or IN_STOCK as its availability climbs back above zero."

    Design: Difficulty/transitive_cascade/exchange_approve_cascade_depth3
    """
    ctx = setup_fulfilled_line(base_price_cents=4000, initial_stock=1, quantity=1)
    before = validate_success(api.get_sku(ctx["sku"]["id"], SM), 200)
    assert before["stock_on_hand"] == 0 and before["stock_status"] == "OUT_OF_STOCK", before
    exch = request_exchange(ctx, "SEALED")
    validate_success(api.approve_exchange(exch["id"], SM), 200)
    sku = validate_success(api.get_sku(ctx["sku"]["id"], SM), 200)
    assert sku["stock_on_hand"] == 1, sku
    assert sku["stock_status"] == "LOW_STOCK", sku


# ─── Order-cancel depth-2 cascade (queue A) ───────────────────────────────
def test_order_cancel_marks_line_cancelled(api):
    """PRD §3.5: "Cancellation moves fulfillment_status to CANCELLED and cascades:
    every ACTIVE OrderLine moves to CANCELLED, and each cancelled line releases its
    reservation, so the affected SKUs have reserved_count recomputed downward and
    available_units and stock_status recomputed."

    Design: Difficulty/transitive_cascade/order_cancel_cascade_depth2
    """
    ctx = setup_placed_order(base_price_cents=3000, band_size=38, cup_size="D", initial_stock=5, quantity=2)
    validate_success(
        api.cancel_order(ctx["order"]["id"], make_customer_headers(ctx["customer"]["id"])), 200
    )
    line = validate_success(api.get_order_line(ctx["line"]["id"], SM), 200)
    assert line["status"] == "CANCELLED", line


def test_order_cancel_releases_reservation(api):
    """PRD §3.5: "each cancelled line releases its reservation, so the affected SKUs
    have reserved_count recomputed downward and available_units and stock_status
    recomputed."

    Design: Difficulty/transitive_cascade/order_cancel_cascade_depth2
    """
    ctx = setup_placed_order(base_price_cents=3000, band_size=38, cup_size="D", initial_stock=5, quantity=2)
    validate_success(
        api.cancel_order(ctx["order"]["id"], make_customer_headers(ctx["customer"]["id"])), 200
    )
    sku = validate_success(api.get_sku(ctx["sku"]["id"], SM), 200)
    assert sku["reserved_count"] == 0, sku
    assert sku["available_units"] == 5, sku


# ─── State check beats temporal window (queue A) ──────────────────────────
def _state_beats_temporal(api):
    ctx = setup_fulfilled_line(base_price_cents=4000, band_size=40, cup_size="E", initial_stock=1, quantity=1)
    exch1 = request_exchange(ctx, "SEALED")
    validate_success(api.approve_exchange(exch1["id"], SM), 200)  # line -> EXCHANGED (window still open)
    set_clock("2026-08-15T00:00:00Z")  # 45 days after fulfillment: window now expired too
    exch2 = request_exchange(ctx, "SEALED")
    return ctx, exch2


def test_exchange_state_error_precedes_window_error(api):
    """PRD §2.9: "Seventh is the state check ... reported through the state family ...
    ERR_LINE_NOT_EXCHANGEABLE_STATE ... Eleventh are temporal-window checks
    (ERR_EXCHANGE_WINDOW_EXPIRED, ERR_REMINDER_NOT_DUE)."
    PRD §2.9: "Where a lower-priority failure and a higher-priority failure coexist,
    the higher-priority error is the one returned."

    Design: Difficulty/priority_pair_validation_conflict/exchange_state_beats_temporal
    """
    _ctx, exch2 = _state_beats_temporal(api)
    res = api.approve_exchange(exch2["id"], SM)
    validate_error(res, ApiErrorId.ERR_LINE_NOT_EXCHANGEABLE_STATE)


def test_exchange_on_already_exchanged_line_reports_state_error(api):
    """PRD §3.5: "Approval requires three conditions. First, the referenced OrderLine
    must be in FULFILLED status, or the request is rejected with
    ERR_LINE_NOT_EXCHANGEABLE_STATE."

    Design: Difficulty/priority_pair_validation_conflict/exchange_state_beats_temporal
    """
    ctx, exch2 = _state_beats_temporal(api)
    line = validate_success(api.get_order_line(ctx["line"]["id"], SM), 200)
    assert line["status"] == "EXCHANGED", line
    res = api.approve_exchange(exch2["id"], SM)
    validate_error(res, ApiErrorId.ERR_LINE_NOT_EXCHANGEABLE_STATE)


# ─── Exchange window boundary (queue A) ───────────────────────────────────
def test_exchange_window_day30_allowed(api):
    """PRD §3.5: "the number of whole days between the order's fulfilled_at and the
    logical clock's current instant must be within the exchange window of 30 days ...
    the boundary is inclusive, so an approval at exactly 30 days after fulfillment is
    still allowed and only day 31 onward is rejected."
    PRD §3.5: "The exchange's store_credit_issued_cents is set to the line's
    line_net_cents".

    Design: Difficulty/boundary_precision_check/exchange_window_boundary_day30_allowed
    """
    ctx = setup_fulfilled_line(base_price_cents=4000, initial_stock=2, quantity=1)
    set_clock("2026-07-31T00:00:00Z")  # exactly 30 days after 2026-07-01
    exch = request_exchange(ctx, "SEALED")
    approved = validate_success(api.approve_exchange(exch["id"], SM), 200)
    assert approved["status"] == "APPROVED", approved
    assert approved["store_credit_issued_cents"] == 4000, approved


def test_exchange_window_day31_rejected(api):
    """PRD §3.5: "the number of whole days between the order's fulfilled_at and the
    logical clock's current instant must be within the exchange window of 30 days, or
    the request is rejected with ERR_EXCHANGE_WINDOW_EXPIRED; the boundary is
    inclusive, so an approval at exactly 30 days after fulfillment is still allowed
    and only day 31 onward is rejected."

    Design: Difficulty/boundary_precision_check/exchange_window_boundary_day30_allowed
    """
    ctx = setup_fulfilled_line(base_price_cents=4000, initial_stock=2, quantity=1)
    set_clock("2026-08-01T00:00:00Z")  # 31 days after 2026-07-01
    exch = request_exchange(ctx, "SEALED")
    res = api.approve_exchange(exch["id"], SM)
    validate_error(res, ApiErrorId.ERR_EXCHANGE_WINDOW_EXPIRED)


# ─── Hygiene / window guards (queue B) ────────────────────────────────────
def test_exchange_worn_item_hygiene_rejected(api):
    """PRD §3.5: "the item_condition must be SEALED and the product's hygiene_class
    must be STANDARD_RETURNABLE; a non-sealed item, or any INTIMATE_NON_RETURNABLE
    product, is rejected with ERR_ITEM_NOT_EXCHANGEABLE_HYGIENE."

    Design: Corner/state_machines/exchange_worn_item_returns_hygiene_error
    """
    ctx = setup_fulfilled_line(base_price_cents=4000, initial_stock=3, quantity=1)
    exch = request_exchange(ctx, "WORN")
    res = api.approve_exchange(exch["id"], SM)
    validate_error(res, ApiErrorId.ERR_ITEM_NOT_EXCHANGEABLE_HYGIENE)


def test_exchange_after_window_rejected(api):
    """PRD §3.5: "the number of whole days between the order's fulfilled_at and the
    logical clock's current instant must be within the exchange window of 30 days, or
    the request is rejected with ERR_EXCHANGE_WINDOW_EXPIRED".

    Design: Corner/state_machines/exchange_after_window_returns_window_expired
    """
    ctx = setup_fulfilled_line(base_price_cents=4000, initial_stock=3, quantity=1)
    set_clock("2026-08-15T00:00:00Z")  # 45 days after fulfillment
    exch = request_exchange(ctx, "SEALED")
    res = api.approve_exchange(exch["id"], SM)
    validate_error(res, ApiErrorId.ERR_EXCHANGE_WINDOW_EXPIRED)


# ─── Exchange cancels the scheduled reminder (queue B) ────────────────────
def test_exchange_approval_cancels_scheduled_reminder(api):
    """PRD §3.5: "Finally, any SCHEDULED ReplacementReminder tied to that
    order_line_id is moved to CANCELLED."

    Design: Corner/cross_cutting_complexity_layers/exchange_cancels_scheduled_reminder_cascade
    """
    ctx = setup_fulfilled_line(base_price_cents=4000, initial_stock=3, quantity=1)
    reminder = get_reminder_for_line(ctx["line"]["id"])
    exch = request_exchange(ctx, "SEALED")
    validate_success(api.approve_exchange(exch["id"], SM), 200)
    after = validate_success(api.get_reminder(reminder["id"], SM), 200)
    assert after["status"] == "CANCELLED", after


# ─── Reminder send timing (queue B) ───────────────────────────────────────
def test_reminder_send_before_due_rejected(api):
    """PRD §3.7: "A StoreManager sends a due reminder, advancing SCHEDULED → SENT, but
    only when the logical clock's current instant is at or after the reminder's
    due_date; sending early is rejected with ERR_REMINDER_NOT_DUE."

    Design: Corner/state_machines/reminder_send_before_due_returns_not_due
    """
    ctx = setup_fulfilled_line(base_price_cents=2000, initial_stock=5, quantity=1)
    reminder = get_reminder_for_line(ctx["line"]["id"])
    res = api.send_reminder(reminder["id"], SM)
    validate_error(res, ApiErrorId.ERR_REMINDER_NOT_DUE)


def test_reminder_send_when_due_succeeds(api):
    """PRD §3.4: "the system creates a ReplacementReminder in SCHEDULED status whose
    due_date is fulfilled_at advanced by 6 calendar months (for example, a line
    fulfilled at 2026-07-01T00:00:00Z yields a due_date of 2027-01-01T00:00:00Z)."
    PRD §3.7: "A StoreManager sends a due reminder, advancing SCHEDULED → SENT, but
    only when the logical clock's current instant is at or after the reminder's
    due_date".

    Design: Corner/state_machines/reminder_send_when_due_succeeds
    """
    ctx = setup_fulfilled_line(base_price_cents=2000, initial_stock=5, quantity=1)
    reminder = get_reminder_for_line(ctx["line"]["id"])
    set_clock("2027-01-01T00:00:00Z")
    sent = validate_success(api.send_reminder(reminder["id"], SM), 200)
    assert sent["status"] == "SENT", sent
