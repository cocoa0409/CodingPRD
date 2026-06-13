"""Cancellation: penalty tiers, cash-vs-FCC settlement, cascades, conservation.

Covers the CASH/FCC divergence on a CONFIRMED booking, the 90-day tier boundary,
the depth-3 group-booking cancel cascade, the depth-2 sailing-cancel cascade,
cabin-inventory conservation, and money conservation with a minted REFUND.
"""
from test_helpers import (
    validate_success, get_success_data,
    TEST_USERS,
    make_guest_user_headers,
    create_confirmed_booking, create_deposit_held_booking, get_booking,
    setup_held_group_block,
    set_clock,
    assert_cabin_conservation,
)

RM = TEST_USERS["revenue_manager_headers"]


# ===========================================================================
# Difficulty: dual-variant cancellation (CASH vs FCC) on a CONFIRMED booking
# ===========================================================================
def test_cash_cancel_confirmed_booking_refund(api):
    """PRD 3.8: "Under the `CASH` variant, an administrative fee of 5000 cents
    applies only when the penalty fraction is exactly 0.00 (the no-penalty tier) and
    is otherwise zero; the `cancel_refund_cents` is the booking's `amount_paid_cents`
    minus the base penalty minus that admin fee, floored at 0, and `fcc_credit_cents`
    stays 0."

    Design: Difficulty/dual_variant_calc/cancellation_cash_vs_fcc_diverges_on_booking
    """
    set_clock("2026-06-18T16:00:00Z")  # 75 days before embark -> 25% tier
    sailing, category, confirmed = create_confirmed_booking(
        "guest-1", num_guests=3, num_cabins=2,
    )
    resp = api.cancel_booking(confirmed["id"], "CASH", make_guest_user_headers("guest-1"))
    data = validate_success(resp)
    assert data["status"] == "CANCELLED"
    assert data["cancellation_mode"] == "CASH"
    assert data["cancel_refund_cents"] == 275705
    assert data["fcc_credit_cents"] == 0


def test_fcc_cancel_confirmed_booking_credit_diverges(api):
    """PRD 3.8: "Under the `FCC` variant, no admin fee ever applies; the FCC penalty
    is the base penalty multiplied by the FCC penalty factor of 0.50, rounded
    half-up to whole cents — that is, only half the cash-tier penalty is charged —
    and `fcc_credit_cents` is `amount_paid_cents` minus that halved penalty, floored
    at 0, while `cancel_refund_cents` stays 0."

    Design: Difficulty/dual_variant_calc/cancellation_cash_vs_fcc_diverges_on_booking
    """
    set_clock("2026-06-18T16:00:00Z")  # 75 days before embark -> 25% tier
    sailing, category, confirmed = create_confirmed_booking(
        "guest-1b", num_guests=3, num_cabins=2,
    )
    resp = api.cancel_booking(confirmed["id"], "FCC", make_guest_user_headers("guest-1b"))
    data = validate_success(resp)
    assert data["status"] == "CANCELLED"
    assert data["cancellation_mode"] == "FCC"
    assert data["fcc_credit_cents"] == 321656
    assert data["cancel_refund_cents"] == 0


# ===========================================================================
# Difficulty: cancellation tier boundary at 90 days
# ===========================================================================
def test_cancel_at_90_days_inclusive_zero_penalty_tier(api):
    """PRD 3.8: "When that day count is 90 or more, the penalty fraction is 0.00".
    PRD 3.8: "an administrative fee of 5000 cents applies only when the penalty
    fraction is exactly 0.00 (the no-penalty tier) ... the `cancel_refund_cents` is
    the booking's `amount_paid_cents` minus the base penalty minus that admin fee,
    floored at 0".

    Design: Difficulty/boundary_precision_check/cancellation_tier_boundary_90_days_inclusive
    """
    set_clock("2026-06-03T16:00:00Z")  # exactly 90 days before embark
    sailing, category, confirmed = create_confirmed_booking(
        "guest-10", num_guests=2, num_cabins=2,
    )
    resp = api.cancel_booking(confirmed["id"], "CASH", make_guest_user_headers("guest-10"))
    data = validate_success(resp)
    assert data["cancel_refund_cents"] == 280178  # 285178 - 0 - 5000 admin


def test_cancel_at_89_days_applies_25_percent_tier(api):
    """PRD 3.8: "when it is at least 60 but fewer than 90, the fraction is 0.25". PRD
    3.8: "The base penalty amount is `booking_total_cents` multiplied by that
    fraction, rounded half-up to whole cents."

    Design: Difficulty/boundary_precision_check/cancellation_tier_boundary_90_days_inclusive
    """
    set_clock("2026-06-04T16:00:00Z")  # 89 days before embark -> 25% tier
    sailing, category, confirmed = create_confirmed_booking(
        "guest-10b", num_guests=2, num_cabins=2,
    )
    resp = api.cancel_booking(confirmed["id"], "CASH", make_guest_user_headers("guest-10b"))
    data = validate_success(resp)
    # booking_total 285178; penalty half_up(285178*0.25)=71295 (.5 rounds up);
    # no admin fee outside the 0% tier -> 285178-71295 = 213883.
    assert data["cancel_refund_cents"] == 213883


# ===========================================================================
# Difficulty: transitive cascades
# ===========================================================================
def test_cancel_group_booking_depth3_cascade(api):
    """PRD 3.8: "The cabin-release cascade has three levels. The booking's held or
    assigned cabin is released ... which in turn restores the category's
    `available_cabins` or `blocked_cabins` ... which in turn, for a group draw,
    decrements the owning block's `materialized_count`, relaxing a
    `PARTIALLY_MATERIALIZED` block back toward held semantics."

    Design: Difficulty/transitive_cascade/cancel_group_booking_depth3_cabin_category_block
    """
    sailing, category, _cabins, block = setup_held_group_block(num_cabins=4, block_size=2)
    s2, c2, held = create_deposit_held_booking(
        "guest-6", num_guests=2, sailing=sailing, category=category,
        group_block_id=block["id"], deposit_cents=75000,
    )
    resp = api.cancel_booking(held["id"], "FCC", make_guest_user_headers("guest-6"))
    data = validate_success(resp)
    assert data["status"] == "CANCELLED"
    cat = get_success_data(api.get_cabin_category(category["id"], RM))
    assert cat["blocked_cabins"] == 2
    assert cat["held_cabins"] == 0
    blk = get_success_data(api.get_group_block(block["id"], RM))
    assert blk["materialized_count"] == 0


def test_cancel_group_booking_releases_cabin_to_blocked(api):
    """PRD 3.8: "The booking's held or assigned cabin is released — a `HELD` or
    `ASSIGNED` cabin returns to `AVAILABLE` for an individual draw or to `BLOCKED`
    for a group draw — which in turn restores the category's `available_cabins` or
    `blocked_cabins`".

    Design: Difficulty/transitive_cascade/cancel_group_booking_depth3_cabin_category_block
    """
    sailing, category, _cabins, block = setup_held_group_block(num_cabins=4, block_size=2)
    s2, c2, held = create_deposit_held_booking(
        "guest-6b", num_guests=2, sailing=sailing, category=category,
        group_block_id=block["id"], deposit_cents=75000,
    )
    held_cabin_id = held["cabin_id"]
    assert held_cabin_id is not None
    cancelled = validate_success(
        api.cancel_booking(held["id"], "FCC", make_guest_user_headers("guest-6b"))
    )
    assert cancelled["cabin_id"] is None
    # The released cabin returns to BLOCKED (group draw), not AVAILABLE.
    cabin = get_success_data(api.get_cabin(held_cabin_id, RM))
    assert cabin["status"] == "BLOCKED"
    assert cabin["group_block_id"] == block["id"]
    assert cabin["booking_id"] is None


def test_cancel_sailing_depth2_cascade_to_bookings(api):
    """PRD 3.1: "From `OPEN` or `CLOSED`, cancellation is a goodwill cascade: every
    non-terminal booking on the sailing ... is moved to `CANCELLED` with its
    `cancellation_mode` recorded as `FCC` and a full-value future cruise credit
    minted, with no penalty applied because the line, not the guest, cancelled. That
    booking-level cancellation in turn releases the booking's held or assigned cabin
    and voids the booking's folio".

    Design: Difficulty/transitive_cascade/cancel_sailing_depth2_bookings_then_folios
    """
    set_clock("2026-06-18T16:00:00Z")
    sailing, category, confirmed = create_confirmed_booking(
        "guest-7", num_guests=2, num_cabins=2,
    )
    get_success_data(api.cancel_sailing(sailing["id"], RM))
    booking = get_booking(confirmed["id"])
    assert booking["status"] == "CANCELLED"
    assert booking["cancellation_mode"] == "FCC"
    assert booking["fcc_credit_cents"] == 285178  # full-value, no penalty
    cat = get_success_data(api.get_cabin_category(category["id"], RM))
    assert cat["available_cabins"] == 2


def test_cancel_sailing_marks_sailing_cancelled(api):
    """PRD 3.1: "A `RevenueManager` may cancel a sailing. ... From `OPEN` or
    `CLOSED`, cancellation is a goodwill cascade: every non-terminal booking on the
    sailing ... is moved to `CANCELLED` with its `cancellation_mode` recorded as
    `FCC` and a full-value future cruise credit minted".

    Design: Difficulty/transitive_cascade/cancel_sailing_depth2_bookings_then_folios
    """
    set_clock("2026-06-18T16:00:00Z")
    sailing, category, confirmed = create_confirmed_booking(
        "guest-7b", num_guests=2, num_cabins=2,
    )
    data = validate_success(api.cancel_sailing(sailing["id"], RM))
    assert data["status"] == "CANCELLED"


# ===========================================================================
# Difficulty: compensating invariants (conservation)
# ===========================================================================
def test_cabin_inventory_conserved_book_then_cancel(api):
    """PRD 2.6: "Cabin-count fields on a `CabinCategory` (`total_cabins`,
    `available_cabins`, `held_cabins`, `assigned_cabins`, `blocked_cabins`) ... are
    derived from the cabins beneath them and are kept consistent whenever a cabin's
    `status` changes."

    Design: Difficulty/compensating_invariant/cabin_inventory_conservation_book_then_cancel
    """
    sailing, category, held = create_deposit_held_booking(
        "guest-15", num_guests=2, num_cabins=2, deposit_cents=50000,
    )
    get_success_data(api.cancel_booking(held["id"], "FCC", make_guest_user_headers("guest-15")))
    cat = get_success_data(api.get_cabin_category(category["id"], RM))
    assert cat["available_cabins"] == 2
    assert cat["held_cabins"] == 0
    assert cat["assigned_cabins"] == 0
    assert cat["blocked_cabins"] == 0
    assert_cabin_conservation(cat)


def test_cabin_conservation_holds_while_deposit_held(api):
    """PRD 2.6: "Cabin-count fields on a `CabinCategory` ... are derived from the
    cabins beneath them and are kept consistent whenever a cabin's `status`
    changes."

    Design: Difficulty/compensating_invariant/cabin_inventory_conservation_book_then_cancel
    """
    sailing, category, held = create_deposit_held_booking(
        "guest-15b", num_guests=2, num_cabins=2, deposit_cents=50000,
    )
    cat = get_success_data(api.get_cabin_category(category["id"], RM))
    assert cat["total_cabins"] == 2
    assert cat["held_cabins"] == 1
    assert cat["available_cabins"] == 1
    assert_cabin_conservation(cat)


def test_cash_cancel_mints_refund_payment_money_conserved(api):
    """PRD 3.8: "A cash settlement mints a `REFUND` payment for the refunded amount."
    PRD 3.5: "A refund decreases the booking's `amount_paid_cents` by the refunded
    `amount_cents`."

    Design: Difficulty/compensating_invariant/money_conservation_cash_cancel_mints_refund_payment
    """
    set_clock("2026-06-03T16:00:00Z")  # 90 days -> 0% tier, admin fee applies
    sailing, category, held = create_deposit_held_booking(
        "guest-16", num_guests=2, num_cabins=2, deposit_cents=50000,
    )
    resp = api.cancel_booking(held["id"], "CASH", make_guest_user_headers("guest-16"))
    data = validate_success(resp)
    assert data["cancel_refund_cents"] == 45000   # 50000 - 0 penalty - 5000 admin
    assert data["amount_paid_cents"] == 5000      # 50000 - 45000 refunded


def test_cash_cancel_refund_payment_exists_in_refunded(api):
    """PRD 3.8: "A cash settlement mints a `REFUND` payment for the refunded amount."
    PRD 3.5: "A payment moves through `PENDING`, `CAPTURED`, `FAILED`, and
    `REFUNDED`."

    Design: Difficulty/compensating_invariant/money_conservation_cash_cancel_mints_refund_payment
    """
    set_clock("2026-06-03T16:00:00Z")
    sailing, category, held = create_deposit_held_booking(
        "guest-16b", num_guests=2, num_cabins=2, deposit_cents=50000,
    )
    get_success_data(api.cancel_booking(held["id"], "CASH", make_guest_user_headers("guest-16b")))
    payments = get_success_data(api.list_payments(RM, params={"booking_id": held["id"]}))
    if isinstance(payments, dict):
        payments = payments.get("data", payments)
    refunds = [p for p in payments if p["kind"] == "REFUND"]
    assert any(p["amount_cents"] == 45000 and p["status"] == "REFUNDED" for p in refunds), \
        f"expected a REFUNDED REFUND payment of 45000, got {refunds}"
