"""Transitive cascades (extension approve, trip cancel) and compensating invariants.

Difficulty rules transitive_cascade and compensating_invariant. Every secondary
effect of a state transition is part of the contract (PRD §2.8).
"""
from test_helpers import (
    validate_success, get_success_data,
    make_admin_headers,
    setup_requested_trip, setup_confirmed_trip, setup_requested_extension,
    get_booked_block,
)

ADMIN = make_admin_headers()


# ------------------------- Difficulty: extension approve depth-3 cascade
def test_extension_approve_reprices_trip(api):
    """PRD §3.7: "the trip's `end_date` becomes the extension's `new_end_date`,
    and the trip's `discounted_subtotal_cents`, `protection_premium_cents`,
    `estimated_total_cents`, and `estimated_host_earnings_cents` are recomputed
    with the same estimated-settlement math of §3.4 over the new, longer night
    count."
    PRD §3.7: "That `added_earnings_cents` is the difference between the host
    earnings implied by the re-priced longer trip ... and the trip's
    `estimated_host_earnings_cents` before the extension"

    Design: Difficulty/transitive_cascade/extension_approve_cascade_depth3
    """
    ctx = setup_requested_extension(api, new_end_date="2026-06-10")
    extension = get_success_data(api.approve_extension(ctx["extension"]["id"], ctx["host_headers"]))
    trip = get_success_data(api.get_trip(ctx["trip"]["id"], ctx["host_headers"]))
    assert trip["end_date"] == "2026-06-10"
    assert trip["estimated_host_earnings_cents"] == 64800
    assert extension["added_earnings_cents"] == 14400


def test_extension_approve_grows_block_vehicle_and_host(api):
    """PRD §3.7: "At level two the trip mutation drives the linked `BOOKED`
    block: its `end_date` becomes the `new_end_date` and its `nights` is
    recomputed. At level three the block's night growth drives both the vehicle
    and the host: the vehicle's `booked_night_count` increases by the
    `added_nights`, and the host's `pending_balance_cents` increases by the
    extension's `added_earnings_cents`."

    Design: Difficulty/transitive_cascade/extension_approve_cascade_depth3
    """
    ctx = setup_requested_extension(api, new_end_date="2026-06-10")
    api.approve_extension(ctx["extension"]["id"], ctx["host_headers"])
    vehicle = get_success_data(api.get_vehicle(ctx["vehicle"]["id"], ADMIN))
    host = get_success_data(api.get_host(ctx["host"]["id"], ADMIN))
    block = get_booked_block(api, ctx["trip"]["id"])
    assert vehicle["booked_night_count"] == 9
    assert host["pending_balance_cents"] == 64800
    assert block["end_date"] == "2026-06-10"
    assert block["nights"] == 9


# --------------------------- Difficulty: trip cancel depth-2 cascade
def test_cancel_confirmed_trip_releases_block(api):
    """PRD §3.5: "the trip releases its linked `BOOKED` block to `RELEASED`
    (level one), and that release both reduces the vehicle's `booked_night_count`
    by the trip's `nights` and — only if the trip was `CONFIRMED` at the moment
    of cancellation — reduces the host's `pending_balance_cents` by the trip's
    `estimated_host_earnings_cents` (level two)."

    Design: Difficulty/transitive_cascade/trip_cancel_cascade_depth2
    """
    ctx = setup_confirmed_trip(api)
    trip = get_success_data(api.cancel_trip(ctx["trip"]["id"], ctx["guest_headers"],
                                            {"reason": "guest change"}))
    assert trip["status"] == "CANCELLED"
    block = get_booked_block(api, ctx["trip"]["id"])
    assert block["status"] == "RELEASED"


def test_cancel_confirmed_trip_reverses_vehicle_and_host(api):
    """PRD §3.5: "the trip releases its linked `BOOKED` block to `RELEASED`
    (level one), and that release both reduces the vehicle's `booked_night_count`
    by the trip's `nights` and — only if the trip was `CONFIRMED` at the moment
    of cancellation — reduces the host's `pending_balance_cents` by the trip's
    `estimated_host_earnings_cents` (level two)."

    Design: Difficulty/transitive_cascade/trip_cancel_cascade_depth2
    """
    ctx = setup_confirmed_trip(api)
    api.cancel_trip(ctx["trip"]["id"], ctx["guest_headers"], {"reason": "guest change"})
    vehicle = get_success_data(api.get_vehicle(ctx["vehicle"]["id"], ADMIN))
    host = get_success_data(api.get_host(ctx["host"]["id"], ADMIN))
    assert vehicle["booked_night_count"] == 0
    assert host["pending_balance_cents"] == 0


# ---------------- Difficulty: host pending balance approve/cancel conservation
def test_host_pending_balance_returns_to_zero_after_approve_cancel(api):
    """PRD §2.8: "approving a trip credits that estimate and cancelling the same
    confirmed trip debits the identical amount, so an approve-then-cancel round
    trip returns the balance to its pre-approval value."

    Design: Difficulty/compensating_invariant/host_pending_balance_book_cancel_conserved
    """
    ctx = setup_confirmed_trip(api)
    api.cancel_trip(ctx["trip"]["id"], ctx["host_headers"], {"reason": "conservation check"})
    host = get_success_data(api.get_host(ctx["host"]["id"], ADMIN))
    assert host["pending_balance_cents"] == 0


def test_host_pending_balance_credited_on_approve(api):
    """PRD §3.5: "Approving it advances `REQUESTED → CONFIRMED` and credits the
    host's `pending_balance_cents` by the trip's `estimated_host_earnings_cents`."

    Design: Difficulty/compensating_invariant/host_pending_balance_book_cancel_conserved
    """
    ctx = setup_confirmed_trip(api)
    host = get_success_data(api.get_host(ctx["host"]["id"], ADMIN))
    assert host["pending_balance_cents"] == ctx["trip"]["estimated_host_earnings_cents"] == 50400


# --------------- Difficulty: vehicle booked-nights book/cancel conservation
def test_vehicle_booked_nights_returns_to_zero_after_book_cancel(api):
    """PRD §2.8: "a booking adds its nights and a cancellation releases the
    block out of the sum, so a book-then-cancel round trip returns the count to
    its pre-booking value."

    Design: Difficulty/compensating_invariant/vehicle_booked_nights_book_cancel_conserved
    """
    ctx = setup_requested_trip(api)
    api.cancel_trip(ctx["trip"]["id"], ctx["guest_headers"], {"reason": "calendar conservation"})
    vehicle = get_success_data(api.get_vehicle(ctx["vehicle"]["id"], ADMIN))
    assert vehicle["booked_night_count"] == 0
    block = get_booked_block(api, ctx["trip"]["id"])
    assert block["status"] == "RELEASED"


def test_vehicle_booked_nights_incremented_on_booking(api):
    """PRD §3.4: "the vehicle's `booked_night_count` increases by the trip's
    `nights`"

    Design: Difficulty/compensating_invariant/vehicle_booked_nights_book_cancel_conserved
    """
    ctx = setup_requested_trip(api)
    vehicle = get_success_data(api.get_vehicle(ctx["vehicle"]["id"], ADMIN))
    assert vehicle["booked_night_count"] == 7
