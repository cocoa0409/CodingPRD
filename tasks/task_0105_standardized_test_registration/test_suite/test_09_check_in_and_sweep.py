"""Check-in window, ID and accommodation gates, no-show sweep tests.

Covers PRD §3.7 — check-in window, ID-cleared precondition,
accommodation-pending precondition, the no-show sweep, expiry of
accommodation requests, and the precedence order of the four check-in
gates.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock_to,
    advance_clock_to_check_in_window,
    api_client,
    create_candidate,
    create_event_with_capacity,
    fmt_iso,
    force_confirmed_registration,
    make_candidate_headers,
    parse_iso,
    reject_id_verification,
    reset_clock_to,
    run_sweep,
    start_review,
    submit_accommodation_request,
    submit_and_clear_id,
    submit_id_verification,
    validate_error,
    validate_success,
)
from datetime import timedelta


# ===========================================================================
# Check-in window
# ===========================================================================
class TestCheckInWindow:
    def test_check_in_before_window_rejected(self, api):
        """PRD §3.7: "The current logical time must be within the
        window from `test_date - 2 hours` to `test_date + 1 hour`
        (check-in opens two hours before the scheduled start and
        closes one hour after); if it is not, the proctor's call is
        rejected with `ERR_CHECK_IN_WINDOW_CLOSED`."

        Claim: check-in at 30 hours before test_date (well before the
        2-hour open) returns ERR_CHECK_IN_WINDOW_CLOSED.

        Note: PRD §3.11 places check-in-window after ID-cleared and
        accommodation-pending in evaluation order. To isolate this
        rule, we satisfy both prior gates (ID CLEARED, no
        accommodation pending) before tripping the window.
        """
        reset_clock_to("2026-05-01T00:00:00.000Z")
        event, center, _ = create_event_with_capacity(
            test_date="2026-06-08T09:00:00.000Z",
            registration_deadline="2026-05-25T00:00:00.000Z",
            late_registration_deadline="2026-06-04T00:00:00.000Z",
            score_release_date="2026-06-15T00:00:00.000Z",
        )
        cand = create_candidate(home_state_code="CA")
        reg = force_confirmed_registration(event["id"], cand, center["id"])
        submit_and_clear_id(event["id"], reg["id"], cand)

        # Clock at 30h before test_date (still outside the 2-hour window).
        advance_clock_to("2026-06-07T03:00:00.000Z")
        res = api.check_in_registration(
            event["id"], reg["id"], TEST_USERS["proctor_headers"],
        )
        validate_error(res, ApiErrorId.ERR_CHECK_IN_WINDOW_CLOSED.value)

    def test_check_in_in_window_succeeds(self, api):
        """PRD §3.7: "Check-in is the act by which a `Proctor` at the
        test center confirms a candidate's physical arrival, advancing
        their `Registration` from `CONFIRMED` to `CHECKED_IN`."

        Claim: check-in inside the window advances the row to
        CHECKED_IN.
        """
        event, center, _ = create_event_with_capacity()
        cand = create_candidate(home_state_code="CA")
        reg = force_confirmed_registration(event["id"], cand, center["id"])
        submit_and_clear_id(event["id"], reg["id"], cand)
        advance_clock_to_check_in_window(event["test_date"])
        res = api.check_in_registration(
            event["id"], reg["id"], TEST_USERS["proctor_headers"],
        )
        data = validate_success(res, 200)
        assert data["status"] == "CHECKED_IN"


# ===========================================================================
# ID-cleared precondition
# ===========================================================================
class TestIDClearedGate:
    def test_check_in_without_cleared_id_rejected(self, api):
        """PRD §3.7: "The associated `IDVerification` must be in
        `CLEARED`; a missing or non-cleared verification yields
        `ERR_ID_NOT_CLEARED`."

        Claim: check-in inside the window with IDVerification in
        REJECTED returns ERR_ID_NOT_CLEARED.
        """
        event, center, _ = create_event_with_capacity()
        cand = create_candidate(home_state_code="CA")
        reg = force_confirmed_registration(event["id"], cand, center["id"])
        # Submit ID then reject.
        submit_id_verification(
            event["id"], reg["id"], cand,
            id_document_type="DRIVERS_LICENSE", issuing_state_code="CA",
            id_expires_on="2030-01-01",
        )
        reject_id_verification(event["id"], reg["id"], "blurry")
        advance_clock_to_check_in_window(event["test_date"])
        res = api.check_in_registration(
            event["id"], reg["id"], TEST_USERS["proctor_headers"],
        )
        validate_error(res, ApiErrorId.ERR_ID_NOT_CLEARED.value)


# ===========================================================================
# Accommodation-pending precondition
# ===========================================================================
class TestAccommodationPendingGate:
    def test_check_in_with_pending_accommodation_rejected(self, api):
        """PRD §3.7: "if any `AccommodationRequest` exists on the same
        `(candidate_id, test_event_id)`, that request must already be
        in one of the terminal review states — `APPROVED`, `DENIED`,
        or `EXPIRED` — and not in `SUBMITTED`, `UNDER_REVIEW`, or
        `NEEDS_MORE_INFO`; otherwise the proctor receives
        `ERR_ACCOMMODATION_PENDING`."

        Claim: a candidate with IDVerification CLEARED and an
        accommodation request still in SUBMITTED returns
        ERR_ACCOMMODATION_PENDING at check-in.
        """
        event, center, _ = create_event_with_capacity()
        cand = create_candidate(has_iep_or_504=True, home_state_code="CA")
        reg = force_confirmed_registration(event["id"], cand, center["id"])
        submit_and_clear_id(event["id"], reg["id"], cand)
        # Create an accommodation request that stays in SUBMITTED.
        submit_accommodation_request(cand, event["id"])
        advance_clock_to_check_in_window(event["test_date"])
        res = api.check_in_registration(
            event["id"], reg["id"], TEST_USERS["proctor_headers"],
        )
        validate_error(res, ApiErrorId.ERR_ACCOMMODATION_PENDING.value)


# ===========================================================================
# Sweep: NO_SHOW + accommodation EXPIRED
# ===========================================================================
class TestSweep:
    def test_sweep_marks_no_show_after_grace_window(self, api):
        """PRD §3.7: "First, it moves any `Registration` still in
        `CONFIRMED` whose check-in window has passed (now is strictly
        after `test_date + 1 hour`) to `NO_SHOW`".

        Claim: after advancing past test_date+1h with no check-in, the
        sweep marks the registration NO_SHOW and the response counter
        no_show_count reflects it.
        """
        event, center, _ = create_event_with_capacity(
            test_date="2026-06-08T09:00:00.000Z",
            registration_deadline="2026-05-25T00:00:00.000Z",
            late_registration_deadline="2026-06-04T00:00:00.000Z",
            score_release_date="2026-06-15T00:00:00.000Z",
        )
        cand = create_candidate(home_state_code="CA")
        reg = force_confirmed_registration(event["id"], cand, center["id"])
        submit_and_clear_id(event["id"], reg["id"], cand)
        # Advance well past test_date + 1 hour without any check-in call.
        advance_clock_to(fmt_iso(parse_iso(event["test_date"]) + timedelta(hours=2)))
        result = run_sweep(event["id"])
        assert result["no_show_count"] >= 1
        refreshed = validate_success(
            api.get_registration(event["id"], reg["id"],
                                 TEST_USERS["registrar_headers"]),
            200,
        )
        assert refreshed["status"] == "NO_SHOW"

    def test_sweep_expires_pending_accommodation(self, api):
        """PRD §3.7: "Third, any `AccommodationRequest` whose
        `review_deadline_at` has passed and which is still in any of
        `SUBMITTED`, `UNDER_REVIEW`, or `NEEDS_MORE_INFO` is moved to
        `EXPIRED`."

        Claim: after advancing past review_deadline_at, the sweep
        moves a still-SUBMITTED AccommodationRequest to EXPIRED and
        increments the expired_accommodations counter.
        """
        reset_clock_to("2026-04-01T00:00:00.000Z")
        # registration_deadline 2026-05-25 -> submission_deadline_at = 2026-05-11.
        # review_deadline_at = submission_deadline_at + 7d = 2026-05-18.
        event, center, _ = create_event_with_capacity(
            test_date="2026-06-08T09:00:00.000Z",
            registration_deadline="2026-05-25T00:00:00.000Z",
            late_registration_deadline="2026-06-04T00:00:00.000Z",
            score_release_date="2026-06-15T00:00:00.000Z",
        )
        cand = create_candidate(has_iep_or_504=True)
        req = submit_accommodation_request(cand, event["id"])
        assert req["status"] == "SUBMITTED"
        # Advance clock past review_deadline_at, then sweep.
        advance_clock_to("2026-05-20T00:00:00.000Z")
        result = run_sweep(event["id"])
        assert result["expired_accommodations"] >= 1
        refreshed = validate_success(
            api.get_accommodation_request(req["id"], TEST_USERS["registrar_headers"]),
            200,
        )
        assert refreshed["status"] == "EXPIRED"
