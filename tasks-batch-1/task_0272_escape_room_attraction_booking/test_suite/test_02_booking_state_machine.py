"""Booking and TimeSlot state machines.

Covers the parallel lifecycle/payment axes advancing under one confirm, and the
TimeSlot branching-with-revert machine (OPEN->HELD on grab, HELD->OPEN on cancel).
"""
from test_helpers import (
    validate_success,
    setup_draft_booking,
    confirm_booking,
    cancel_booking,
    make_customer_headers,
)

OFFPEAK_SLOT = "2026-07-01T09:00:00Z"


# ─── non_linear_state_machine: parallel axes ──────────
def test_confirm_advances_lifecycle_and_payment_axes_together(api):
    """PRD §3.5: "The held slot advances from `HELD` to `BOOKED`, the booking's
    `lifecycle_status` becomes `CONFIRMED`, and the booking's `version` is incremented."
    PRD §3.5: "The remaining amount — `quoted_charge_cents` minus
    `gift_card_applied_cents` — is authorized on the card, moving the booking's
    `payment_status` from `UNPAID` to `AUTHORIZED`."

    The two independent axes on the same Booking advance under one confirm:
    lifecycle DRAFT->CONFIRMED and payment UNPAID->AUTHORIZED. Off-peak group 2,
    base 2000 -> quote 4000.

    Design: Difficulty/non_linear_state_machine/booking_parallel_lifecycle_and_payment_axes
    """
    ctx = setup_draft_booking(
        start_utc=OFFPEAK_SLOT,
        group_size=2,
        room_overrides={"base_price_cents": 2000, "min_group_size": 1, "max_group_size": 8,
                        "reset_buffer_minutes": 30, "waiver_required": False,
                        "private_surcharge_cents": 0},
    )
    assert ctx["booking"]["lifecycle_status"] == "DRAFT"
    assert ctx["booking"]["payment_status"] == "UNPAID"

    confirmed = confirm_booking(ctx["booking"], ctx["customer"])
    assert confirmed["lifecycle_status"] == "CONFIRMED"
    assert confirmed["payment_status"] == "AUTHORIZED"
    assert confirmed["quoted_charge_cents"] == 4000


def test_draft_booking_starts_unpaid_on_both_axes(api):
    """PRD §3.3: "This single action advances the slot from `OPEN` to `HELD` and creates
    a new booking in `lifecycle_status` of `DRAFT` and `payment_status` of `UNPAID`."

    Before confirm the two parallel axes both sit at their initial states: lifecycle
    DRAFT and payment UNPAID, independent of each other.

    Design: Difficulty/non_linear_state_machine/booking_parallel_lifecycle_and_payment_axes
    """
    ctx = setup_draft_booking(
        start_utc=OFFPEAK_SLOT,
        group_size=2,
        room_overrides={"base_price_cents": 2000, "min_group_size": 1, "max_group_size": 8,
                        "reset_buffer_minutes": 30, "waiver_required": False},
    )
    booking = validate_success(
        api.get_booking(ctx["booking"]["id"], make_customer_headers(ctx["customer"]["id"])), 200)
    assert booking["lifecycle_status"] == "DRAFT"
    assert booking["payment_status"] == "UNPAID"


# ─── non_linear_state_machine: TimeSlot revert ────────
def test_cancel_draft_reverts_slot_held_to_open(api):
    """PRD §3.8: "Any held or booked slot the booking occupied is released to `OPEN`,
    freeing its game master."
    PRD §3.3: "This single action advances the slot from `OPEN` to `HELD`."

    The TimeSlot branching-with-revert machine: a grab took it OPEN->HELD; cancelling
    the DRAFT booking reverts it HELD->OPEN and clears booking_id and the assigned GM.

    Design: Difficulty/non_linear_state_machine/timeslot_branch_with_revert_held_back_to_open
    """
    ctx = setup_draft_booking(
        start_utc=OFFPEAK_SLOT,
        group_size=2,
        room_overrides={"base_price_cents": 2000, "min_group_size": 1, "max_group_size": 8,
                        "reset_buffer_minutes": 30, "waiver_required": False},
    )
    slot, booking, customer = ctx["slot"], ctx["booking"], ctx["customer"]

    # Slot is HELD immediately after the grab.
    held = validate_success(api.get_time_slot(slot["id"], make_customer_headers(customer["id"])), 200)
    assert held["status"] == "HELD"
    assert held["booking_id"] == booking["id"]

    cancelled = cancel_booking(booking, customer)
    assert cancelled["lifecycle_status"] == "CANCELLED"

    reverted = validate_success(api.get_time_slot(slot["id"], make_customer_headers(customer["id"])), 200)
    assert reverted["status"] == "OPEN"
    assert reverted["booking_id"] is None
    assert reverted["assigned_game_master_id"] is None


def test_grab_sets_slot_held_with_assigned_gamemaster(api):
    """PRD §3.3: "This single action advances the slot from `OPEN` to `HELD`."
    PRD §3.3: "The slot's `booking_id` is set to the new booking, its
    `assigned_game_master_id` is set to the selected master, and the slot's `version`
    is incremented."

    The forward edge of the branching machine (OPEN->HELD): the grab leaves the slot
    HELD with booking_id and assigned_game_master_id set.

    Design: Difficulty/non_linear_state_machine/timeslot_branch_with_revert_held_back_to_open
    """
    ctx = setup_draft_booking(
        start_utc=OFFPEAK_SLOT,
        group_size=2,
        room_overrides={"base_price_cents": 2000, "min_group_size": 1, "max_group_size": 8,
                        "reset_buffer_minutes": 30, "waiver_required": False},
    )
    slot, booking, gm, customer = ctx["slot"], ctx["booking"], ctx["game_masters"][0], ctx["customer"]
    held = validate_success(api.get_time_slot(slot["id"], make_customer_headers(customer["id"])), 200)
    assert held["status"] == "HELD"
    assert held["booking_id"] == booking["id"]
    assert held["assigned_game_master_id"] == gm["id"]
