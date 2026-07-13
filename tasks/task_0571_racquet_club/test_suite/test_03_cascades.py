"""Multi-hop cascades and compensating reversals.

Covers the no-show -> suspend -> freeze chain, the court-maintenance sweep with
credit restoration, and the waitlist promotion on enrollment cancellation.
"""
from test_helpers import (
    api_client, validate_success, get_success_data,
    setup_member_with_strikes, setup_booking_scenario, setup_clinic,
    make_reservation, set_clock, TEST_USERS,
)

FD = TEST_USERS["frontdesk_headers"]


# ─── transitive_cascade / cascade_noshow_strike_suspend_freeze_depth3 ─
def test_third_noshow_auto_suspends_member():
    """PRD §3.4: "When no_show_strikes reaches at least 3, the member is automatically
    transitioned ACTIVE → SUSPENDED (two strikes do not suspend; the third does)."

    Design: Difficulty/transitive_cascade/cascade_noshow_strike_suspend_freeze_depth3
    """
    member, _, court = setup_member_with_strikes(2)
    rc = make_reservation(court["id"], member["id"],
                          "2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z")
    set_clock("2026-05-02T10:16:00Z")
    get_success_data(api_client.mark_no_show(rc["id"], FD))

    m = validate_success(api_client.get_member(member["id"], FD), 200)
    assert m["no_show_strikes"] == 3
    assert m["status"] == "SUSPENDED"


def test_auto_suspension_cascades_freeze_of_subscription():
    """PRD §3.4: "entering SUSPENDED triggers a further cascade: if the member owns a
    non-CANCELLED subscription that is currently ACTIVE, that subscription is
    transitioned ACTIVE → FROZEN and its frozen_at is stamped to the current clock
    instant."

    Design: Difficulty/transitive_cascade/cascade_noshow_strike_suspend_freeze_depth3
    """
    member, sub, court = setup_member_with_strikes(2)
    rc = make_reservation(court["id"], member["id"],
                          "2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z")
    set_clock("2026-05-02T10:16:00Z")
    get_success_data(api_client.mark_no_show(rc["id"], FD))

    s = validate_success(api_client.get_subscription(sub["id"], FD), 200)
    assert s["status"] == "FROZEN"


# ─── transitive_cascade / cascade_court_maintenance_cancel_credit_refund
def test_maintenance_cancels_future_booked_reservation():
    """PRD §3.1: "In the first hop, every reservation on that court that is still in
    BOOKED status and whose start_time is at or after the current clock time is
    transitioned BOOKED → CANCELLED."

    Design: Difficulty/transitive_cascade/cascade_court_maintenance_cancel_credit_refund_depth2
    """
    s = setup_booking_scenario()
    res = make_reservation(s["court"]["id"], s["member"]["id"],
                           "2026-05-06T10:00:00Z", "2026-05-06T11:00:00Z")
    court = get_success_data(api_client.court_maintenance(s["court"]["id"], FD))
    assert court["status"] == "MAINTENANCE"
    r = validate_success(api_client.get_reservation(res["id"], FD), 200)
    assert r["status"] == "CANCELLED"


def test_maintenance_cascade_restores_court_credits():
    """PRD §3.1: "In the second hop, each such cancellation restores that
    reservation's credits_used to the owning subscription's court_credits_remaining
    and reverses its provisional_fee_cents from the member's account_balance_cents,
    following the compensation invariant."

    Design: Difficulty/transitive_cascade/cascade_court_maintenance_cancel_credit_refund_depth2
    """
    s = setup_booking_scenario()
    make_reservation(s["court"]["id"], s["member"]["id"],
                     "2026-05-06T10:00:00Z", "2026-05-06T11:00:00Z")
    get_success_data(api_client.court_maintenance(s["court"]["id"], FD))
    sub = validate_success(api_client.get_subscription(s["sub"]["id"], FD), 200)
    assert sub["court_credits_remaining"] == 8


# ─── Corner: enrollment_cancel_promotes_earliest_waitlisted ───────────
def test_enrollment_cancel_promotes_earliest_waitlisted():
    """PRD §3.5: "If the cancelled seat was an ENROLLED seat and a waitlist exists, the
    system promotes the earliest WAITLISTED enrollment — the one with the earliest
    created_at in ascending order — from WAITLISTED → ENROLLED, and the lesson's
    enrolled_count is recomputed."

    Design: Corner/cross_cutting/enrollment_cancel_promotes_earliest_waitlisted
    """
    c = setup_clinic(capacity=1, enroll=2)
    enrolled, waitlisted = c["enrollments"][0], c["enrollments"][1]
    get_success_data(api_client.cancel_enrollment(enrolled["id"], FD))

    ex = validate_success(api_client.get_enrollment(enrolled["id"], FD), 200)
    ey = validate_success(api_client.get_enrollment(waitlisted["id"], FD), 200)
    lesson = validate_success(api_client.get_lesson(c["lesson"]["id"], FD), 200)
    assert ex["status"] == "CANCELLED"
    assert ey["status"] == "ENROLLED"
    assert lesson["enrolled_count"] == 1
