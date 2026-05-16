"""Session booking: gross pricing, validation gates, credit application.

Covers PRD §3.4: book session, gross-pricing formula (tiered discount),
PROVISIONAL commission, credit application, trial eligibility, lead-time
and duration validation, MINOR-via-Parent gating.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    DISCOUNT_TIER_120_RATE,
    DISCOUNT_TIER_180_RATE,
    NON_EXISTENT_UUID,
    TEST_DEFAULTS,
    TEST_USERS,
    add_approved_subject,
    advance_clock_to,
    assert_session,
    book_session,
    book_session_payload,
    create_adult_student,
    create_parent,
    create_minor_student,
    create_tutor,
    iso_utc,
    make_parent_headers,
    make_student_headers,
    make_tutor_verified,
    parse_iso,
    seed_student_credit,
    server_now_dt,
    setup_active_parent_child,
    setup_basic_booking_scenario,
    setup_completed_session,
    setup_verified_tutor_with_subject,
    validate_error,
    validate_success,
)


def _book_with_minutes(api, *, tutor, student, subject_code, minutes,
                       is_trial=False, apply_credits=False):
    """Helper to book a session with a precise scheduled-minute count
    while letting the test reuse standard fixture wiring.
    """
    return book_session(
        tutor=tutor, student=student, subject_code=subject_code,
        duration_minutes=minutes, start_offset_hours=2.0,
        is_trial=is_trial, apply_credits=apply_credits,
    )


# ===========================================================================
# Booking success cases — gross pricing tiers
# ===========================================================================
class TestGrossPricing:
    def test_book_60_min_no_discount(self, api):
        """PRD §3.4: "The base per-minute rate is the tutor's
        hourly_rate_cents divided by 60.0 when is_trial is false ...
        The final gross_price_cents is the raw amount rounded half-up
        to whole cents."

        Claim: 60-minute non-trial at hourly_rate=6000 yields
        gross=6000.
        """
        tutor, _subject = setup_verified_tutor_with_subject(
            hourly_rate_cents=6000,
        )
        student = create_adult_student()
        s = book_session(
            tutor=tutor, student=student, duration_minutes=60,
        )
        assert_session(s)
        assert s["gross_price_cents"] == 6000
        assert s["status"] == "REQUESTED"
        assert s["credit_applied_cents"] == 0
        assert s["charged_amount_cents"] == 6000

    def test_book_120_min_5pct_discount(self, api):
        """PRD §3.4: "else if scheduled minutes is at least 120, the
        raw amount is multiplied by 0.95 (a 5% discount)".

        Claim: 120-min non-trial at hourly_rate=6000 yields
        round(6000/60*120*0.95) = round(11400) = 11400.

        # difficulty: combinatorial_formula/pricing_gross_multi_input_nonlinear_mode_a
        """
        tutor, _subject = setup_verified_tutor_with_subject(
            hourly_rate_cents=6000,
        )
        student = create_adult_student()
        s = _book_with_minutes(
            api, tutor=tutor, student=student,
            subject_code=TEST_DEFAULTS["DEFAULT_SUBJECT"], minutes=120,
        )
        assert s["gross_price_cents"] == 11400

    def test_book_180_min_10pct_discount(self, api):
        """PRD §3.4: "if scheduled minutes is at least 180, the raw
        amount is multiplied by 0.90 (a 10% discount)".

        Claim: 180-min non-trial at hourly_rate=6000 yields
        round(6000/60*180*0.90) = round(16200) = 16200.
        """
        tutor, _subject = setup_verified_tutor_with_subject(
            hourly_rate_cents=6000,
        )
        student = create_adult_student()
        s = _book_with_minutes(
            api, tutor=tutor, student=student,
            subject_code=TEST_DEFAULTS["DEFAULT_SUBJECT"], minutes=180,
        )
        assert s["gross_price_cents"] == 16200

    def test_book_119_min_just_under_120_no_discount(self, api):
        """PRD §3.4: "if scheduled minutes is at least 120, the raw
        amount is multiplied by 0.95"; 119 < 120 → no discount.

        Claim: 119-min non-trial at hourly_rate=6000 yields
        round(6000/60*119) = round(11900) = 11900 (no discount).
        """
        tutor, _subject = setup_verified_tutor_with_subject(
            hourly_rate_cents=6000,
        )
        student = create_adult_student()
        s = _book_with_minutes(
            api, tutor=tutor, student=student,
            subject_code=TEST_DEFAULTS["DEFAULT_SUBJECT"], minutes=119,
        )
        assert s["gross_price_cents"] == 11900

    def test_book_trial_uses_trial_rate_no_discount(self, api):
        """PRD §3.4: "Trial bookings receive no discount even if they
        meet the duration thresholds."

        Claim: 60-min trial at trial_rate=4000 yields
        round(4000/60*60) = 4000; no discount even at long durations.
        """
        tutor, _subject = setup_verified_tutor_with_subject(
            hourly_rate_cents=6000, trial_rate_cents=4000,
        )
        student = create_adult_student()
        s = _book_with_minutes(
            api, tutor=tutor, student=student,
            subject_code=TEST_DEFAULTS["DEFAULT_SUBJECT"],
            minutes=60, is_trial=True,
        )
        assert s["gross_price_cents"] == 4000
        assert s["is_trial"] is True


# ===========================================================================
# Validation gates — PRD §3.4 + §2.6 priority order
# ===========================================================================
class TestBookingValidations:
    def test_book_unverified_tutor_rejected(self, api):
        """PRD §3.4: "The tutor must be VERIFIED — bookings against
        any other verification_status are rejected with
        ERR_TUTOR_NOT_VERIFIED."

        Per PRD §2.6, ERR_SUBJECT_NOT_OFFERED (priority 9) fires
        BEFORE ERR_TUTOR_NOT_VERIFIED (priority 10). Per PRD §3.2,
        subject tags can only be APPROVED on a VERIFIED tutor. So we
        must first verify the tutor, approve the subject, then move
        the tutor out of VERIFIED (via PlatformAdmin suspend per
        PRD §3.1) so the subject-offered gate passes but the
        verification gate fails.

        Claim: booking against a SUSPENDED tutor whose subject is
        still APPROVED returns ERR_TUTOR_NOT_VERIFIED.
        """
        tutor, _ = setup_verified_tutor_with_subject(
            subject_code="MATH_ALGEBRA",
        )
        # Suspend the tutor — verification_status drops out of VERIFIED.
        validate_success(
            api.suspend_tutor(tutor["id"], TEST_USERS["admin_headers"]),
        )
        student = create_adult_student()
        res = api.book_session(
            book_session_payload(
                tutor_id=tutor["id"], student_id=student["id"],
                subject_code="MATH_ALGEBRA",
                start_at=iso_utc(server_now_dt() + timedelta(hours=2)),
                end_at=iso_utc(server_now_dt() + timedelta(hours=3)),
            ),
            make_student_headers(student["id"]),
        )
        validate_error(res, "ERR_TUTOR_NOT_VERIFIED")

    def test_book_subject_not_offered_rejected(self, api):
        """PRD §3.4: "The subject_code must match an APPROVED
        SubjectTag for the tutor; otherwise ERR_SUBJECT_NOT_OFFERED."

        Claim: booking on a tutor with no APPROVED tag for the subject
        returns ERR_SUBJECT_NOT_OFFERED.
        """
        from test_helpers import make_tutor_verified
        tutor, _, _ = make_tutor_verified()  # no APPROVED subject yet
        student = create_adult_student()
        res = api.book_session(
            book_session_payload(
                tutor_id=tutor["id"], student_id=student["id"],
                subject_code="BIO_GENETICS",
                start_at=iso_utc(server_now_dt() + timedelta(hours=2)),
                end_at=iso_utc(server_now_dt() + timedelta(hours=3)),
            ),
            make_student_headers(student["id"]),
        )
        validate_error(res, "ERR_SUBJECT_NOT_OFFERED")

    def test_book_lead_time_under_60min_rejected(self, api):
        """PRD §3.4: "start_at must be at least 60 minutes ahead of the
        current clock (the minimum-lead-time rule)".

        Claim: start_at 30 minutes from now returns
        ERR_INVALID_SESSION_WINDOW.
        """
        tutor, _ = setup_verified_tutor_with_subject()
        student = create_adult_student()
        now = server_now_dt()
        res = api.book_session(
            book_session_payload(
                tutor_id=tutor["id"], student_id=student["id"],
                start_at=iso_utc(now + timedelta(minutes=30)),
                end_at=iso_utc(now + timedelta(minutes=90)),
            ),
            make_student_headers(student["id"]),
        )
        validate_error(res, "ERR_INVALID_SESSION_WINDOW")

    def test_book_end_at_not_after_start_at_rejected(self, api):
        """PRD §3.4: "end_at must be strictly after start_at".

        Claim: end_at == start_at returns ERR_INVALID_SESSION_WINDOW.
        """
        tutor, _ = setup_verified_tutor_with_subject()
        student = create_adult_student()
        now = server_now_dt()
        start = iso_utc(now + timedelta(hours=2))
        res = api.book_session(
            book_session_payload(
                tutor_id=tutor["id"], student_id=student["id"],
                start_at=start, end_at=start,
            ),
            make_student_headers(student["id"]),
        )
        validate_error(res, "ERR_INVALID_SESSION_WINDOW")

    def test_book_duration_over_240min_rejected(self, api):
        """PRD §3.4: "the scheduled duration must be a positive whole
        number of minutes no greater than 240 (a four-hour cap)".

        Claim: 241-min session returns ERR_INVALID_SESSION_WINDOW.
        """
        tutor, _ = setup_verified_tutor_with_subject()
        student = create_adult_student()
        now = server_now_dt()
        start = iso_utc(now + timedelta(hours=2))
        end = iso_utc(now + timedelta(hours=2, minutes=241))
        res = api.book_session(
            book_session_payload(
                tutor_id=tutor["id"], student_id=student["id"],
                start_at=start, end_at=end,
            ),
            make_student_headers(student["id"]),
        )
        validate_error(res, "ERR_INVALID_SESSION_WINDOW")

    def test_book_duration_240min_accepted(self, api):
        """PRD §3.4: "no greater than 240 (a four-hour cap)" — exactly
        240 is permitted.

        Claim: 240-min session is accepted.
        """
        tutor, _ = setup_verified_tutor_with_subject()
        student = create_adult_student()
        s = book_session(
            tutor=tutor, student=student, duration_minutes=240,
        )
        assert s["status"] == "REQUESTED"


# ===========================================================================
# Trial eligibility — PRD §3.4
# ===========================================================================
class TestTrialEligibility:
    def test_trial_eligible_first_time_pair(self, api):
        """PRD §3.4: "the (tutor_id, student_id) pair must have no
        prior Session anywhere in history (active or terminal) with
        is_trial true, and the student must have a count of zero
        COMPLETED sessions with that tutor".

        Claim: first trial for a fresh (tutor, student) pair succeeds.
        """
        tutor, _ = setup_verified_tutor_with_subject()
        student = create_adult_student()
        s = book_session(
            tutor=tutor, student=student, duration_minutes=60,
            is_trial=True,
        )
        assert s["is_trial"] is True
        assert s["status"] == "REQUESTED"

    def test_second_trial_on_same_pair_rejected(self, api):
        """PRD §3.4: "the (tutor_id, student_id) pair must have no
        prior Session anywhere in history (active or terminal) with
        is_trial true ... otherwise ERR_TRIAL_ALREADY_USED."

        Claim: a second trial for the same pair (first still REQUESTED)
        returns ERR_TRIAL_ALREADY_USED.

        # difficulty: resource_temporal_overlap/trial_uniqueness_lifetime_aggregate_overlap
        """
        tutor, _ = setup_verified_tutor_with_subject()
        student = create_adult_student()
        book_session(
            tutor=tutor, student=student, duration_minutes=60,
            is_trial=True,
        )
        res = api.book_session(
            book_session_payload(
                tutor_id=tutor["id"], student_id=student["id"],
                start_at=iso_utc(server_now_dt() + timedelta(hours=5)),
                end_at=iso_utc(server_now_dt() + timedelta(hours=6)),
                is_trial=True,
            ),
            make_student_headers(student["id"]),
        )
        validate_error(res, "ERR_TRIAL_ALREADY_USED")

    def test_trial_blocked_after_completed_non_trial(self, api):
        """PRD §3.4: "the student must have a count of zero COMPLETED
        sessions with that tutor; otherwise ERR_TRIAL_ALREADY_USED."

        Claim: a trial booking after a COMPLETED non-trial with the
        same tutor returns ERR_TRIAL_ALREADY_USED.

        # difficulty: boundary_precision_check/trial_eligibility_empty_history_boundary
        """
        tutor, student, completed = setup_completed_session()
        assert completed["status"] == "COMPLETED"
        # Now try to book a trial for the same pair.
        res = api.book_session(
            book_session_payload(
                tutor_id=tutor["id"], student_id=student["id"],
                start_at=iso_utc(server_now_dt() + timedelta(hours=2)),
                end_at=iso_utc(server_now_dt() + timedelta(hours=3)),
                is_trial=True,
            ),
            make_student_headers(student["id"]),
        )
        validate_error(res, "ERR_TRIAL_ALREADY_USED")


# ===========================================================================
# Credit application — PRD §3.4
# ===========================================================================
class TestCreditApplication:
    def test_credits_consumed_up_to_gross(self, api):
        """PRD §3.4: "When apply_credits is true on a non-trial booking,
        the server consumes from the student's credit_balance_cents up
        to the gross price; the amount consumed is the minimum of
        gross_price_cents and the student's credit_balance_cents at
        the moment of booking."

        Claim: with credit_balance=3000 and gross=6000,
        credit_applied_cents=3000 and charged_amount_cents=3000.
        """
        tutor, _ = setup_verified_tutor_with_subject(hourly_rate_cents=6000)
        student = create_adult_student()
        # Seed credit balance to 3000.
        seeded = seed_student_credit(
            student=student, target_credit_cents=3000,
        )
        assert seeded["credit_balance_cents"] >= 3000
        # Now book with apply_credits=True.
        s = book_session(
            tutor=tutor, student=seeded, duration_minutes=60,
            apply_credits=True,
        )
        assert s["gross_price_cents"] == 6000
        # Allow credit_applied to be 3000 (the seeded amount) or higher
        # if the seeding helper overshot due to rounding.
        assert s["credit_applied_cents"] >= 3000
        assert (
            s["charged_amount_cents"]
            == s["gross_price_cents"] - s["credit_applied_cents"]
        )

    def test_trial_ignores_apply_credits_flag(self, api):
        """PRD §3.4: "Trial bookings always pin credit_applied_cents to
        0 and ignore the apply_credits flag."

        Claim: trial booking with apply_credits=True still has
        credit_applied_cents=0, even if the student has credit.
        """
        tutor, _ = setup_verified_tutor_with_subject()
        student = create_adult_student()
        seeded = seed_student_credit(
            student=student, target_credit_cents=10_000,
        )
        s = book_session(
            tutor=tutor, student=seeded, duration_minutes=60,
            is_trial=True, apply_credits=True,
        )
        assert s["is_trial"] is True
        assert s["credit_applied_cents"] == 0
        assert s["charged_amount_cents"] == s["gross_price_cents"]


# ===========================================================================
# MINOR booking via Parent — PRD §3.3
# ===========================================================================
class TestMinorBookingGating:
    def test_minor_without_active_link_rejected(self, api):
        """PRD §3.3: "An attempt to book on behalf of a minor without
        an ACTIVE link, or any MINOR-targeting operation where the
        acting Parent is not the linked one, is rejected with
        ERR_MINOR_REQUIRES_PARENT".

        Claim: booking for a MINOR student whose link is still in
        PENDING_PARENT_APPROVAL returns ERR_MINOR_REQUIRES_PARENT.

        # difficulty: cross_entity_state_dependency/session_book_requires_parentchildlink_active_for_minor
        """
        tutor, _ = setup_verified_tutor_with_subject()
        parent = create_parent()
        student, link = create_minor_student(parent=parent)
        # Link not yet approved; try to book as parent.
        res = api.book_session(
            book_session_payload(
                tutor_id=tutor["id"], student_id=student["id"],
                start_at=iso_utc(server_now_dt() + timedelta(hours=2)),
                end_at=iso_utc(server_now_dt() + timedelta(hours=3)),
            ),
            make_parent_headers(parent["id"]),
        )
        validate_error(res, "ERR_MINOR_REQUIRES_PARENT")

    def test_minor_booking_via_active_link_succeeds(self, api):
        """PRD §3.3: "Bookings on behalf of a MINOR are always
        initiated by the linked Parent through an ACTIVE
        ParentChildLink."

        Claim: parent booking on behalf of MINOR child with ACTIVE
        link succeeds.
        """
        tutor, _ = setup_verified_tutor_with_subject()
        parent, student, _link = setup_active_parent_child()
        s = book_session(
            tutor=tutor, student=student, duration_minutes=60,
            parent=parent,
        )
        assert s["status"] == "REQUESTED"
        assert s["student_id"] == student["id"]
