"""Stay lifecycle: cancellation conservation invariants and terminal/idempotency
state guards.
"""
from test_helpers import (
    validate_success, validate_error,
    make_admin_headers,
    build_points_scenario, get_member,
    make_member_headers,
)

ADMIN = make_admin_headers()


# ── Difficulty 9a: cancel conserves total posted points ──────────────────────
def test_cancel_full_refund_sets_refund_points(api):
    """PRD §3.6: "seven or more days before check-in refunds the full points cost".
    PRD §3.6: "The refund fraction is applied to the agreement's `points_cost` and
    rounded half up."

    Design: Difficulty/compensating_invariant/cancel_conserves_total_posted_points
    """
    sc = build_points_scenario("confirmed", points_per_night=100, guest_tier="PLUS",
                               host_tier="PLUS", confirm_as="guest")
    agreement = sc["agreement"]   # clock still 2026-07-01, check_in 2026-07-10 -> 9 days out
    res = api.cancel_agreement(agreement["id"], make_member_headers(sc["guest"]["id"]))
    cancelled = validate_success(res, 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["refund_points"] == 270


def test_cancel_conserves_total_posted_points(api):
    """PRD §3.6: "the system then posts an `EXCHANGE_REFUND` of the positive refund
    to the guest and a `CREDIT_REVERSAL` of the equal negative amount from the host —
    the host retains the difference between the original cost and the refund as
    compensation — and recomputes both members' balances. Because the original debit,
    credit, refund, and reversal sum to zero, points remain conserved across the
    cancellation."

    Design: Difficulty/compensating_invariant/cancel_conserves_total_posted_points
    """
    sc = build_points_scenario("confirmed", points_per_night=100, guest_tier="PLUS",
                               host_tier="PLUS", confirm_as="guest")
    api.cancel_agreement(sc["agreement"]["id"], make_member_headers(sc["guest"]["id"]))
    gm = get_member(sc["guest"]["id"])
    hm = get_member(sc["host"]["id"])
    # Full refund: guest and host both return to their welcome-bonus balances.
    assert gm["settled_points_balance"] == 1000
    assert hm["settled_points_balance"] == 1000


# ── Difficulty 9b: cancel conserves listing availability nights ──────────────
def test_cancel_releases_booked_window(api):
    """PRD §3.6: "Cancelling releases the booked window `BOOKED → OPEN`, restoring
    the listing's open nights."

    Design: Difficulty/compensating_invariant/cancel_conserves_listing_availability_nights
    """
    sc = build_points_scenario("pending", points_per_night=100, guest_tier="PLUS", host_tier="PLUS")
    api.cancel_agreement(sc["agreement"]["id"], make_member_headers(sc["guest"]["id"]))
    window = validate_success(api.get_availability_window(sc["window"]["id"], ADMIN), 200)
    assert window["status"] == "OPEN"


def test_cancel_preserves_window_nights(api):
    """PRD §3.2: "The window's `nights` is the number of days in that half-open span
    and must be at least 1".
    PRD §3.6: "Cancelling releases the booked window `BOOKED → OPEN`, restoring the
    listing's open nights."

    Design: Difficulty/compensating_invariant/cancel_conserves_listing_availability_nights
    """
    sc = build_points_scenario("pending", points_per_night=100, guest_tier="PLUS", host_tier="PLUS")
    api.cancel_agreement(sc["agreement"]["id"], make_member_headers(sc["guest"]["id"]))
    window = validate_success(api.get_availability_window(sc["window"]["id"], ADMIN), 200)
    assert window["nights"] == 2


# ── Corner: idempotency / terminal-state guards ──────────────────────────────
def test_confirm_twice_returns_invalid_state(api):
    """PRD §3.6: "Either party — guest or host — confirms a `PENDING_CONFIRMATION`
    agreement, moving it `PENDING_CONFIRMATION → CONFIRMED`."
    PRD §2.9: "State admissibility comes sixth, giving `ERR_INVALID_STATE` when a
    resource is not in a state that admits the requested transition."

    Design: Corner/state_machines/confirm_twice_returns_invalid_state
    """
    sc = build_points_scenario("confirmed", points_per_night=100, guest_tier="PLUS",
                               host_tier="PLUS", confirm_as="guest")
    res = api.confirm_agreement(sc["agreement"]["id"], make_member_headers(sc["guest"]["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_cancel_completed_agreement_returns_invalid_state(api):
    """PRD §3.6: "Cancellation is available only from `PENDING_CONFIRMATION` or
    `CONFIRMED` — never once a stay is `IN_PROGRESS` or `COMPLETED`".
    PRD §2.9: "State admissibility comes sixth, giving `ERR_INVALID_STATE` when a
    resource is not in a state that admits the requested transition."

    Design: Corner/state_machines/cancel_completed_agreement_returns_invalid_state
    """
    sc = build_points_scenario("completed", points_per_night=100, guest_tier="PLUS",
                               host_tier="PLUS", confirm_as="guest", complete_as="guest")
    res = api.cancel_agreement(sc["agreement"]["id"], make_member_headers(sc["guest"]["id"]))
    validate_error(res, "ERR_INVALID_STATE")
