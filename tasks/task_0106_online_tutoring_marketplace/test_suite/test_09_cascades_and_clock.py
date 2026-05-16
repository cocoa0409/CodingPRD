"""Cascades and the test clock.

Covers PRD §2.10 (force-cancellation cascade for credential expiry,
tutor suspend, and ParentChildLink revoke) and §3.9 (the clock-advance
sweeps).
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock_to,
    assert_money_conservation_invariant,
    book_session,
    confirm_session,
    create_adult_student,
    create_minor_student,
    create_parent,
    iso_utc,
    make_parent_headers,
    make_student_headers,
    make_tutor_headers,
    make_tutor_verified,
    parse_iso,
    revoke_link,
    server_now_dt,
    setup_active_parent_child,
    setup_basic_booking_scenario,
    setup_confirmed_session,
    setup_verified_tutor_with_subject,
    submit_credential,
    validate_success,
)


# ===========================================================================
# Credential expiry cascade — PRD §2.10
# ===========================================================================
class TestCredentialExpiryCascade:
    def test_critical_credential_expiry_suspends_tutor(self, api):
        """PRD §2.10: "When a credential expires (a system-driven
        action during clock advance), the credential transitions to
        EXPIRED, the tutor's verification_status is recomputed and,
        if it drops below VERIFIED, the tutor moves to SUSPENDED".

        Claim: clock advance past a GOVERNMENT_ID expires_at causes
        Credential→EXPIRED and Tutor→SUSPENDED.
        """
        # Build a VERIFIED tutor with critical credentials having a
        # near-future expiry on GOVERNMENT_ID.
        from test_helpers import make_tutor_verified
        soon = iso_utc(server_now_dt() + timedelta(hours=5))
        far = iso_utc(server_now_dt() + timedelta(days=30))
        tutor, gov_cred, bg_cred = make_tutor_verified(
            gov_id_expires_at=soon, bg_check_expires_at=far,
        )
        assert tutor["verification_status"] == "VERIFIED"
        # Advance past soon.
        advance_clock_to(iso_utc(server_now_dt() + timedelta(hours=6)))
        refreshed_tutor = validate_success(
            api.get_tutor(tutor["id"], TEST_USERS["admin_headers"]),
        )
        assert refreshed_tutor["verification_status"] == "SUSPENDED"

    def test_expiry_force_cancels_future_confirmed_sessions(self, api):
        """PRD §2.10: "every Session of that tutor in CONFIRMED whose
        start_at is in the future is force-cancelled to
        CANCELLED_BY_TUTOR with refund_to_student_cents set equal to
        charged_amount_cents and cancellation_fee_cents set to 0".

        Claim: after credential expiry that suspends the tutor, a
        future CONFIRMED session becomes CANCELLED_BY_TUTOR with full
        refund and zero fee, and the student's credit_balance_cents
        rises by the refund.

        # difficulty: transitive_cascade/credential_expiry_cascade_depth3
        """
        from test_helpers import add_approved_subject
        soon = iso_utc(server_now_dt() + timedelta(hours=5))
        far = iso_utc(server_now_dt() + timedelta(days=30))
        tutor, gov_cred, bg_cred = make_tutor_verified(
            gov_id_expires_at=soon, bg_check_expires_at=far,
        )
        add_approved_subject(tutor=tutor, subject_code="MATH_ALGEBRA")
        tutor = validate_success(
            api.get_tutor(tutor["id"], TEST_USERS["admin_headers"]),
        )
        student = create_adult_student()
        # Schedule the session well after credential expiry (>= soon).
        future_start = server_now_dt() + timedelta(hours=10)
        s = book_session(
            tutor=tutor, student=student, duration_minutes=60,
            start_at=iso_utc(future_start),
            end_at=iso_utc(future_start + timedelta(hours=1)),
        )
        confirm_session(session=s, tutor=tutor)
        # Sweep past credential expiry.
        advance_clock_to(iso_utc(server_now_dt() + timedelta(hours=6)))
        refreshed = validate_success(
            api.get_session(s["id"], make_student_headers(student["id"])),
        )
        assert refreshed["status"] == "CANCELLED_BY_TUTOR"
        assert refreshed["cancellation_fee_cents"] == 0
        assert (
            refreshed["refund_to_student_cents"]
            == s["charged_amount_cents"]
        )
        assert_money_conservation_invariant(refreshed)
        # Student credit increased.
        refreshed_student = validate_success(
            api.get_student(student["id"], make_student_headers(student["id"])),
        )
        assert (
            refreshed_student["credit_balance_cents"]
            == refreshed["refund_to_student_cents"]
        )


# ===========================================================================
# Admin suspend cascade — PRD §2.10
# ===========================================================================
class TestAdminSuspendCascade:
    def test_admin_suspend_cancels_future_confirmed_sessions(self, api,
                                                              admin_headers):
        """PRD §2.10: "The same future-CONFIRMED-cancel cascade fires
        when a PlatformAdmin explicitly suspends a tutor (VERIFIED to
        SUSPENDED)".

        Claim: after admin suspend, a future CONFIRMED session for the
        tutor becomes CANCELLED_BY_TUTOR with full refund.
        """
        tutor, student, confirmed = setup_confirmed_session()
        api.suspend_tutor(tutor["id"], admin_headers)
        refreshed = validate_success(
            api.get_session(
                confirmed["id"], make_student_headers(student["id"]),
            ),
        )
        assert refreshed["status"] == "CANCELLED_BY_TUTOR"
        assert (
            refreshed["refund_to_student_cents"]
            == confirmed["charged_amount_cents"]
        )
        assert refreshed["cancellation_fee_cents"] == 0


# ===========================================================================
# Link revoke cascade — PRD §2.10, §3.3
# ===========================================================================
class TestLinkRevokeCascade:
    def test_revoke_link_cancels_future_minor_sessions(self, api):
        """PRD §2.10: "a structurally similar cascade fires when a
        Parent or PlatformAdmin revokes an ACTIVE ParentChildLink:
        every Session of that minor child in REQUESTED or CONFIRMED
        with start_at in the future is cascade-cancelled as
        CANCELLED_BY_STUDENT with refund_to_student_cents equal to
        charged_amount_cents minus the cancellation fee computed for
        the child's session per the cancellation-fee rule."

        Claim: after the parent revokes the link, the child's future
        CONFIRMED session moves to CANCELLED_BY_STUDENT.

        # difficulty: transitive_cascade/parent_link_revoke_cascade_depth2
        """
        tutor, _ = setup_verified_tutor_with_subject(
            hourly_rate_cents=6000,
        )
        parent, student, link = setup_active_parent_child()
        # Schedule session well in the future so cancellation fee is 0.
        now = server_now_dt()
        s = book_session(
            tutor=tutor, student=student, duration_minutes=60,
            parent=parent,
            start_at=iso_utc(now + timedelta(days=2)),
            end_at=iso_utc(now + timedelta(days=2, hours=1)),
        )
        confirmed = confirm_session(session=s, tutor=tutor)
        revoke_link(parent=parent, link=link)
        # After revoke the link is REVOKED; per PRD §2.1 a Parent's
        # access to a child's Session is mediated by an ACTIVE link,
        # so we re-fetch via PlatformAdmin to observe the cascade.
        refreshed = validate_success(
            api.get_session(
                confirmed["id"], TEST_USERS["admin_headers"],
            ),
        )
        assert refreshed["status"] == "CANCELLED_BY_STUDENT"
        # >=24h notice → cancellation_fee=0; refund = charged_amount.
        assert refreshed["cancellation_fee_cents"] == 0
        assert (
            refreshed["refund_to_student_cents"]
            == confirmed["charged_amount_cents"]
        )


# ===========================================================================
# Clock-advance sweeps — PRD §3.9
# ===========================================================================
class TestClockSweeps:
    def test_confirmed_session_enters_in_progress_at_start_at(self, api):
        """PRD §3.5: "Every Session in CONFIRMED whose start_at is at
        or before the new clock and whose end_at is strictly later
        transitions CONFIRMED → IN_PROGRESS."

        Claim: clock advance to a moment inside [start_at, end_at) on
        a CONFIRMED session moves it to IN_PROGRESS.
        """
        tutor, student, confirmed = setup_confirmed_session(
            duration_minutes=60,
        )
        start_dt = parse_iso(confirmed["start_at"])
        end_dt = parse_iso(confirmed["end_at"])
        # Advance to start_dt + 1min (inside open interval).
        advance_clock_to(iso_utc(start_dt + timedelta(minutes=1)))
        refreshed = validate_success(
            api.get_session(
                confirmed["id"], make_student_headers(student["id"]),
            ),
        )
        assert refreshed["status"] == "IN_PROGRESS"

    def test_settled_sweep_runs_at_72h(self, api):
        """PRD §3.6: "When both are met, the session transitions
        COMPLETED → SETTLED, and the tutor's payout_balance_cents is
        increased by the session's pinned tutor_payout_cents."

        Claim: after 72h+1min and a sweep, COMPLETED with no active
        dispute becomes SETTLED and the tutor's payout_balance_cents
        rises by tutor_payout_cents.
        """
        from test_helpers import setup_completed_session
        tutor, student, completed = setup_completed_session(
            hourly_rate_cents=6000, duration_minutes=60,
            adjusted_minutes=60,
        )
        tutor_before = validate_success(
            api.get_tutor(tutor["id"], TEST_USERS["admin_headers"]),
        )
        assert tutor_before["payout_balance_cents"] == 0
        end_dt = parse_iso(completed["end_at"])
        advance_clock_to(
            iso_utc(end_dt + timedelta(hours=72, minutes=1)),
        )
        refreshed_session = validate_success(
            api.get_session(
                completed["id"], make_student_headers(student["id"]),
            ),
        )
        assert refreshed_session["status"] == "SETTLED"
        tutor_after = validate_success(
            api.get_tutor(tutor["id"], TEST_USERS["admin_headers"]),
        )
        assert (
            tutor_after["payout_balance_cents"]
            == completed["tutor_payout_cents"]
        )
