"""Transitive cascades: retreat-cancel -> booking -> transport -> shuttle, and facilitator-withdraw -> slot -> schedule_ready."""
from test_helpers import (
    validate_success, TEST_USERS,
    setup_booking_deposit_paid, setup_retreat_with_common_room_and_facilitator,
    new_shuttle, book_transport_segment, new_slot, get_shuttle,
)

_OP = TEST_USERS["operator_headers"]


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / retreat_cancel_cascade_to_shuttle_depth3
# ---------------------------------------------------------------------------
def test_retreat_cancel_cascades_through_booking_and_transport_to_shuttle(api):
    """PRD §3.1: "every booking on the retreat still in PENDING_DEPOSIT, DEPOSIT_PAID,
    CONFIRMED, or CHECKED_IN is cancelled with its cancelled_by set to OPERATOR (which forces
    a full refund, per §3.7), each such booking's BOOKED transport segments are cancelled and
    their shuttle seats released."

    Design: Difficulty/transitive_cascade/retreat_cancel_cascade_to_shuttle_depth3
    """
    ctx = setup_booking_deposit_paid(api, party_size=2, retreat_overrides={"base_price_cents": 150000})
    gh = ctx["guest_headers"]
    shuttle = new_shuttle(api, ctx["retreat"]["id"], seat_capacity=4)
    segment = book_transport_segment(api, ctx["booking"]["id"], shuttle["id"], gh)

    validate_success(api.cancel_retreat(ctx["retreat"]["id"], _OP), 200)

    booking = validate_success(api.get_booking(ctx["booking"]["id"], gh), 200)
    assert booking["status"] == "CANCELLED"
    assert booking["cancelled_by"] == "OPERATOR"
    assert booking["refund_cents"] == 90450
    seg = validate_success(api.get_transport_segment(segment["id"], gh), 200)
    assert seg["status"] == "CANCELLED"
    shuttle_after = get_shuttle(api, ctx["retreat"]["id"], shuttle["id"])
    assert shuttle_after["reserved_seats"] == 0


def test_retreat_cancel_records_full_refund_payment(api):
    """PRD §3.7: "the refund is forced to the full amount regardless of lead time ... If that
    refund is greater than zero, the server records a Payment of type REFUND for the refund
    amount."

    Design: Difficulty/transitive_cascade/retreat_cancel_cascade_to_shuttle_depth3
    """
    ctx = setup_booking_deposit_paid(api, party_size=2, retreat_overrides={"base_price_cents": 150000})
    gh = ctx["guest_headers"]
    shuttle = new_shuttle(api, ctx["retreat"]["id"], seat_capacity=4)
    book_transport_segment(api, ctx["booking"]["id"], shuttle["id"], gh)

    validate_success(api.cancel_retreat(ctx["retreat"]["id"], _OP), 200)

    payments = validate_success(api.list_booking_payments(ctx["booking"]["id"], gh), 200)
    refunds = [p for p in payments if p["type"] == "REFUND"]
    assert len(refunds) == 1
    assert refunds[0]["amount_cents"] == 90450


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / facilitator_withdraw_cascade_to_schedule_depth2
# ---------------------------------------------------------------------------
def test_facilitator_withdraw_cancels_scheduled_slot(api):
    """PRD §3.5: "Withdrawing a facilitator moves them from `ACTIVE` to `WITHDRAWN` and cascades: every `SCHEDULED` slot led by that facilitator is cancelled, the `schedule_ready` flag of each affected retreat is recomputed, and the facilitator's `version` is incremented."

    Design: Difficulty/transitive_cascade/facilitator_withdraw_cascade_to_schedule_depth2
    """
    ctx = setup_retreat_with_common_room_and_facilitator(api)
    slot = new_slot(api, ctx["retreat"]["id"], ctx["facilitator"]["id"], ctx["common_room"]["id"],
                    "2026-09-02T09:00:00Z", "2026-09-02T10:00:00Z")
    fac = validate_success(api.withdraw_facilitator(ctx["facilitator"]["id"], _OP), 200)
    assert fac["status"] == "WITHDRAWN"
    slot_after = validate_success(api.get_activity_slot(slot["id"], _OP), 200)
    assert slot_after["status"] == "CANCELLED"


def test_facilitator_withdraw_recomputes_schedule_ready_false(api):
    """PRD §3.5: "the `schedule_ready` flag of each affected retreat is recomputed."
    PRD §3.1: "A retreat also exposes `schedule_ready`, a boolean that is true exactly when at least one activity slot on the retreat is in `SCHEDULED`."

    Design: Difficulty/transitive_cascade/facilitator_withdraw_cascade_to_schedule_depth2
    """
    ctx = setup_retreat_with_common_room_and_facilitator(api)
    new_slot(api, ctx["retreat"]["id"], ctx["facilitator"]["id"], ctx["common_room"]["id"],
             "2026-09-02T09:00:00Z", "2026-09-02T10:00:00Z")
    ready = validate_success(api.get_retreat(ctx["retreat"]["id"], _OP), 200)
    assert ready["schedule_ready"] is True  # slot scheduled -> ready
    validate_success(api.withdraw_facilitator(ctx["facilitator"]["id"], _OP), 200)
    retreat = validate_success(api.get_retreat(ctx["retreat"]["id"], _OP), 200)
    assert retreat["schedule_ready"] is False
