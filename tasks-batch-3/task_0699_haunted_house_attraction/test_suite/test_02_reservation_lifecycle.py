"""Reservation lifecycle: parallel entry/payment dimensions, refunds, wallet,
occupancy/money conservation, and no-show."""
import pytest
from test_helpers import (
    api_client, get_success_data, validate_success,
    setup_venue_attraction_slot, setup_admission_ready,
    create_paid_reservation, create_reserved_reservation,
    create_held_reservation_with_ticket, confirm_reservation,
    create_guest, create_reservation, add_ticket, set_clock,
    open_closure, make_guest_headers, TEST_USERS,
)

BOX = TEST_USERS["box_office_headers"]
OPS = TEST_USERS["ops_headers"]


def test_pay_advances_payment_only_then_admit_advances_entry(api):
    """PRD 3.7: "A reservation may be paid only while its entry_status is RESERVED
    and its payment_status is UNPAID". PRD 3.7: "Admission takes a RESERVED, PAID
    reservation through the gate". PRD 3.7: "On success the reservation moves to
    ADMITTED".

    Paying leaves entry_status RESERVED while payment_status becomes PAID; only after
    PAID can admit move entry_status to ADMITTED — the two axes advance independently.

    Design: Difficulty/non_linear_state_machine/nlsm_reservation_parallel_entry_x_payment_dimensions
    """
    venue, attraction, slot, zone, guest, reservation, ticket = setup_admission_ready()
    assert reservation["entry_status"] == "RESERVED"
    assert reservation["payment_status"] == "PAID"

    admitted = validate_success(api.admit_reservation(reservation["id"], BOX), 200)
    assert admitted["entry_status"] == "ADMITTED"
    assert admitted["payment_status"] == "PAID"


def test_payment_status_evolves_without_changing_entry_status(api):
    """PRD 3.7: "Payment and entry evolve as two independent dimensions of the same
    reservation: its entry_status and its payment_status advance separately." PRD 3.7:
    "Payment moves the reservation to PAID and increments its version."

    A RESERVED+UNPAID reservation paid stays entry_status RESERVED while
    payment_status flips UNPAID -> PAID.

    Design: Difficulty/non_linear_state_machine/nlsm_reservation_parallel_entry_x_payment_dimensions
    """
    venue, attraction, slot = setup_venue_attraction_slot()
    guest, reservation, ticket = create_reserved_reservation(venue["id"], slot["id"])
    assert reservation["entry_status"] == "RESERVED"
    assert reservation["payment_status"] == "UNPAID"

    paid = validate_success(api.pay_reservation(reservation["id"], BOX), 200)
    assert paid["entry_status"] == "RESERVED", "paying must not change entry_status"
    assert paid["payment_status"] == "PAID"


def test_self_cancel_refunds_full_total_to_guest_wallet(api):
    """PRD 3.7: "If the reservation had been PAID, its payment state moves to
    REFUNDED and the full total_cents is credited to the guest's wallet_credit_cents."

    A guest self-cancelling a RESERVED+PAID reservation of total 2410 credits the
    wallet by the full 2410.

    Design: Difficulty/dual_variant_calc/dvc_refund_credit_self_cancel_vs_closure_on_guest_wallet
    """
    venue, attraction, slot = setup_venue_attraction_slot()
    guest, reservation, ticket = create_paid_reservation(venue["id"], slot["id"])
    assert reservation["total_cents"] == 2410

    cancelled = validate_success(
        api.cancel_reservation(reservation["id"], make_guest_headers(guest["id"])), 200
    )
    assert cancelled["payment_status"] == "REFUNDED"
    refreshed_guest = validate_success(api.get_guest(guest["id"], BOX), 200)
    assert refreshed_guest["wallet_credit_cents"] == 2410


def test_closure_cascade_refunds_full_total_to_guest_wallet(api):
    """PRD 3.9: "every reservation holding a ticket on a now-closed slot whose entry
    state is HELD or RESERVED is moved to CANCELLED. Third — caused by each such
    cancellation where the reservation's payment state was PAID — the payment state
    moves to REFUNDED and the reservation's full total_cents is added to the owning
    guest's wallet_credit_cents."

    A WEATHER closure auto-refunding a PAID reservation of total 2410 credits the
    guest wallet by the full 2410, exactly as a self-cancel does.

    Design: Difficulty/dual_variant_calc/dvc_refund_credit_self_cancel_vs_closure_on_guest_wallet
    """
    venue, attraction, slot = setup_venue_attraction_slot()
    guest, reservation, ticket = create_paid_reservation(venue["id"], slot["id"])
    assert reservation["total_cents"] == 2410

    open_closure(attraction["id"], reason="WEATHER")

    refreshed_res = validate_success(api.get_reservation(reservation["id"], BOX), 200)
    assert refreshed_res["payment_status"] == "REFUNDED"
    refreshed_guest = validate_success(api.get_guest(guest["id"], BOX), 200)
    assert refreshed_guest["wallet_credit_cents"] == 2410


def test_wallet_applies_before_cash_on_pay(api):
    """PRD 3.7: "The amount applied from the wallet is the smaller of the guest's
    wallet_credit_cents and the reservation's total_cents; that applied amount is
    subtracted from wallet_credit_cents, and the cash charged is the total_cents less
    the applied amount."

    A guest holding wallet 4820 (from a refunded two-ticket reservation) paying a new
    2410 reservation drains the wallet to 2410 and marks the reservation PAID.

    Design: Corner/calculations/wallet_apply_drains_before_cash
    """
    venue, attraction, slot = setup_venue_attraction_slot(slot_overrides={"capacity": 10})
    guest = create_guest(full_name="Wallet Guest", email="wal@x.com")

    # Build wallet 4820: confirm+pay a two-ticket reservation (2*2410), then cancel.
    big = create_reservation(venue["id"], guest["id"])
    add_ticket(big["id"], slot["id"], tier="GA")
    add_ticket(big["id"], slot["id"], tier="GA")
    confirm_reservation(big["id"], slot["id"])
    validate_success(api.pay_reservation(big["id"], BOX), 200)
    validate_success(api.cancel_reservation(big["id"], BOX), 200)
    g_after_refund = validate_success(api.get_guest(guest["id"], BOX), 200)
    assert g_after_refund["wallet_credit_cents"] == 4820

    # New single-ticket reservation total 2410, paid from wallet.
    new_res = create_reservation(venue["id"], guest["id"])
    add_ticket(new_res["id"], slot["id"], tier="GA")
    confirm_reservation(new_res["id"], slot["id"])
    paid = validate_success(api.pay_reservation(new_res["id"], BOX), 200)
    assert paid["payment_status"] == "PAID"

    g_final = validate_success(api.get_guest(guest["id"], BOX), 200)
    assert g_final["wallet_credit_cents"] == 2410, (
        f"wallet should drain 2410 of 4820, got {g_final['wallet_credit_cents']}"
    )


def test_slot_occupancy_conserved_across_confirm_then_cancel(api):
    """PRD 2.8: "confirmation raises reserved_count, admission shifts a member from
    reserved_count to admitted_count, and no-show or cancellation releases
    reserved_count". PRD 3.7: "If it was RESERVED, each ticket's slot has its
    reserved_count decremented".

    Confirming a 2-ticket reservation raises reserved_count to 2; cancelling that
    RESERVED reservation returns it to 0 (occupancy conserved to its pre-confirm value).

    Design: Difficulty/compensating_invariant/ci_slot_occupancy_conserved_confirm_then_cancel
    """
    venue, attraction, slot = setup_venue_attraction_slot(slot_overrides={"capacity": 10})
    guest = create_guest(full_name="Conserve Guest", email="cons@x.com")
    reservation = create_reservation(venue["id"], guest["id"])
    add_ticket(reservation["id"], slot["id"], tier="GA")
    add_ticket(reservation["id"], slot["id"], tier="GA")
    confirm_reservation(reservation["id"], slot["id"])

    mid = validate_success(api.get_time_slot(slot["id"], BOX), 200)
    assert mid["reserved_count"] == 2, "reserved_count should be 2 after confirm"

    validate_success(api.cancel_reservation(reservation["id"], BOX), 200)
    after = validate_success(api.get_time_slot(slot["id"], BOX), 200)
    assert after["reserved_count"] == 0
    assert after["reserved_count"] + after["admitted_count"] == 0


def test_confirm_raises_reserved_count_by_party_size(api):
    """PRD 3.6: "On success each slot's reserved_count is raised by that slot's new
    party members". PRD 2.8: "The reserved_count is the number of party members
    currently held by reservations in the RESERVED entry state against that slot".

    Confirming a 2-ticket reservation raises the slot's reserved_count to exactly 2 —
    the forward half of the conserved-occupancy invariant whose cancel half returns it
    to 0.

    Design: Difficulty/compensating_invariant/ci_slot_occupancy_conserved_confirm_then_cancel
    """
    venue, attraction, slot = setup_venue_attraction_slot(slot_overrides={"capacity": 10})
    assert slot["reserved_count"] == 0
    guest = create_guest(full_name="Occ Guest", email="occ@x.com")
    reservation = create_reservation(venue["id"], guest["id"])
    add_ticket(reservation["id"], slot["id"], tier="GA")
    add_ticket(reservation["id"], slot["id"], tier="GA")
    confirm_reservation(reservation["id"], slot["id"])

    after = validate_success(api.get_time_slot(slot["id"], BOX), 200)
    assert after["reserved_count"] == 2
    assert after["admitted_count"] == 0


def test_money_conserved_across_pay_then_refund(api):
    """PRD 3.7: "the cash charged is the total_cents less the applied amount." PRD 3.7:
    "A refund — whether from a guest's own cancellation or from a closure cascade —
    always credits the guest's wallet with the full total_cents that was charged;
    total cash charged plus wallet credit issued is conserved across the cancellation."

    Paying a total-2410 reservation with wallet 0 charges 2410 cash; cancelling
    refunds 2410 to the wallet, so wallet + outstanding cash returns to the pre-pay
    total 2410.

    Design: Difficulty/compensating_invariant/ci_money_conserved_pay_then_refund_wallet_plus_cash
    """
    venue, attraction, slot = setup_venue_attraction_slot()
    guest, reservation, ticket = create_paid_reservation(venue["id"], slot["id"])
    assert reservation["total_cents"] == 2410
    g_after_pay = validate_success(api.get_guest(guest["id"], BOX), 200)
    assert g_after_pay["wallet_credit_cents"] == 0  # cash charged 2410, wallet 0

    validate_success(api.cancel_reservation(reservation["id"], BOX), 200)
    refreshed_res = validate_success(api.get_reservation(reservation["id"], BOX), 200)
    assert refreshed_res["payment_status"] == "REFUNDED"
    g_after_refund = validate_success(api.get_guest(guest["id"], BOX), 200)
    # wallet 2410 + cash outstanding 0 == pre-pay total 2410.
    assert g_after_refund["wallet_credit_cents"] == 2410


def test_pay_with_zero_wallet_leaves_wallet_zero_money_conserved(api):
    """PRD 3.7: "The amount applied from the wallet is the smaller of the guest's
    wallet_credit_cents and the reservation's total_cents; that applied amount is
    subtracted from wallet_credit_cents, and the cash charged is the total_cents less
    the applied amount."

    Paying a total-2410 reservation with wallet 0 applies 0 from the wallet (charging
    2410 cash) and leaves the wallet at 0 — the pre-refund leg of the money-conservation
    invariant, before any credit is issued.

    Design: Difficulty/compensating_invariant/ci_money_conserved_pay_then_refund_wallet_plus_cash
    """
    venue, attraction, slot = setup_venue_attraction_slot()
    guest, reservation, ticket = create_reserved_reservation(venue["id"], slot["id"])
    assert reservation["total_cents"] == 2410
    g_before = validate_success(api.get_guest(guest["id"], BOX), 200)
    assert g_before["wallet_credit_cents"] == 0

    paid = validate_success(api.pay_reservation(reservation["id"], BOX), 200)
    assert paid["payment_status"] == "PAID"
    g_after = validate_success(api.get_guest(guest["id"], BOX), 200)
    assert g_after["wallet_credit_cents"] == 0


def test_mark_no_show_after_window_returns_slot_capacity(api):
    """PRD 3.7: "After a reservation's entry window has fully passed — when the
    logical clock is at or after the latest ticketed slot's window_end — a
    still-RESERVED reservation may be marked a no-show by box-office staff, moving it
    to the terminal NO_SHOW state. For each ticket the slot's reserved_count drops by
    one".

    A RESERVED reservation marked no-show after window_end moves to NO_SHOW and
    releases its reserved_count back to 0.

    Design: Corner/endpoints/mark_no_show_after_window_returns_reservation_no_show
    """
    set_clock("2026-10-31T18:30:00Z")
    venue, attraction, slot = setup_venue_attraction_slot()
    guest, reservation, ticket = create_reserved_reservation(venue["id"], slot["id"])
    set_clock("2026-10-31T20:00:00Z")

    no_show = validate_success(api.mark_no_show(reservation["id"], BOX), 200)
    assert no_show["entry_status"] == "NO_SHOW"
    after = validate_success(api.get_time_slot(slot["id"], BOX), 200)
    assert after["reserved_count"] == 0
