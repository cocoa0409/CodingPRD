"""Optimistic concurrency and race-condition tests.

Covers PRD §2.7 (version field) and the four PRD-stated concurrency
outcomes from §3.4, §3.7, §3.8, §3.10.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock_to_check_in_window,
    api_client,
    assert_at_least_one_succeeds,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    cancel_payload,
    complete_registration_lifecycle,
    create_candidate,
    create_event_with_capacity,
    create_registration_payload,
    force_confirmed_registration,
    make_candidate_headers,
    post_score_report,
    reset_clock_to,
    run_race,
    self_cancel,
    submit_and_clear_id,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# Optimistic concurrency on version
# ===========================================================================
class TestVersionConflict:
    def test_stale_version_on_self_cancel_rejected(self, api):
        """PRD §2.7: "Endpoints that modify an existing resource accept
        an optional `version` field in the request body. When the
        client supplies it, the server compares the value to the row's
        current `version`; if they differ, the request is rejected
        with `ERR_VERSION_CONFLICT` and no side effects fire."

        Claim: DELETE /test-events/{id}/registrations/{id} with a stale
        version returns ERR_VERSION_CONFLICT.
        """
        event, center, _ = create_event_with_capacity()
        cand = create_candidate()
        reg = force_confirmed_registration(event["id"], cand, center["id"])
        # Stale version = current - 1 (or 0 since min is 1 — use current - 1 if >= 1).
        stale = max(0, reg["version"] - 1)
        res = api.self_cancel_registration(
            event["id"], reg["id"],
            make_candidate_headers(cand["id"]),
            cancel_payload(version=stale),
        )
        validate_error(res, ApiErrorId.ERR_VERSION_CONFLICT.value)

    def test_omitted_version_skips_check(self, api):
        """PRD §2.7: "When the client omits the field, the server
        proceeds without the check — clients that want last-writer-
        wins semantics can opt out by leaving `version` out of the
        payload."

        Claim: a self-cancel without version in the body succeeds even
        if the row has been mutated and a different version is now
        current.
        """
        event, center, _ = create_event_with_capacity()
        cand = create_candidate()
        reg = force_confirmed_registration(event["id"], cand, center["id"])
        res = api.self_cancel_registration(
            event["id"], reg["id"],
            make_candidate_headers(cand["id"]),
            {},
        )
        data = validate_success(res, 200)
        assert data["status"] == "CANCELLED"


# ===========================================================================
# Race: two CreditsOfficers post the first award for the same ScoreReport
# ===========================================================================
class TestRaceClepDuplicate:
    def test_only_one_clep_award_per_score_report(self, api):
        """PRD §3.10: "two officers racing to post the first award on
        the same score report are serialised first-writer-wins on that
        uniqueness — the loser receives the same code [
        `ERR_CLEP_AWARD_ALREADY_POSTED`]."

        Claim: two parallel POSTs against the same ScoreReport produce
        exactly one success and one ERR_CLEP_AWARD_ALREADY_POSTED.
        """
        reset_clock_to("2026-05-01T00:00:00.000Z")
        cand = create_candidate()
        event, reg = complete_registration_lifecycle(
            cand,
            test_type="CLEP",
            subject="CLEP_BIOLOGY",
            test_date_iso="2026-06-15T09:00:00.000Z",
            registration_deadline="2026-06-01T00:00:00.000Z",
            late_registration_deadline="2026-06-10T00:00:00.000Z",
            score_release_date="2026-06-22T00:00:00.000Z",
        )
        report = post_score_report(
            event["id"], reg["id"],
            section_scores={"composite": 75}, total_score=75,
        )
        results = run_race(
            lambda: api.post_clep_credit(
                event["id"], reg["id"], report["id"],
                TEST_USERS["credits_officer_headers"],
            ),
            lambda: api.post_clep_credit(
                event["id"], reg["id"], report["id"],
                TEST_USERS["credits_officer_headers_alt"],
            ),
        )
        outcome = assert_exactly_one_succeeds(*results)
        loser = outcome["failures"][0]
        validate_error(loser, ApiErrorId.ERR_CLEP_AWARD_ALREADY_POSTED.value)


# ===========================================================================
# Race: Proctor check-in vs Registrar admin-cancel on the same Registration
# ===========================================================================
class TestRaceCheckInVsAdminCancel:
    def test_check_in_and_admin_cancel_serialised(self, api):
        """PRD §3.7: "A `Proctor`'s check-in racing against a
        `Registrar`'s admin cancellation on the same row is serialised
        first-writer-wins on the registration's `status`; the loser
        receives `ERR_INVALID_REGISTRATION_STATE`."

        Claim: exactly one of (check-in, admin-cancel) succeeds; the
        other returns ERR_INVALID_REGISTRATION_STATE.
        """
        event, center, _ = create_event_with_capacity()
        cand = create_candidate(home_state_code="CA")
        reg = force_confirmed_registration(event["id"], cand, center["id"])
        submit_and_clear_id(event["id"], reg["id"], cand)
        advance_clock_to_check_in_window(event["test_date"])

        results = run_race(
            lambda: api.check_in_registration(
                event["id"], reg["id"], TEST_USERS["proctor_headers"],
            ),
            lambda: api.admin_cancel_registration(
                event["id"], reg["id"],
                TEST_USERS["registrar_headers"], {},
            ),
        )
        outcome = assert_exactly_one_succeeds(*results)
        loser = outcome["failures"][0]
        validate_error(loser, ApiErrorId.ERR_INVALID_REGISTRATION_STATE.value)
