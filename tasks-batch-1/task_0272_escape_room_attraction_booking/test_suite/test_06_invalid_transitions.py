"""Invalid and terminal state transitions, plus the waiver cyclic machine.

Corner coverage over the state_machines section.
"""
from test_helpers import (
    validate_success,
    validate_error,
    setup_draft_booking,
    setup_confirmed_booking,
    create_venue,
    create_gift_card,
    sign_waiver,
    add_participant,
    cancel_booking,
    get_slot,
    make_customer_headers,
    make_game_master_headers,
    TEST_USERS,
)

MANAGER = TEST_USERS["venue_manager_headers"]
OFFPEAK_SLOT = "2026-07-01T09:00:00Z"


def test_complete_from_confirmed_without_checkin_rejected(api):
    """PRD §3.7: "Completing a `CHECKED_IN` booking advances it to `COMPLETED` and
    settles the charge."
    PRD §2.9: "Only then does the system check that the target resource is in a valid
    state for the requested transition, raising `ERR_INVALID_STATE` (HTTP 409) when it
    is not."

    complete requires CHECKED_IN; calling complete on a CONFIRMED booking (skipping
    check-in) yields ERR_INVALID_STATE.

    Design: Corner/state_machines/complete_from_confirmed_skips_checkin_returns_invalid_state
    """
    ctx = setup_confirmed_booking(
        start_utc=OFFPEAK_SLOT,
        group_size=2,
        num_game_masters=1,
        room_overrides={"base_price_cents": 2000, "min_group_size": 1, "max_group_size": 4,
                        "reset_buffer_minutes": 30, "waiver_required": False},
    )
    booking, gm = ctx["booking"], ctx["game_masters"][0]
    res = api.complete_booking(
        booking["id"], {"expected_booking_version": booking["version"]},
        make_game_master_headers(gm["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_close_held_slot_rejected(api):
    """PRD §3.2: "Closing permanently removes a slot from inventory, moving it to
    `CLOSED`, and is permitted only when the slot is in `OPEN` or `BLOCKED`; a `HELD` or
    `BOOKED` slot cannot be closed."
    PRD §3.2: "Attempting any of them from a state the action does not allow is an
    `ERR_INVALID_STATE`."

    A slot held by a DRAFT booking cannot be closed -> ERR_INVALID_STATE.

    Design: Corner/state_machines/close_held_slot_returns_invalid_state
    """
    ctx = setup_draft_booking(
        start_utc=OFFPEAK_SLOT,
        group_size=2,
        num_game_masters=1,
        room_overrides={"base_price_cents": 2000, "min_group_size": 1, "max_group_size": 4,
                        "reset_buffer_minutes": 30, "waiver_required": False},
    )
    slot_now = get_slot(ctx["slot"]["id"])
    assert slot_now["status"] == "HELD"
    res = api.close_time_slot(slot_now["id"], {"expected_time_slot_version": slot_now["version"]}, MANAGER)
    validate_error(res, "ERR_INVALID_STATE")


def test_cancel_already_cancelled_booking_rejected(api):
    """PRD §3.8: "A `Customer` may cancel a booking that is in `DRAFT` or `CONFIRMED`,
    moving it to `CANCELLED`; a cancel from any other state is `ERR_INVALID_STATE`."

    CANCELLED is terminal; a second cancel on a CANCELLED booking yields
    ERR_INVALID_STATE.

    Design: Corner/state_machines/terminal_cancelled_booking_cannot_cancel_again
    """
    ctx = setup_draft_booking(
        start_utc=OFFPEAK_SLOT,
        group_size=2,
        num_game_masters=1,
        room_overrides={"base_price_cents": 2000, "min_group_size": 1, "max_group_size": 4,
                        "reset_buffer_minutes": 30, "waiver_required": False},
    )
    booking, customer = ctx["booking"], ctx["customer"]
    cancelled = cancel_booking(booking, customer)
    assert cancelled["lifecycle_status"] == "CANCELLED"

    res = api.cancel_booking(
        cancelled["id"], {"expected_booking_version": cancelled["version"]},
        make_customer_headers(customer["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_waiver_sign_then_revoke_cycles_to_revoked(api):
    """PRD §3.4: "A customer signs a participant's waiver, moving `waiver_status` from
    `PENDING` or `REVOKED` to `SIGNED`."
    PRD §3.4: "A customer may also revoke a signed waiver, moving `waiver_status` from
    `SIGNED` to `REVOKED`, again only while the booking is in `DRAFT` or `CONFIRMED`."

    The waiver cyclic machine: PENDING->SIGNED then SIGNED->REVOKED leaves the final
    waiver_status at REVOKED.

    Design: Corner/state_machines/waiver_cyclic_revoke_after_sign
    """
    ctx = setup_draft_booking(
        start_utc=OFFPEAK_SLOT,
        group_size=1,
        num_game_masters=1,
        room_overrides={"base_price_cents": 2000, "min_group_size": 1, "max_group_size": 4,
                        "reset_buffer_minutes": 30, "waiver_required": True, "min_age": 0},
    )
    booking, customer = ctx["booking"], ctx["customer"]
    participant = add_participant(booking, customer, display_name="P1", age=30)
    signed = sign_waiver(participant, customer)
    assert signed["waiver_status"] == "SIGNED"

    revoked = validate_success(api.revoke_waiver(
        signed["id"], {"expected_participant_version": signed["version"]},
        make_customer_headers(customer["id"])), 200)
    assert revoked["waiver_status"] == "REVOKED"


def test_top_up_voided_gift_card_rejected(api):
    """PRD §3.9: "A manager may also void a card, moving its `status` to `VOID` from
    either `ACTIVE` or `DEPLETED`, after which the balance is frozen and no further
    spend, refund, or top-up is accepted."
    PRD §2.9: "Only then does the system check that the target resource is in a valid
    state for the requested transition, raising `ERR_INVALID_STATE` (HTTP 409) when it
    is not."

    VOID is terminal; a top-up on a VOID card yields ERR_INVALID_STATE.

    Design: Corner/state_machines/giftcard_void_then_topup_returns_invalid_state
    """
    venue = create_venue()
    gc = create_gift_card(venue["id"], initial_balance_cents=5000)
    voided = validate_success(api.void_gift_card(
        gc["id"], {"expected_gift_card_version": gc["version"]}, MANAGER), 200)
    assert voided["status"] == "VOID"

    res = api.top_up_gift_card(
        gc["id"], {"amount_cents": 1000, "expected_gift_card_version": voided["version"]}, MANAGER)
    validate_error(res, "ERR_INVALID_STATE")
