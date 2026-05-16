"""Session confirm, cancel, and the cancellation-fee ladder.

Covers PRD §3.5 (confirm + overlap), §3.8 (cancellation fee tiers and
refund), and §2.10 (cancellation cascade for tutor suspend + link
revoke is in test_09).
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    advance_clock_to,
    assert_money_conservation_invariant,
    assert_session,
    book_session,
    book_session_payload,
    cancel_session,
    confirm_session,
    create_adult_student,
    create_parent,
    create_tutor,
    iso_utc,
    make_parent_headers,
    make_student_headers,
    make_tutor_headers,
    make_tutor_verified,
    parse_iso,
    server_now_dt,
    setup_active_parent_child,
    setup_basic_booking_scenario,
    setup_confirmed_session,
    setup_verified_tutor_with_subject,
    validate_error,
    validate_success,
)


# ===========================================================================
# Confirmation
# ===========================================================================
class TestConfirmSession:
    def test_confirm_requires_acting_tutor(self, api):
        """PRD §3.5: "Confirmation requires the acting tutor's
        X-User-ID to equal the session's tutor_id".

        Claim: a different tutor confirming returns
        ERR_NOT_AUTHORIZED_FOR_RESOURCE.
        """
        tutor, _student, session = setup_basic_booking_scenario()
        other_tutor, _, _ = make_tutor_verified()
        res = api.confirm_session(
            session["id"], make_tutor_headers(other_tutor["id"]),
        )
        validate_error(res, "ERR_NOT_AUTHORIZED_FOR_RESOURCE")

    def test_confirm_blocked_when_tutor_not_verified(self, api,
                                                    admin_headers):
        """PRD §3.5: "requires the tutor's current verification_status
        to be VERIFIED (a tutor whose posture has slipped to SUSPENDED
        or UNVERIFIED between booking and confirmation cannot confirm
        — ERR_TUTOR_NOT_VERIFIED)".

        Claim: tutor suspended between booking and confirm returns
        ERR_TUTOR_NOT_VERIFIED.

        # difficulty: cross_entity_state_dependency/session_confirm_requires_tutor_verified
        """
        tutor, _student, session = setup_basic_booking_scenario()
        # Admin suspends.
        api.suspend_tutor(tutor["id"], admin_headers)
        res = api.confirm_session(
            session["id"], make_tutor_headers(tutor["id"]),
        )
        validate_error(res, "ERR_TUTOR_NOT_VERIFIED")

    def test_confirm_requested_session_succeeds(self, api):
        """PRD §3.5: "The owning tutor confirms the session, which
        advances REQUESTED → CONFIRMED."

        Claim: confirming a REQUESTED session by its tutor returns
        status=CONFIRMED.
        """
        tutor, _student, session = setup_basic_booking_scenario()
        confirmed = confirm_session(session=session, tutor=tutor)
        assert confirmed["status"] == "CONFIRMED"

    def test_confirm_invalid_state_when_already_confirmed(self, api):
        """PRD §2.6 priority 5 / §3.5: "Target entity in a state where
        the requested transition is defined" otherwise
        ERR_INVALID_STATE.

        Claim: confirming an already-CONFIRMED session returns
        ERR_INVALID_STATE.
        """
        tutor, _student, session = setup_confirmed_session()
        res = api.confirm_session(
            session["id"], make_tutor_headers(tutor["id"]),
        )
        validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# Overlap detection — PRD §3.5
# ===========================================================================
class TestOverlap:
    def test_strict_overlap_rejected(self, api):
        """PRD §3.5: "Temporal overlap uses a closed-open interval
        [start_at, end_at) with a 0-minute buffer: two sessions
        overlap if the open interval of one contains any instant of
        the closed-open interval of the other. An overlap is rejected
        with ERR_SESSION_OVERLAP."

        Claim: confirming a session that strictly overlaps an existing
        CONFIRMED session for the same tutor returns
        ERR_SESSION_OVERLAP.

        # difficulty: resource_temporal_overlap/tutor_session_closed_open_interval_overlap
        """
        tutor, _, _ = make_tutor_verified()
        from test_helpers import add_approved_subject
        add_approved_subject(tutor=tutor, subject_code="MATH_ALGEBRA")
        tutor = validate_success(
            api.get_tutor(tutor["id"], TEST_USERS["admin_headers"]),
        )
        # Sessions for different students so trial uniqueness is moot.
        s1_student = create_adult_student()
        s2_student = create_adult_student()
        now = server_now_dt()
        a = book_session(
            tutor=tutor, student=s1_student, duration_minutes=60,
            start_at=iso_utc(now + timedelta(hours=2)),
            end_at=iso_utc(now + timedelta(hours=3)),
        )
        b = book_session(
            tutor=tutor, student=s2_student, duration_minutes=60,
            start_at=iso_utc(now + timedelta(hours=2, minutes=30)),
            end_at=iso_utc(now + timedelta(hours=3, minutes=30)),
        )
        confirm_session(session=a, tutor=tutor)
        res = api.confirm_session(
            b["id"], make_tutor_headers(tutor["id"]),
        )
        validate_error(res, "ERR_SESSION_OVERLAP")

    def test_adjacent_sessions_do_not_overlap(self, api):
        """PRD §3.5: "Temporal overlap uses a closed-open interval
        [start_at, end_at) with a 0-minute buffer".

        Claim: a session starting exactly when another ends does NOT
        overlap; both can be CONFIRMED for the same tutor.
        """
        tutor, _, _ = make_tutor_verified()
        from test_helpers import add_approved_subject
        add_approved_subject(tutor=tutor, subject_code="MATH_ALGEBRA")
        tutor = validate_success(
            api.get_tutor(tutor["id"], TEST_USERS["admin_headers"]),
        )
        s1_student = create_adult_student()
        s2_student = create_adult_student()
        now = server_now_dt()
        a = book_session(
            tutor=tutor, student=s1_student,
            start_at=iso_utc(now + timedelta(hours=2)),
            end_at=iso_utc(now + timedelta(hours=3)),
        )
        b = book_session(
            tutor=tutor, student=s2_student,
            start_at=iso_utc(now + timedelta(hours=3)),
            end_at=iso_utc(now + timedelta(hours=4)),
        )
        a_confirmed = confirm_session(session=a, tutor=tutor)
        b_confirmed = confirm_session(session=b, tutor=tutor)
        assert a_confirmed["status"] == "CONFIRMED"
        assert b_confirmed["status"] == "CONFIRMED"


# ===========================================================================
# Cancellation — PRD §3.8
# ===========================================================================
class TestCancellation:
    def test_tutor_cancel_marks_cancelled_by_tutor_zero_fee_full_refund(
        self, api,
    ):
        """PRD §3.8: "Tutor-initiated cancellations and any
        system-driven cascade cancellations carry a fee of 0." And:
        "refund_to_student_cents is set to charged_amount_cents (full
        refund, fee 0) for a tutor cancel".

        Claim: tutor-initiated cancel of CONFIRMED session yields
        status=CANCELLED_BY_TUTOR, fee=0, refund=charged_amount.

        # difficulty: non_linear_state_machine/session_branching_complete_or_cancel_or_dispute
        """
        tutor, student, confirmed = setup_confirmed_session()
        cancelled = cancel_session(
            session=confirmed, actor_headers=make_tutor_headers(tutor["id"]),
        )
        assert cancelled["status"] == "CANCELLED_BY_TUTOR"
        assert cancelled["cancellation_fee_cents"] == 0
        assert (
            cancelled["refund_to_student_cents"]
            == confirmed["charged_amount_cents"]
        )
        assert_money_conservation_invariant(cancelled)

    def test_student_cancel_24h_notice_free(self, api):
        """PRD §3.8: "If hours-of-notice is at least 24, the fee is 0
        (a free cancel)" — and "a hours-of-notice equal to exactly
        24.0 is free."

        Claim: student-initiated cancel with start_at exactly 24h
        away yields fee=0, refund=charged_amount.

        # difficulty: boundary_precision_check/cancellation_fee_24h_boundary_inclusive
        """
        tutor, _ = setup_verified_tutor_with_subject(hourly_rate_cents=6000)
        student = create_adult_student()
        now = server_now_dt()
        s = book_session(
            tutor=tutor, student=student, duration_minutes=60,
            start_at=iso_utc(now + timedelta(hours=24)),
            end_at=iso_utc(now + timedelta(hours=25)),
        )
        cancelled = cancel_session(
            session=s, actor_headers=make_student_headers(student["id"]),
        )
        assert cancelled["status"] == "CANCELLED_BY_STUDENT"
        assert cancelled["cancellation_fee_cents"] == 0
        assert (
            cancelled["refund_to_student_cents"]
            == s["charged_amount_cents"]
        )

    def test_student_cancel_just_under_24h_charges_25pct(self, api):
        """PRD §3.8: "If hours-of-notice is less than 24 but at least
        2, the fee is 25% of charged_amount_cents, rounded half-up."

        Claim: student cancel with start_at 23h59m away charges 25%
        fee = round_half_up(0.25 * 6000) = 1500.
        """
        tutor, _ = setup_verified_tutor_with_subject(hourly_rate_cents=6000)
        student = create_adult_student()
        now = server_now_dt()
        s = book_session(
            tutor=tutor, student=student, duration_minutes=60,
            start_at=iso_utc(now + timedelta(hours=23, minutes=59)),
            end_at=iso_utc(now + timedelta(hours=24, minutes=59)),
        )
        cancelled = cancel_session(
            session=s, actor_headers=make_student_headers(student["id"]),
        )
        assert cancelled["status"] == "CANCELLED_BY_STUDENT"
        assert cancelled["cancellation_fee_cents"] == 1500
        assert cancelled["refund_to_student_cents"] == 4500

    def test_student_cancel_under_2h_charges_50pct(self, api):
        """PRD §3.8: "If hours-of-notice is less than 2, the fee is
        50% of charged_amount_cents, rounded half-up."

        Claim: student cancel with start_at 1h away charges 50% fee
        = round_half_up(0.50 * 6000) = 3000.
        """
        tutor, _ = setup_verified_tutor_with_subject(hourly_rate_cents=6000)
        student = create_adult_student()
        now = server_now_dt()
        # Need start_at >= now+60min for the booking lead-time gate,
        # so use exactly 1h05m here so cancel still falls below 2h.
        start = iso_utc(now + timedelta(hours=1, minutes=5))
        end = iso_utc(now + timedelta(hours=2, minutes=5))
        s = book_session(
            tutor=tutor, student=student,
            start_at=start, end_at=end,
        )
        cancelled = cancel_session(
            session=s, actor_headers=make_student_headers(student["id"]),
        )
        assert cancelled["cancellation_fee_cents"] == 3000
        assert cancelled["refund_to_student_cents"] == 3000

    def test_student_cancel_credits_student_balance(self, api):
        """PRD §3.8: "The student's credit_balance_cents is then
        increased by refund_to_student_cents."

        Claim: after a free student-initiated cancel, the student's
        credit_balance_cents increases by refund_to_student_cents.
        """
        tutor, _ = setup_verified_tutor_with_subject(hourly_rate_cents=6000)
        student = create_adult_student()
        now = server_now_dt()
        # 48h notice → free cancel.
        s = book_session(
            tutor=tutor, student=student, duration_minutes=60,
            start_at=iso_utc(now + timedelta(hours=48)),
            end_at=iso_utc(now + timedelta(hours=49)),
        )
        cancelled = cancel_session(
            session=s, actor_headers=make_student_headers(student["id"]),
        )
        refreshed_student = validate_success(
            api.get_student(student["id"], make_student_headers(student["id"])),
        )
        assert (
            refreshed_student["credit_balance_cents"]
            == cancelled["refund_to_student_cents"]
        )

    def test_cancel_by_wrong_student_rejected(self, api):
        """PRD §3.8: "Student cancellation requires the acting
        student's X-User-ID to equal the session's student_id — any
        mismatch is rejected with ERR_NOT_AUTHORIZED_FOR_RESOURCE."

        Claim: a different student attempting to cancel returns
        ERR_NOT_AUTHORIZED_FOR_RESOURCE.
        """
        tutor, _student, session = setup_basic_booking_scenario()
        other = create_adult_student()
        res = api.cancel_session(
            session["id"], make_student_headers(other["id"]),
        )
        validate_error(res, "ERR_NOT_AUTHORIZED_FOR_RESOURCE")

    def test_parent_cancel_for_minor_via_active_link(self, api):
        """PRD §3.8: "Parent cancellation requires an ACTIVE
        ParentChildLink to the student".

        Claim: parent cancels a session booked for their MINOR child
        (link is ACTIVE) yields status=CANCELLED_BY_STUDENT.
        """
        tutor, _ = setup_verified_tutor_with_subject()
        parent, student, _link = setup_active_parent_child()
        s = book_session(
            tutor=tutor, student=student, duration_minutes=60,
            parent=parent,
        )
        cancelled = cancel_session(
            session=s, actor_headers=make_parent_headers(parent["id"]),
        )
        assert cancelled["status"] == "CANCELLED_BY_STUDENT"
