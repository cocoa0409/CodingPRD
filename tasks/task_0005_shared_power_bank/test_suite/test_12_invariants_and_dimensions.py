"""
Cross-entity invariants (PRD §2.4 / §3.7) and parallel-state-dimension tests
(PRD §3.4 / §3.5 / §3.6).
"""

from __future__ import annotations

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    advance_clock_to,
    api_client,
    assert_money_equal,
    borrow_for,
    create_cabinet,
    create_device,
    create_location_partner,
    heartbeat,
    make_user_headers,
    return_for,
    setup_borrow_environment,
    setup_funded_user,
    setup_pricing_plans,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Money invariant across rent → return → refund (PRD §3.7)
# ---------------------------------------------------------------------------


def test_refund_returns_wallet_to_pre_borrow_value(api):
    """PRD §3.7: "On a successful refund the rental's refund_amount is set
    equal to the prior Rental.charged_amount, the user's wallet_balance is
    increased by the refund amount."

    Invariant: a complete rent → return → refund cycle leaves wallet
    balance equal to its pre-borrow value (no other operations).
    """
    env = setup_borrow_environment()
    pre = validate_success(
        api.get_user(env["user"]["id"], make_user_headers(env["user"]["id"])), 200
    )
    rental = borrow_for(env["user"], env["cabinet"]["id"])
    advance_clock_to("2026-01-01T11:00:00Z")
    heartbeat(env["cabinet"]["id"], "2026-01-01T11:00:00Z")
    final = return_for(env["user"], rental["id"], env["cabinet"]["id"])
    post_return = validate_success(
        api.get_user(env["user"]["id"], make_user_headers(env["user"]["id"])), 200
    )
    assert_money_equal(
        post_return["wallet_balance"], pre["wallet_balance"] - final["charged_amount"]
    )
    refunded = validate_success(api.refund_rental(final["id"], ADMIN_HEADERS), 200)
    assert refunded["refund_amount"] == final["charged_amount"]
    post_refund = validate_success(
        api.get_user(env["user"]["id"], make_user_headers(env["user"]["id"])), 200
    )
    assert_money_equal(post_refund["wallet_balance"], pre["wallet_balance"])


def test_refund_increments_refund_count_30d(api):
    """PRD §3.7: "the user's refund_count_30d is incremented by one."
    """
    env = setup_borrow_environment()
    rental = borrow_for(env["user"], env["cabinet"]["id"])
    advance_clock_to("2026-01-01T11:00:00Z")
    heartbeat(env["cabinet"]["id"], "2026-01-01T11:00:00Z")
    return_for(env["user"], rental["id"], env["cabinet"]["id"])
    user_before = validate_success(
        api.get_user(env["user"]["id"], make_user_headers(env["user"]["id"])), 200
    )
    api.refund_rental(rental["id"], ADMIN_HEADERS)
    user_after = validate_success(
        api.get_user(env["user"]["id"], make_user_headers(env["user"]["id"])), 200
    )
    assert user_after["refund_count_30d"] == user_before["refund_count_30d"] + 1


# ---------------------------------------------------------------------------
# Parallel state dimensions (PRD §3.4 / §3.5 / §3.6 / §3.7)
# ---------------------------------------------------------------------------


def test_overdue_sweep_advances_only_rental_status_dimension(api):
    """PRD §3.6: "The transition from ACTIVE to OVERDUE is performed by the
    overdue sweep when the elapsed hours since rented_at ... are strictly
    greater than 24."

    PRD §3.4: rental is created with payment_status PENDING. PRD §2.7 priority
    5 uses both rental_status and payment_status as targets of state checks,
    confirming they are independent dimensions on the same row.

    After the overdue sweep: rental_status = OVERDUE, payment_status remains
    PENDING (it does not advance until BILLED via return).
    """
    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    advance_clock_to("2026-01-01T00:00:00Z")
    heartbeat(cabinet["id"], "2026-01-01T00:00:00Z")
    create_device(cabinet["id"], 0, battery_level=80)
    user = setup_funded_user()
    rental = borrow_for(user, cabinet["id"])
    assert rental["rental_status"] == "ACTIVE"
    assert rental["payment_status"] == "PENDING"
    advance_clock_to("2026-01-02T01:00:00Z")  # 25h
    heartbeat(cabinet["id"], "2026-01-02T01:00:00Z")
    api.run_sweep({"sweep_type": "overdue"})
    fetched = validate_success(
        api.get_rental(rental["id"], make_user_headers(user["id"])), 200
    )
    assert fetched["rental_status"] == "OVERDUE"
    assert fetched["payment_status"] == "PENDING"


def test_refund_advances_only_payment_status_dimension(api):
    """PRD §3.7: refund advances payment_status from BILLED to REFUNDED but
    leaves rental_status at RETURNED."""
    env = setup_borrow_environment()
    rental = borrow_for(env["user"], env["cabinet"]["id"])
    advance_clock_to("2026-01-01T11:00:00Z")
    heartbeat(env["cabinet"]["id"], "2026-01-01T11:00:00Z")
    final = return_for(env["user"], rental["id"], env["cabinet"]["id"])
    assert final["rental_status"] == "RETURNED"
    assert final["payment_status"] == "BILLED"
    refunded = validate_success(api.refund_rental(final["id"], ADMIN_HEADERS), 200)
    assert refunded["rental_status"] == "RETURNED"  # rental dimension unchanged
    assert refunded["payment_status"] == "REFUNDED"  # payment dimension advanced


# ---------------------------------------------------------------------------
# Refund only valid when payment_status == BILLED AND rental_status == RETURNED
# (PRD §3.7)
# ---------------------------------------------------------------------------


def test_refund_on_pending_payment_rejected(api):
    """PRD §3.7: "The refund capability is available only when the rental's
    payment_status is BILLED and rental_status is RETURNED; calling it
    against any other state pair is rejected with ERR_INVALID_STATE."
    """
    env = setup_borrow_environment()
    rental = borrow_for(env["user"], env["cabinet"]["id"])
    # rental is ACTIVE / PENDING — refund forbidden.
    res = api.refund_rental(rental["id"], ADMIN_HEADERS)
    validate_error(res, "ERR_INVALID_STATE")
