"""Cancellation: the two compensating legs (booked-nights release and the
tiered money refund), the full / half / zero refund tiers, and the long-term
non-refundable rule.

Covers difficulty queue compensating_invariant and corner
calculations / long_term_stay_class_makes_deposit_nonrefundable.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_paginated,
    make_guest_headers,
    make_operator_headers,
    setup_base_scenario,
    create_reservation,
    create_confirmed_reservation,
    get_site,
    get_reservation,
)

OP = make_operator_headers()


def _refunds(api, reservation_id):
    payments, _ = validate_paginated(api.list_payments(reservation_id, OP))
    return [p for p in payments if p["type"] == "REFUND"]


# ===========================================================================
# Difficulty: compensating_invariant / cancel_restores_site_booked_nights
# ===========================================================================
def test_cancel_releases_booked_nights_back_to_zero(api):
    """PRD §3.8: "The booked-nights leg releases the locked window: the site's
    `booked_night_count` drops by the reservation's `nights` (in practice via
    the same recompute that excludes cancelled reservations) and the site's
    `version` is bumped."

    Design: Difficulty/compensating_invariant/cancel_restores_site_booked_nights
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", site_overrides={"max_length_of_stay_nights": 30})
    res = create_reservation(site, guest, "2026-08-01", "2026-08-11")  # +10 nights
    assert get_site(site["id"])["booked_night_count"] == 10
    cancelled = validate_success(
        api.cancel_reservation(res["id"], make_guest_headers(guest["id"])),
        expected_status=200)
    assert cancelled["reservation_status"] == "CANCELLED"
    assert get_site(site["id"])["booked_night_count"] == 0


def test_cancelled_reservation_excluded_from_booked_nights(api):
    """PRD §3.5: "the site's `booked_night_count` is recomputed as the sum of
    `nights` across the reservations on that site whose `reservation_status` is
    `REQUESTED`, `CONFIRMED`, or `CHECKED_IN`; cancelled and checked-out
    reservations are excluded, and the count is an integer that is never negative."

    Design: Difficulty/compensating_invariant/cancel_restores_site_booked_nights
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", site_overrides={"max_length_of_stay_nights": 30})
    res = create_reservation(site, guest, "2026-08-01", "2026-08-11")
    api.cancel_reservation(res["id"], make_guest_headers(guest["id"]))
    # A surviving live reservation contributes; the cancelled one does not.
    create_reservation(site, guest, "2026-09-01", "2026-09-04")  # +3 nights
    assert get_site(site["id"])["booked_night_count"] == 3


# ===========================================================================
# Difficulty: compensating_invariant / cancel_refund_conserves_net_money_ledger
# ===========================================================================
def test_full_refund_zeroes_net_amount_paid(api):
    """PRD §3.8: "if `days_before` is at least the policy's `full_refund_min_days`,
    the refund is the full `amount_paid_cents` (100 percent)"
    PRD §3.7: "`amount_paid_cents` is the sum of `DEPOSIT` and `BALANCE` payment
    amounts minus the `REFUND` amounts on the reservation"

    Design: Difficulty/compensating_invariant/cancel_refund_conserves_net_money_ledger
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", site_overrides={"max_length_of_stay_nights": 30})
    # clock 07-01, check_in 08-01 -> 31 days before -> full refund (>=14).
    confirmed = create_confirmed_reservation(site, guest, "2026-08-01", "2026-08-11")
    cancelled = validate_success(
        api.cancel_reservation(confirmed["id"], make_guest_headers(guest["id"])),
        expected_status=200)
    assert cancelled["reservation_status"] == "CANCELLED"
    assert cancelled["payment_status"] == "REFUNDED"
    assert cancelled["amount_paid_cents"] == 0


def test_full_refund_creates_refund_payment_for_deposit(api):
    """PRD §3.8: "When the computed refund is greater than 0, the system creates
    a `REFUND` payment for that amount and sets `payment_status` to `REFUNDED`."

    Design: Difficulty/compensating_invariant/cancel_refund_conserves_net_money_ledger
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z", site_overrides={"max_length_of_stay_nights": 30})
    confirmed = create_confirmed_reservation(site, guest, "2026-08-01", "2026-08-11")
    deposit = confirmed["deposit_due_cents"]
    api.cancel_reservation(confirmed["id"], make_guest_headers(guest["id"]))
    refunds = _refunds(api, confirmed["id"])
    assert len(refunds) == 1
    # 100% of the 14580 deposit.
    assert refunds[0]["amount_cents"] == deposit == 14580


# ===========================================================================
# Corner: calculations / long_term_stay_class_makes_deposit_nonrefundable
# ===========================================================================
def test_long_term_stay_deposit_nonrefundable_on_cancel(api):
    """PRD §3.8: "If the reservation's `stay_class` is `LONG_TERM`, the refund is
    0 — long-term deposits are non-refundable."
    PRD §3.5: "it is `LONG_TERM` precisely when `nights` is at least the park's
    `long_stay_nights_threshold`, and `SHORT_TERM` otherwise."

    Design: Corner/calculations/long_term_stay_class_makes_deposit_nonrefundable
    """
    park, rate_plan, site, guest = setup_base_scenario(
        clock="2026-07-01T12:00:00Z",
        park_overrides={"long_stay_nights_threshold": 28},
        site_overrides={"max_length_of_stay_nights": 40})
    # 28 nights (08-01..08-29) >= threshold 28 -> LONG_TERM.
    confirmed = create_confirmed_reservation(site, guest, "2026-08-01", "2026-08-29")
    assert confirmed["stay_class"] == "LONG_TERM"
    cancelled = validate_success(
        api.cancel_reservation(confirmed["id"], make_guest_headers(guest["id"])),
        expected_status=200)
    assert cancelled["reservation_status"] == "CANCELLED"
    # No refund issued: deposit non-refundable, so payment_status stays DEPOSIT_PAID.
    assert cancelled["payment_status"] == "DEPOSIT_PAID"
    assert len(_refunds(api, confirmed["id"])) == 0
