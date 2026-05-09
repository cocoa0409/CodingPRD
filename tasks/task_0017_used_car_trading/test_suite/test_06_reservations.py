"""Tests for PRD §3.4 — Reservations on FIXED_PRICE listings: 5%-rounded-up
deposit, FIFO queue, HOLDING window, expiry promotion, cancellation.
"""

import math
from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    advance_clock_payload,
    api_client,
    assert_reservation,
    create_reservation,
    make_buyer_headers,
    register_buyer,
    setup_active_listing,
    setup_holding_reservation,
    validate_error,
    validate_success,
)


# ──────────────────────────────────────────────────────────
# §3.4 Reservation creation: deposit, queue position
# ──────────────────────────────────────────────────────────


def test_first_reservation_becomes_holding_with_deposit_five_percent_rounded_up(api):
    """PRD §3.4: "the system computes the deposit_cents for every reservation
    on that listing as five percent of the listing's ask_price_cents rounded
    up to the next whole cent."
    PRD §3.4: "Promotion to position 1 (either at creation when the queue is
    empty ... ) advances the reservation from QUEUED to HOLDING."

    Setup: ask=2_000_001 → deposit = ceil(100_000.05) = 100_001.
    """
    seller, vehicle, _, listing = setup_active_listing(
        sale_mode="FIXED_PRICE", ask_price_cents=2_000_001
    )
    buyer = register_buyer()
    reservation = create_reservation(buyer, listing)
    assert_reservation(reservation)
    assert reservation["status"] == "HOLDING"
    assert reservation["queue_position"] == 1
    assert reservation["deposit_cents"] == math.ceil(2_000_001 * 0.05)


def test_first_reservation_advances_listing_to_reserved(api, admin_headers):
    """PRD §3.4: "if the listing was in ACTIVE — advances the listing from
    ACTIVE to RESERVED."
    """
    seller, vehicle, listing, buyer, reservation = setup_holding_reservation()
    refreshed = validate_success(api.get_listing(listing["id"], admin_headers), 200)
    assert refreshed["status"] == "RESERVED"
    assert refreshed["reservation_buyer_id"] == buyer["id"]


def test_first_reservation_acquires_buyer_deposit_hold(api):
    """PRD §3.4: "acquires the buyer's deposit hold
    (Buyer.deposit_held_cents increases by the reservation's deposit_cents)"."""
    seller, vehicle, listing, buyer, reservation = setup_holding_reservation(
        ask_price_cents=2_000_000
    )
    refreshed = validate_success(api.get_buyer(buyer["id"], make_buyer_headers(buyer["id"])), 200)
    assert refreshed["deposit_held_cents"] == reservation["deposit_cents"]
    assert refreshed["deposit_balance_cents"] == refreshed["deposit_held_cents"]


def test_second_reservation_is_queued_at_position_two(api):
    """PRD §3.4: "Reservations are placed at the next available queue_position,
    which is the count of non-terminal reservations on the listing plus one.
    Reservations enter in status QUEUED, with hold_expires_at null while they
    are at any position other than 1."
    """
    seller, vehicle, listing, buyer_a, _ = setup_holding_reservation()
    buyer_b = register_buyer()
    res = api.create_reservation(listing["id"], make_buyer_headers(buyer_b["id"]))
    second = validate_success(res, 201)
    assert second["status"] == "QUEUED"
    assert second["queue_position"] == 2
    assert second.get("hold_expires_at") is None


def test_queued_reservation_holds_no_deposit(api):
    """PRD §3.4: "with hold_expires_at null while they are at any position
    other than 1." Combined with PRD §3.4: deposit acquisition fires only on
    promotion to HOLDING (step "Promotion to position 1 ... acquires the
    buyer's deposit hold"). A buyer at queue_position 2 must hold zero.
    """
    seller, vehicle, listing, buyer_a, _ = setup_holding_reservation()
    buyer_b = register_buyer()
    api.create_reservation(listing["id"], make_buyer_headers(buyer_b["id"]))
    refreshed = validate_success(
        api.get_buyer(buyer_b["id"], make_buyer_headers(buyer_b["id"])), 200
    )
    assert refreshed["deposit_held_cents"] == 0


# ──────────────────────────────────────────────────────────
# §3.4 Listing reservability
# ──────────────────────────────────────────────────────────


def test_reservation_on_draft_listing_rejected(api):
    """PRD §3.4: "Reservations cannot be created when the listing's status is
    anything other than ACTIVE or RESERVED; otherwise the creation is
    rejected with ERR_LISTING_NOT_RESERVABLE."

    Build a listing in DRAFT state — reservation must fail.
    """
    from test_helpers import (
        create_draft_listing,
        setup_finalized_assessment,
    )

    seller, vehicle, assessment = setup_finalized_assessment()
    listing = create_draft_listing(seller, vehicle, assessment, sale_mode="FIXED_PRICE")
    buyer = register_buyer()
    res = api.create_reservation(listing["id"], make_buyer_headers(buyer["id"]))
    validate_error(res, "ERR_LISTING_NOT_RESERVABLE")


# ──────────────────────────────────────────────────────────
# §3.4 Cancellation
# ──────────────────────────────────────────────────────────


def test_cancel_holding_reservation_releases_deposit_and_reactivates_listing(api, admin_headers):
    """PRD §3.4: "Cancelling a HOLDING reservation transitions HOLDING to
    CANCELLED, releases the deposit, and either promotes the next-position
    reservation (advancing the next QUEUED to HOLDING) or — if none exists —
    restores the listing from RESERVED back to ACTIVE."
    """
    seller, vehicle, listing, buyer, reservation = setup_holding_reservation()
    cancelled = validate_success(
        api.cancel_reservation(reservation["id"], make_buyer_headers(buyer["id"])), 200
    )
    assert cancelled["status"] == "CANCELLED"
    refreshed_buyer = validate_success(
        api.get_buyer(buyer["id"], make_buyer_headers(buyer["id"])), 200
    )
    assert refreshed_buyer["deposit_held_cents"] == 0
    refreshed_listing = validate_success(api.get_listing(listing["id"], admin_headers), 200)
    assert refreshed_listing["status"] == "ACTIVE"


def test_cancel_queued_reservation_no_deposit_movement(api):
    """PRD §3.4: "Cancelling a QUEUED reservation transitions QUEUED to
    CANCELLED with no deposit movement (none was held)."
    """
    seller, vehicle, listing, buyer_a, _ = setup_holding_reservation()
    buyer_b = register_buyer()
    queued = validate_success(
        api.create_reservation(listing["id"], make_buyer_headers(buyer_b["id"])), 201
    )
    cancelled = validate_success(
        api.cancel_reservation(queued["id"], make_buyer_headers(buyer_b["id"])), 200
    )
    assert cancelled["status"] == "CANCELLED"
    refreshed_buyer = validate_success(
        api.get_buyer(buyer_b["id"], make_buyer_headers(buyer_b["id"])), 200
    )
    assert refreshed_buyer["deposit_held_cents"] == 0


# ──────────────────────────────────────────────────────────
# §3.4 Expiry promotion via clock advance
# ──────────────────────────────────────────────────────────


def test_holding_reservation_expires_after_clock_advance_past_hold_expires_at(api, admin_headers):
    """PRD §3.4: "If the holder does not pay before hold_expires_at, a clock
    advance past that instant moves the reservation from HOLDING to EXPIRED.
    The deposit is released."
    """
    seller, vehicle, listing, buyer, reservation = setup_holding_reservation()
    hold_expires = reservation.get("hold_expires_at")
    assert hold_expires is not None, (
        "PRD §3.4: hold_expires_at must be set when reservation is HOLDING"
    )
    # Parse hold_expires_at (server-clock-relative) and advance one day past it.
    hold_dt = datetime.fromisoformat(hold_expires.replace("Z", "+00:00"))
    far_future = hold_dt + timedelta(days=1)
    api.advance_clock(
        advance_clock_payload(far_future.strftime("%Y-%m-%dT%H:%M:%S.000Z")),
        admin_headers,
    )
    refreshed_buyer = validate_success(
        api.get_buyer(buyer["id"], make_buyer_headers(buyer["id"])), 200
    )
    # Deposit released.
    assert refreshed_buyer["deposit_held_cents"] == 0
    # Listing returns to ACTIVE since no successor reservation exists.
    listing_after = validate_success(api.get_listing(listing["id"], admin_headers), 200)
    assert listing_after["status"] == "ACTIVE"


def test_holding_expiry_promotes_next_queued_reservation(api, admin_headers):
    """PRD §3.4: "If a next-position reservation exists on the same listing,
    that next reservation is promoted from QUEUED to HOLDING."
    """
    seller, vehicle, listing, buyer_a, reservation_a = setup_holding_reservation()
    buyer_b = register_buyer()
    queued_b = validate_success(
        api.create_reservation(listing["id"], make_buyer_headers(buyer_b["id"])), 201
    )
    assert queued_b["status"] == "QUEUED"

    # Advance clock past A's hold window (hold_expires_at is server-clock-relative).
    hold_dt = datetime.fromisoformat(reservation_a["hold_expires_at"].replace("Z", "+00:00"))
    far_future = hold_dt + timedelta(days=1)
    api.advance_clock(
        advance_clock_payload(far_future.strftime("%Y-%m-%dT%H:%M:%S.000Z")),
        admin_headers,
    )

    # B should now hold; deposit acquired.
    b_after = validate_success(api.get_buyer(buyer_b["id"], make_buyer_headers(buyer_b["id"])), 200)
    assert b_after["deposit_held_cents"] == queued_b["deposit_cents"]
    listing_after = validate_success(api.get_listing(listing["id"], admin_headers), 200)
    assert listing_after["status"] == "RESERVED"
    assert listing_after["reservation_buyer_id"] == buyer_b["id"]
