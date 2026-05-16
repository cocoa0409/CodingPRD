"""Concurrency races and optimistic concurrency control.

Covers PRD §2.7 (OCC version conflicts) and the concurrency guarantees
PRD §3.4 / §3.5 / §3.6 / §3.7 explicitly pin (race outcomes only —
loser error_ids are asserted only when PRD names them).
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock_to,
    assert_at_least_one_succeeds,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    book_session,
    book_session_payload,
    confirm_session,
    create_adult_student,
    iso_utc,
    make_student_headers,
    make_tutor_headers,
    make_tutor_verified,
    mark_payout_paid,
    open_dispute,
    open_dispute_payload,
    parse_iso,
    patch_tutor_payload,
    run_race,
    server_now_dt,
    setup_basic_booking_scenario,
    setup_completed_session,
    setup_confirmed_session,
    setup_settled_session,
    setup_verified_tutor_with_subject,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# OCC version conflict — PRD §2.7
# ===========================================================================
class TestOcc:
    def test_concurrent_patch_one_wins_other_version_conflicts(self, api):
        """PRD §2.7: "When supplied, the server compares it to the
        current version of the target row; mismatch is rejected with
        ERR_VERSION_CONFLICT."

        Claim: two concurrent PATCHes carrying the same `version` field
        result in exactly one success and one ERR_VERSION_CONFLICT.
        """
        from test_helpers import create_tutor
        tutor = create_tutor()
        # Both PATCHes carry version=1; only one can win.
        h = make_tutor_headers(tutor["id"])
        results = run_race(
            lambda: api.patch_tutor(
                tutor["id"],
                patch_tutor_payload(display_name="A", version=1),
                h,
            ),
            lambda: api.patch_tutor(
                tutor["id"],
                patch_tutor_payload(display_name="B", version=1),
                h,
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        # Loser must carry ERR_VERSION_CONFLICT — PRD §2.7 names it.
        loser = outcome["failures"][0]
        validate_error(loser, "ERR_VERSION_CONFLICT")


# ===========================================================================
# Tutor overlapping confirms — PRD §3.5
# ===========================================================================
class TestOverlapRace:
    def test_two_overlapping_confirms_one_wins(self, api):
        """PRD §3.5: "When two overlapping confirms race, exactly one
        wins on the per-tutor_id overlap reservation and the other
        receives ERR_SESSION_OVERLAP."

        Claim: two concurrent confirms of overlapping sessions for the
        same tutor result in one success and one ERR_SESSION_OVERLAP.
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
            start_at=iso_utc(now + timedelta(hours=2, minutes=30)),
            end_at=iso_utc(now + timedelta(hours=3, minutes=30)),
        )
        h = make_tutor_headers(tutor["id"])
        results = run_race(
            lambda: api.confirm_session(a["id"], h),
            lambda: api.confirm_session(b["id"], h),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error(loser, "ERR_SESSION_OVERLAP")


# ===========================================================================
# Trial uniqueness race — PRD §3.4
# ===========================================================================
class TestTrialRace:
    def test_two_trial_bookings_race_one_wins(self, api):
        """PRD §3.4: "When two trial bookings are submitted
        concurrently for the same (tutor_id, student_id) pair, exactly
        one wins and the other receives ERR_TRIAL_ALREADY_USED."

        Claim: two concurrent trial POSTs result in one success and
        one ERR_TRIAL_ALREADY_USED.
        """
        tutor, _ = setup_verified_tutor_with_subject()
        student = create_adult_student()
        h = make_student_headers(student["id"])
        now = server_now_dt()
        payload_a = book_session_payload(
            tutor_id=tutor["id"], student_id=student["id"],
            start_at=iso_utc(now + timedelta(hours=2)),
            end_at=iso_utc(now + timedelta(hours=3)),
            is_trial=True,
        )
        payload_b = book_session_payload(
            tutor_id=tutor["id"], student_id=student["id"],
            start_at=iso_utc(now + timedelta(hours=5)),
            end_at=iso_utc(now + timedelta(hours=6)),
            is_trial=True,
        )
        results = run_race(
            lambda: api.book_session(payload_a, h),
            lambda: api.book_session(payload_b, h),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error(loser, "ERR_TRIAL_ALREADY_USED")


# ===========================================================================
# Duplicate dispute race — PRD §3.7
# ===========================================================================
class TestDisputeRace:
    def test_two_disputes_on_same_session_one_wins(self, api):
        """PRD §3.7: "Two simultaneous attempts to open a dispute
        against the same session serialize so that exactly one wins;
        the loser receives ERR_DISPUTE_ALREADY_OPEN because the
        per-session uniqueness constraint excludes any non-terminal
        dispute."

        Claim: two concurrent open-dispute POSTs result in one success
        and one ERR_DISPUTE_ALREADY_OPEN.
        """
        tutor, student, completed = setup_completed_session()
        h = make_student_headers(student["id"])
        payload = open_dispute_payload(
            session_id=completed["id"],
            requested_amount_cents=1000,
        )
        results = run_race(
            lambda: api.open_dispute(payload, h),
            lambda: api.open_dispute(payload, h),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error(loser, "ERR_DISPUTE_ALREADY_OPEN")


# ===========================================================================
# PayoutBatch double mark-paid — PRD §3.6
# ===========================================================================
class TestPayoutRace:
    def test_two_mark_paid_attempts_one_wins(self, api, admin_headers,
                                             admin_headers_alt):
        """PRD §3.6: "Two simultaneous mark-paid attempts on the same
        batch serialize so that exactly one wins and the loser
        receives ERR_INVALID_STATE because the batch has already left
        REQUESTED."

        Claim: two concurrent mark-paid attempts result in one
        success and one ERR_INVALID_STATE.
        """
        tutor, _student, _settled = setup_settled_session()
        tutor_after = validate_success(
            api.get_tutor(tutor["id"], admin_headers),
        )
        from test_helpers import create_payout, make_admin_headers
        batch = create_payout(tutor=tutor_after)
        # Two distinct payer admins, each different from requested_by.
        h1 = admin_headers_alt
        h2 = make_admin_headers("admin-003")
        results = run_race(
            lambda: api.mark_payout_paid(batch["id"], h1),
            lambda: api.mark_payout_paid(batch["id"], h2),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error(loser, "ERR_INVALID_STATE")
