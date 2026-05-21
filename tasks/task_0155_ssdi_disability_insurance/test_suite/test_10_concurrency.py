"""Concurrency / race-condition tests.

Covers PRD §3.4 (determination race), §3.6 (appeal race), §3.7 (slot
booking race), §3.8 (CDR schedule race). Each case is one that PRD prose
explicitly commits to a serialization outcome.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    appeal_payload,
    assert_exactly_one_succeeds,
    book_hearing_slot_payload,
    book_slot,
    complete_cdr_payload,
    create_determination_payload,
    create_open_slot,
    current_clock,
    make_alj_headers,
    make_claimant_headers,
    run_race,
    setup_application_at_alj_pending,
    setup_application_initial_denied,
    setup_application_at_initial_review,
    setup_application_with_pending_cdr,
    validate_error_is_one_of,
)


class TestDeterminationRace:

    def test_two_initial_determinations_one_wins(self, api):
        """PRD §3.4: "If two DDS_Examiner operators race to issue
        determinations against the same INITIAL_REVIEW application —
        for example, one ALLOW and one DENY arriving concurrently —
        the system serialises them first-writer-wins on the
        Application status transition; exactly one transition
        succeeds, and the losing request finds the application no
        longer in INITIAL_REVIEW and is rejected with
        ERR_INVALID_STATE at HTTP status 409."
        """
        claimant, application, _ = setup_application_at_initial_review()
        # Two different DDS examiners (avoid SoD concern; only relevant
        # at RECONSIDERATION anyway).
        allow_payload = create_determination_payload(
            level="INITIAL", decision="ALLOW",
            medical_basis="MEETS_LISTING",
            established_onset_date=claimant["alleged_onset_date"],
        )
        deny_payload = create_determination_payload(
            level="INITIAL", decision="DENY",
            medical_basis="NOT_DISABLED",
        )
        results = run_race(
            lambda: api.create_determination(
                claimant["id"], application["id"], allow_payload,
                TEST_USERS["dds_examiner_headers"],
            ),
            lambda: api.create_determination(
                claimant["id"], application["id"], deny_payload,
                TEST_USERS["dds_examiner_2_headers"],
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        # PRD names the loser's error: ERR_INVALID_STATE.
        loser = outcome["failures"][0]
        validate_error_is_one_of(
            loser, [ApiErrorId.ERR_INVALID_STATE.value],
        )


class TestSlotBookingRace:

    def test_two_alj_books_one_slot_one_wins(self, api):
        """PRD §3.7: "When two ALJ operators race to book the same OPEN
        slot, the system serialises first-writer-wins on the slot's
        transition; the loser is rejected with
        ERR_HEARING_SLOT_CONFLICT at 409."
        """
        claimant_a, app_a = setup_application_at_alj_pending()
        claimant_b, app_b = setup_application_at_alj_pending()
        alj = "alj-race-1"
        T = current_clock() + timedelta(hours=10)
        slot = create_open_slot(alj_id=alj, start_at_dt=T)
        headers = make_alj_headers(alj)
        results = run_race(
            lambda: api.book_hearing_slot(
                slot["id"],
                book_hearing_slot_payload(app_a["id"]), headers,
            ),
            lambda: api.book_hearing_slot(
                slot["id"],
                book_hearing_slot_payload(app_b["id"]), headers,
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error_is_one_of(
            loser, [ApiErrorId.ERR_HEARING_SLOT_CONFLICT.value],
        )


class TestCDRScheduleRace:

    def test_two_cdr_reviewers_one_wins(self, api):
        """PRD §3.8: "When two CDR reviewers race to schedule the same
        review, the system serialises first-writer-wins on the PENDING
        to SCHEDULED transition; the loser is rejected with
        ERR_INVALID_STATE at 409."
        """
        from test_helpers import advance_clock_to, parse_iso, CDR_NOT_DUE_GRACE_DAYS
        claimant, application, cdr = setup_application_with_pending_cdr()
        due = parse_iso(cdr["review_due_date"])
        advance_clock_to(due - timedelta(days=CDR_NOT_DUE_GRACE_DAYS - 1))
        results = run_race(
            lambda: api.schedule_cdr_review(
                cdr["id"], TEST_USERS["cdr_reviewer_headers"],
            ),
            lambda: api.schedule_cdr_review(
                cdr["id"], TEST_USERS["cdr_reviewer_2_headers"],
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error_is_one_of(
            loser, [ApiErrorId.ERR_INVALID_STATE.value],
        )


class TestAppealRace:

    def test_two_appeal_posts_one_wins(self, api):
        """PRD §3.6: "When two appeal requests race against the same
        denied application, the system serialises them first-writer-
        wins on the application's status advance; the loser sees
        status already advanced and is rejected with
        ERR_INVALID_STATE at 409."
        """
        claimant, application = setup_application_initial_denied()
        payload = appeal_payload(target_level="RECONSIDERATION")
        headers = make_claimant_headers(claimant["id"])
        results = run_race(
            lambda: api.appeal_application(
                claimant["id"], application["id"], payload, headers,
            ),
            lambda: api.appeal_application(
                claimant["id"], application["id"], payload, headers,
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error_is_one_of(
            loser, [ApiErrorId.ERR_INVALID_STATE.value],
        )
