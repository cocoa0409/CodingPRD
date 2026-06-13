"""Tow-order lifecycle: cyclic AUCTION_ELIGIBLE<->STORED, freeze/resume accrual
conservation, notification branching, statutory eligibility, and store/void
preconditions.

Covers difficulty rules: non_linear_state_machine, transitive_cascade (confirm-delivery),
boundary_precision (empty notice set), compensating_invariant (freeze/resume); and
corner state_machines / errors instances.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    set_clock,
    create_lot,
    create_order,
    add_inventory,
    create_stored_order,
    create_delivered_notice,
    setup_auction_eligible_order,
    setup_open_auction_with_swept_order,
)

OP = TEST_USERS["lot_operator_headers"]
POLICE = TEST_USERS["police_officer_headers"]
AUCTION = TEST_USERS["auction_official_headers"]


# ─── non_linear_state_machine / tow_order_cyclic_auction_eligible_back_to_stored ─
def test_reclaim_returns_auction_eligible_order_to_stored(api):
    """PRD §3.8: "A LotOperator reclaims an order, moving it AUCTION_ELIGIBLE → STORED;
    this is allowed only from AUCTION_ELIGIBLE (otherwise ERR_INVALID_STATE) and only
    while the order's auction_id is still null"
    PRD §3.8: "Reclaiming resumes accrual by opening a new StorageLedgerEntry with kind
    RESUME and segment_start at the current clock and clearing accrual_frozen_at"

    Design: Difficulty/non_linear_state_machine/tow_order_cyclic_auction_eligible_back_to_stored
    """
    lot, order = setup_auction_eligible_order(
        intake_iso="2026-04-01T00:00:00Z", eligible_iso="2026-05-15T00:00:00Z")
    assert order["status"] == "AUCTION_ELIGIBLE"
    res = api.reclaim_order(order["id"], OP)
    reclaimed = validate_success(res, 200)
    assert reclaimed["status"] == "STORED"
    assert reclaimed["accrual_frozen_at"] is None, "accrual_frozen_at cleared on resume"


def test_marking_auction_eligible_freezes_accrual(api):
    """PRD §3.8: "On success it freezes accrual exactly as authorization does: it closes
    the current open StorageLedgerEntry with segment_end at the current clock and kind
    FREEZE, and sets accrual_frozen_at."

    Design: Difficulty/non_linear_state_machine/tow_order_cyclic_auction_eligible_back_to_stored
    """
    lot, order = setup_auction_eligible_order(
        intake_iso="2026-04-01T00:00:00Z", eligible_iso="2026-05-15T00:00:00Z")
    assert order["status"] == "AUCTION_ELIGIBLE"
    assert order["accrual_frozen_at"] is not None, "accrual frozen on mark-auction-eligible"


# ─── non_linear_state_machine / notification_branching_sent_to_three_terminals ─
def test_undeliverable_notice_does_not_satisfy_statutory_gate(api):
    """PRD §3.4: "Marking a notice undeliverable moves it SENT → UNDELIVERABLE ... it
    stamps resolved_at but pointedly does not start the grace clock and leaves statutory
    eligibility unaffected"
    PRD §3.8: "requires the order to have passed the statutory-eligibility gate, failing
    with ERR_STATUTORY_PERIOD_NOT_ELAPSED if it has not."

    Design: Difficulty/non_linear_state_machine/notification_branching_sent_to_three_terminals
    """
    set_clock("2026-04-01T00:00:00Z")
    lot, order = create_stored_order(order_overrides={"tow_type": "ABANDONED"})
    n = get_success_data(api.create_notification(
        order["id"], {"recipient_type": "OWNER", "method": "CERTIFIED_MAIL"}, OP))
    get_success_data(api.send_notification(order["id"], n["id"], OP))
    get_success_data(api.mark_undeliverable(order["id"], n["id"], OP))
    set_clock("2026-05-15T00:00:00Z")  # statutory hold days elapsed
    res = api.mark_auction_eligible(order["id"], OP)
    validate_error(res, "ERR_STATUTORY_PERIOD_NOT_ELAPSED", expected_status=409)
    note = validate_success(api.get_notification(order["id"], n["id"], OP), 200)
    assert note["status"] == "UNDELIVERABLE"


def test_undeliverable_is_reached_from_sent(api):
    """PRD §3.4: "Marking a notice undeliverable moves it SENT → UNDELIVERABLE (allowed
    only from SENT, else ERR_INVALID_STATE)"

    Design: Difficulty/non_linear_state_machine/notification_branching_sent_to_three_terminals
    """
    set_clock("2026-04-01T00:00:00Z")
    lot, order = create_stored_order(order_overrides={"tow_type": "ABANDONED"})
    n = get_success_data(api.create_notification(
        order["id"], {"recipient_type": "OWNER", "method": "CERTIFIED_MAIL"}, OP))
    get_success_data(api.send_notification(order["id"], n["id"], OP))
    res = api.mark_undeliverable(order["id"], n["id"], OP)
    note = validate_success(res, 200)
    assert note["status"] == "UNDELIVERABLE"


# ─── transitive_cascade / confirm_delivery_cascades_to_statutory_eligibility ──
def test_confirm_delivery_unblocks_auction_eligibility(api):
    """PRD §3.4: "Confirming delivery moves it SENT → DELIVERY_CONFIRMED ... it stamps
    resolved_at to the current clock, which starts the notice grace clock running on the
    tow order, and recomputes the order's statutory eligibility."
    PRD §3.8: "there exists at least one notification on the order whose status is
    DELIVERY_CONFIRMED or CERTIFIED_RETURNED and whose days between resolved_at and the
    current clock (same ceiling day rule, same inclusive boundary) is at least the lot's
    notice_grace_days."

    Design: Difficulty/transitive_cascade/confirm_delivery_cascades_to_statutory_eligibility
    """
    set_clock("2026-06-01T00:00:00Z")
    lot, order = create_stored_order(order_overrides={"tow_type": "ABANDONED"})
    create_delivered_notice(order["id"])
    set_clock("2026-07-05T00:00:00Z")  # well past statutory hold + grace
    res = api.mark_auction_eligible(order["id"], OP)
    eligible = validate_success(res, 200)
    assert eligible["status"] == "AUCTION_ELIGIBLE"


def test_confirm_delivery_sets_notification_terminal(api):
    """PRD §3.4: "Confirming delivery moves it SENT → DELIVERY_CONFIRMED (allowed only
    from SENT, else ERR_INVALID_STATE); it stamps resolved_at to the current clock, which
    starts the notice grace clock running on the tow order"

    Design: Difficulty/transitive_cascade/confirm_delivery_cascades_to_statutory_eligibility
    """
    set_clock("2026-06-01T00:00:00Z")
    lot, order = create_stored_order(order_overrides={"tow_type": "ABANDONED"})
    note = create_delivered_notice(order["id"])
    assert note["status"] == "DELIVERY_CONFIRMED"
    assert note["resolved_at"] is not None


# ─── boundary_precision / statutory_eligibility_empty_notification_set_blocks ─
def test_no_notifications_blocks_auction_eligibility(api):
    """PRD §3.8: "The second is that the notice grace window has elapsed: there exists
    at least one notification on the order whose status is DELIVERY_CONFIRMED or
    CERTIFIED_RETURNED ... Both conditions must be true at once for the order to be
    marked eligible."

    Design: Difficulty/boundary_precision_check/statutory_eligibility_empty_notification_set_blocks
    """
    set_clock("2026-09-01T00:00:00Z")
    lot, order = create_stored_order(order_overrides={"tow_type": "ABANDONED"})
    set_clock("2026-11-01T00:00:00Z")  # 2 months: statutory hold elapsed but NO notices
    res = api.mark_auction_eligible(order["id"], OP)
    validate_error(res, "ERR_STATUTORY_PERIOD_NOT_ELAPSED", expected_status=409)


def test_delivered_notice_alone_without_hold_period_blocks(api):
    """PRD §3.8: "The first is that the holding period has elapsed: the days between
    intake_at and the current clock ... is at least the lot's statutory_hold_days."
    PRD §3.8: "Both conditions must be true at once for the order to be marked eligible."

    Design: Difficulty/boundary_precision_check/statutory_eligibility_empty_notification_set_blocks
    """
    set_clock("2026-09-01T00:00:00Z")
    lot, order = create_stored_order(
        lot_overrides={"statutory_hold_days": 30, "notice_grace_days": 0},
        order_overrides={"tow_type": "ABANDONED"})
    create_delivered_notice(order["id"])  # grace satisfied immediately (grace_days 0)
    set_clock("2026-09-10T00:00:00Z")  # only 9 days: statutory hold NOT elapsed
    res = api.mark_auction_eligible(order["id"], OP)
    validate_error(res, "ERR_STATUTORY_PERIOD_NOT_ELAPSED", expected_status=409)


# ─── compensating_invariant / freeze_resume_conserves_accrued_storage_days ────
def test_freeze_then_resume_conserves_total_accrued_days(api):
    """PRD §2.9: "The order's reported accrued_days and accrued_storage_cents are always
    derived by summing days_counted and segment_charge_cents across these segments, so
    that freezing and resuming accrual never double-counts a day at the boundary."
    PRD §3.8: "with the same compensating invariant that accrued_days continues from the
    frozen value and no day is double-counted."

    Design: Difficulty/compensating_invariant/freeze_resume_conserves_accrued_storage_days
    """
    set_clock("2027-03-01T00:00:00Z")
    lot, order = create_stored_order(
        lot_overrides={"daily_storage_rate_cents": 5000, "statutory_hold_days": 3,
                       "notice_grace_days": 0},
        order_overrides={"tow_type": "ABANDONED"})
    create_delivered_notice(order["id"])
    set_clock("2027-03-04T00:00:00Z")  # +3 days
    get_success_data(api.mark_auction_eligible(order["id"], OP))  # freeze at 3 days (15000)
    get_success_data(api.reclaim_order(order["id"], OP))          # resume
    set_clock("2027-03-06T00:00:00Z")  # +2 more days
    refreshed = validate_success(api.get_tow_order(order["id"], OP), 200)
    assert refreshed["accrued_days"] == 5, "3 frozen + 2 resumed; no day double-counted"
    assert refreshed["accrued_storage_cents"] == 25000


def test_freeze_at_three_days_records_partial_accrual(api):
    """PRD §3.8: "On success it freezes accrual exactly as authorization does: it closes
    the current open StorageLedgerEntry with segment_end at the current clock and kind
    FREEZE, and sets accrual_frozen_at."

    Design: Difficulty/compensating_invariant/freeze_resume_conserves_accrued_storage_days
    """
    set_clock("2027-03-01T00:00:00Z")
    lot, order = create_stored_order(
        lot_overrides={"daily_storage_rate_cents": 5000, "statutory_hold_days": 3,
                       "notice_grace_days": 0},
        order_overrides={"tow_type": "ABANDONED"})
    create_delivered_notice(order["id"])
    set_clock("2027-03-04T00:00:00Z")  # +3 days
    eligible = validate_success(api.mark_auction_eligible(order["id"], OP), 200)
    assert eligible["accrued_storage_cents"] == 15000, "3 days * 5000 frozen"


# ─── Corner: state_machines / store_from_already_stored_returns_invalid_state ─
def test_store_already_stored_order_rejected(api):
    """PRD §3.3: "The transition TOWED → STORED requires the order to actually be in
    TOWED (otherwise ERR_INVALID_STATE)"

    Design: Corner/state_machines/store_from_already_stored_returns_invalid_state
    """
    set_clock("2026-01-01T00:00:00Z")
    lot, order = create_stored_order(order_overrides={"tow_type": "POLICE"})
    res = api.store_order(order["id"], OP)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── Corner: state_machines / store_without_inventory_returns_inventory_required ─
def test_store_without_inventory_rejected(api):
    """PRD §3.3: "requires at least one InventoryItem to have been documented for the
    order as intake evidence; storing an order with no inventory on file is rejected with
    ERR_INVENTORY_REQUIRED."

    Design: Corner/state_machines/store_without_inventory_returns_inventory_required
    """
    lot = create_lot()
    order = create_order(lot["id"], tow_type="POLICE")
    res = api.store_order(order["id"], OP)
    validate_error(res, "ERR_INVENTORY_REQUIRED", expected_status=409)


# ─── Corner: state_machines / terminal_released_order_rejects_void ────────────
def test_void_on_released_order_rejected(api):
    """PRD §3.3: "Voiding is permitted only while the order's status is one of TOWED or
    STORED (otherwise ERR_INVALID_STATE)"

    Design: Corner/state_machines/terminal_released_order_rejects_void
    """
    from test_helpers import take_order_to_released
    lot, order = take_order_to_released(
        intake_iso="2026-01-01T00:00:00Z", advance_iso="2026-01-06T00:00:00Z",
        net_due_cents=32500,
        lot_overrides={"daily_storage_rate_cents": 5000, "admin_fee_cents": 7500},
        order_overrides={"tow_type": "POLICE"})
    assert order["status"] == "RELEASED"
    res = api.void_order(order["id"], POLICE)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── Corner: state_machines / send_lienholder_notice_without_lienholder ───────
def test_send_lienholder_notice_without_lienholder_rejected(api):
    """PRD §3.4: "when the recipient_type is LIENHOLDER, the parent tow order must
    actually carry a lienholder_id, or the send is rejected with ERR_NO_LIENHOLDER."

    Design: Corner/state_machines/send_lienholder_notice_without_lienholder_returns_error
    """
    lot = create_lot()
    order = create_order(lot["id"], tow_type="ABANDONED")
    n = get_success_data(api.create_notification(
        order["id"], {"recipient_type": "LIENHOLDER", "method": "CERTIFIED_MAIL"}, OP))
    res = api.send_notification(order["id"], n["id"], OP)
    validate_error(res, "ERR_NO_LIENHOLDER", expected_status=409)


# ─── Corner: state_machines / mark_returned_on_non_certified_notice_rejected ──
def test_mark_returned_on_email_notice_rejected(api):
    """PRD §3.4: "Marking a certified letter returned moves it SENT → CERTIFIED_RETURNED
    ... and is permitted only when the notice's method is CERTIFIED_MAIL, otherwise it is
    rejected with ERR_METHOD_NOT_CERTIFIED"

    Design: Corner/state_machines/mark_returned_on_non_certified_notice_rejected
    """
    lot = create_lot()
    order = create_order(lot["id"], tow_type="ABANDONED")
    n = get_success_data(api.create_notification(
        order["id"], {"recipient_type": "OWNER", "method": "EMAIL"}, OP))
    get_success_data(api.send_notification(order["id"], n["id"], OP))
    res = api.mark_returned(order["id"], n["id"], OP)
    validate_error(res, "ERR_METHOD_NOT_CERTIFIED", expected_status=409)


# ─── Corner: state_machines / lift_hold_when_none_returns_no_hold ─────────────
def test_lift_hold_with_no_active_hold_rejected(api):
    """PRD §3.3: "Lifting a hold is permitted only when a hold is in fact active — if
    hold_status is already NONE the request is rejected with ERR_NO_HOLD"

    Design: Corner/state_machines/lift_hold_when_none_returns_no_hold
    """
    lot = create_lot()
    order = create_order(lot["id"], tow_type="POLICE")
    res = api.lift_hold(order["id"], POLICE)
    validate_error(res, "ERR_NO_HOLD", expected_status=409)


# ─── Corner: state_machines / reclaim_after_sweep_returns_already_in_auction ──
def test_reclaim_after_sweep_rejected(api):
    """PRD §3.8: "this is allowed only from AUCTION_ELIGIBLE (otherwise ERR_INVALID_STATE)
    and only while the order's auction_id is still null, meaning it has not yet been swept
    into an auction — reclaiming an already-swept order is rejected with
    ERR_ALREADY_IN_AUCTION."

    Design: Corner/state_machines/reclaim_after_sweep_returns_already_in_auction
    """
    lot, order, auction = setup_open_auction_with_swept_order(
        intake_iso="2027-06-01T00:00:00Z", eligible_iso="2027-06-10T00:00:00Z",
        window_start="2027-06-10T00:00:00Z", window_end="2027-06-10T06:00:00Z",
        lot_overrides={"statutory_hold_days": 3, "notice_grace_days": 0})
    res = api.reclaim_order(order["id"], OP)
    validate_error(res, "ERR_ALREADY_IN_AUCTION", expected_status=409)


# ─── Corner: state_machines / auction_open_before_window_start_rejected ───────
def test_open_auction_before_window_start_rejected(api):
    """PRD §3.9: "opening is allowed only from SCHEDULED (otherwise ERR_INVALID_STATE)
    and only once the current clock is at or after window_start, failing with
    ERR_AUCTION_WINDOW_NOT_STARTED before then."

    Design: Corner/state_machines/auction_open_before_window_start_rejected
    """
    set_clock("2027-04-01T00:00:00Z")
    lot = create_lot()
    auction = get_success_data(api.create_auction(
        {"lot_id": lot["id"], "window_start": "2027-05-01T00:00:00Z",
         "window_end": "2027-05-01T06:00:00Z"}, AUCTION))
    res = api.open_auction(auction["id"], AUCTION)
    validate_error(res, "ERR_AUCTION_WINDOW_NOT_STARTED", expected_status=409)
