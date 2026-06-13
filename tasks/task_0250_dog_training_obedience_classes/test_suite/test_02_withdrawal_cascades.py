"""Withdrawal, refunds, credit conservation, and seat conservation.

Covers the withdrawal cascade (§3.6), the all-or-nothing PACKAGE credit refund (§3.7),
the depth-3 package un-deplete cascade, and the conserved-quantity invariants for credits
and seats.
"""
import pytest

from test_helpers import (
    api_client, validate_success, get_success_data,
    TEST_USERS, make_owner_headers,
    setup_enroll_ready_group, setup_enroll_ready_private, setup_enrollment_with_attended_sessions,
    enroll, create_package,
    assert_package_credit_invariant,
)


def test_cash_withdrawal_sets_status_withdrawn_with_progress(api):
    """PRD §3.6: "An owner (or `FrontDesk` or `AdminManager` on their behalf) withdraws an
    enrollment, moving it to the terminal `WITHDRAWN` state from any of `PENDING_PREREQS`,
    `ACTIVE`, `WAITLISTED`, or `SUSPENDED`." PRD §3.9: "The `sessions_attended` count is the
    number of `PRESENT` attendance records on non-makeup sessions plus the number of
    attendance records in `MAKEUP_DONE`."

    Design: Difficulty/dual_variant_calc/enrollment_refund_forward_vs_chronological_on_enrollment
    """
    bundle = setup_enrollment_with_attended_sessions(
        session_count=6, attend_n=3, list_price_cents=10001, credit_cost=2)
    owner, enr = bundle["owner"], bundle["enrollment"]

    res = api.withdraw_enrollment(enr["id"], make_owner_headers(owner["id"]))
    withdrawn = validate_success(res, 200)
    assert withdrawn["status"] == "WITHDRAWN"

    fetched = validate_success(api.get_enrollment(enr["id"], make_owner_headers(owner["id"])), 200)
    assert fetched["sessions_attended"] == 3, "3 of 6 sessions marked PRESENT and completed"


def test_cash_withdrawal_refund_is_forward_looking_on_remaining(api):
    """PRD §3.7: "For a `CASH` enrollment, the applied refund — the value placed in
    `refund_cents` — is forward-looking: it is the per-session value multiplied by the number
    of remaining sessions, rounded half up to a whole cent."

    A whole-cent per-session value (12000 / 6 = 2000) avoids the rounding-divergence design
    space, so the refund is uniquely 2000 * 3 = 6000 for any faithful PRD reader.

    Design: Difficulty/dual_variant_calc/enrollment_refund_forward_vs_chronological_on_enrollment
    """
    bundle = setup_enrollment_with_attended_sessions(
        session_count=6, attend_n=3, list_price_cents=12000, credit_cost=2)
    owner, enr = bundle["owner"], bundle["enrollment"]

    res = api.withdraw_enrollment(enr["id"], make_owner_headers(owner["id"]))
    withdrawn = validate_success(res, 200)
    assert withdrawn["status"] == "WITHDRAWN"
    # per_session = 12000/6 = 2000 (whole cents); remaining = 6 - 3 = 3 -> 6000.
    assert withdrawn["refund_cents"] == 6000, "2000 per session * 3 remaining"


def test_package_withdrawal_credits_refunded_all_or_nothing(api):
    """PRD §3.7: "For a `PACKAGE` enrollment the refund is all-or-nothing in credits rather
    than cents: `credits_refunded` is the series' `credit_cost` when any sessions remain (the
    remaining count is above 0), and 0 when no sessions remain."

    Design: Difficulty/transitive_cascade/withdraw_package_enrollment_depth3_credit_undeplete
    """
    bundle = setup_enroll_ready_private(session_count=1, list_price_cents=30000, credit_cost=4)
    owner = bundle["owner"]
    pkg = create_package(owner, tier="STARTER")  # 4 credits total
    enr = enroll(owner, bundle["dog"], bundle["series"], payment_method="PACKAGE",
                 package_id=pkg["id"], series_version=bundle["series"]["version"])

    res = api.withdraw_enrollment(enr["id"], make_owner_headers(owner["id"]))
    withdrawn = validate_success(res, 200)
    # No sessions attended, so all sessions remain -> full credit_cost (4) returned.
    assert withdrawn["credits_refunded"] == 4, "credit_cost returned when sessions remain"


def test_package_withdraw_undepletes_package_depth3(api):
    """PRD §3.6: "For a package withdrawal, the package's `credits_consumed` is decreased and
    its `credits_remaining` recomputed; and if the package had been `DEPLETED` and now has
    `credits_remaining` above 0, it returns `DEPLETED → ACTIVE`."

    Design: Difficulty/transitive_cascade/withdraw_package_enrollment_depth3_credit_undeplete
    """
    bundle = setup_enroll_ready_private(session_count=1, list_price_cents=30000, credit_cost=4)
    owner = bundle["owner"]
    pkg = create_package(owner, tier="STARTER")  # 4 credits; a 4-credit enroll drains it
    enr = enroll(owner, bundle["dog"], bundle["series"], payment_method="PACKAGE",
                 package_id=pkg["id"], series_version=bundle["series"]["version"])

    drained = validate_success(api.get_package(pkg["id"], make_owner_headers(owner["id"])), 200)
    assert drained["status"] == "DEPLETED", "STARTER fully drained by 4-credit enroll"
    assert drained["credits_remaining"] == 0

    api.withdraw_enrollment(enr["id"], make_owner_headers(owner["id"]))
    restored = validate_success(api.get_package(pkg["id"], make_owner_headers(owner["id"])), 200)
    assert restored["status"] == "ACTIVE", "un-depleted from DEPLETED after reversal"
    assert restored["credits_remaining"] == 4, "reversal restored all 4 credits"


def test_package_credit_conservation_round_trip(api):
    """PRD §3.12: "the system holds the invariant that `credits_remaining` plus
    `credits_consumed` equals `credits_total`." PRD §3.6: "For a package withdrawal, the
    package's `credits_consumed` is decreased and its `credits_remaining` recomputed".

    Design: Difficulty/compensating_invariant/package_credit_conservation_debit_then_reversal
    """
    bundle = setup_enroll_ready_group(session_count=1, list_price_cents=12000, credit_cost=2)
    owner = bundle["owner"]
    pkg = create_package(owner, tier="VALUE")  # credits_total = 9
    enr = enroll(owner, bundle["dog"], bundle["series"], payment_method="PACKAGE",
                 package_id=pkg["id"], series_version=bundle["series"]["version"])

    api.withdraw_enrollment(enr["id"], make_owner_headers(owner["id"]))
    after = validate_success(api.get_package(pkg["id"], make_owner_headers(owner["id"])), 200)
    assert after["credits_remaining"] == 9, "back to total after the reversal"
    assert after["credits_consumed"] == 0
    assert_package_credit_invariant(after)


def test_package_credit_conservation_invariant_holds(api):
    """PRD §3.12: "the system holds the invariant that `credits_remaining` plus
    `credits_consumed` equals `credits_total`."

    Design: Difficulty/compensating_invariant/package_credit_conservation_debit_then_reversal
    """
    bundle = setup_enroll_ready_group(session_count=1, list_price_cents=12000, credit_cost=2)
    owner = bundle["owner"]
    pkg = create_package(owner, tier="VALUE")  # 9 total
    enr = enroll(owner, bundle["dog"], bundle["series"], payment_method="PACKAGE",
                 package_id=pkg["id"], series_version=bundle["series"]["version"])

    # Invariant holds after the DEBIT (mid round-trip)...
    mid = validate_success(api.get_package(pkg["id"], make_owner_headers(owner["id"])), 200)
    assert mid["credits_remaining"] == 7, "9 - 2 debited"
    assert_package_credit_invariant(mid)

    # ...and again after the REVERSAL.
    api.withdraw_enrollment(enr["id"], make_owner_headers(owner["id"]))
    after = validate_success(api.get_package(pkg["id"], make_owner_headers(owner["id"])), 200)
    assert_package_credit_invariant(after)


def test_seat_conservation_enroll_then_withdraw(api):
    """PRD §3.5: "The `seats_available` figure is the series `capacity` minus that
    seat-holding count." PRD §3.6: "any outstanding `EXPECTED` or `MAKEUP_PENDING` attendance
    rows are deleted, and the series' `seats_available` is recomputed — releasing the seat if
    the withdrawn enrollment had held one."

    Design: Difficulty/compensating_invariant/seat_conservation_enroll_then_withdraw
    """
    bundle = setup_enroll_ready_group(session_count=1, capacity=5)
    owner, series = bundle["owner"], bundle["series"]
    enr = enroll(owner, bundle["dog"], series, series_version=series["version"])

    after_enroll = validate_success(
        api.get_class_series(series["id"], TEST_USERS["admin_manager_headers"]), 200)
    assert after_enroll["seats_available"] == 4, "one seat held by the ACTIVE enrollment"

    api.withdraw_enrollment(enr["id"], make_owner_headers(owner["id"]))
    after_withdraw = validate_success(
        api.get_class_series(series["id"], TEST_USERS["admin_manager_headers"]), 200)
    assert after_withdraw["seats_available"] == 5, "seat released; back to capacity"


def test_seat_conservation_invariant_holds_after_round_trip(api):
    """PRD §3.5: "The invariant the system maintains is that the seat-holding count plus
    `seats_available` equals `capacity`."

    Design: Difficulty/compensating_invariant/seat_conservation_enroll_then_withdraw
    """
    bundle = setup_enroll_ready_group(session_count=1, capacity=5)
    owner, series = bundle["owner"], bundle["series"]
    enr = enroll(owner, bundle["dog"], series, series_version=series["version"])
    api.withdraw_enrollment(enr["id"], make_owner_headers(owner["id"]))

    final = validate_success(
        api.get_class_series(series["id"], TEST_USERS["admin_manager_headers"]), 200)
    # seat-holding count is now 0, so seats_available must equal capacity (5).
    assert final["seats_available"] == 5
    assert final["capacity"] == 5
