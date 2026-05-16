"""CLEP credit award tests.

Covers PRD §3.10 — CLEP parent context, subject map, recommended-score
threshold (boundary at exact equality awarded), credit_units lookup,
posted_by_user_id audit field, immutability.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    CREDITS_OFFICER_ID,
    TEST_USERS,
    api_client,
    assert_clep_credit_award,
    complete_registration_lifecycle,
    create_candidate,
    make_candidate_headers,
    make_credits_officer_headers,
    post_score_report,
    reset_clock_to,
    validate_error,
    validate_success,
)


def _complete_clep_event_with_score(cand, subject, total_score,
                                    test_date_iso="2026-06-15T09:00:00.000Z",
                                    registration_deadline_iso="2026-06-01T00:00:00.000Z",
                                    late_registration_deadline_iso="2026-06-10T00:00:00.000Z",
                                    score_release_iso="2026-06-22T00:00:00.000Z"):
    """Drive a CLEP event through to COMPLETED and post a score report."""
    event, reg = complete_registration_lifecycle(
        cand,
        test_type="CLEP",
        subject=subject,
        test_date_iso=test_date_iso,
        registration_deadline=registration_deadline_iso,
        late_registration_deadline=late_registration_deadline_iso,
        score_release_date=score_release_iso,
    )
    report = post_score_report(
        event["id"], reg["id"],
        section_scores={"composite": total_score},
        total_score=total_score,
    )
    return event, reg, report


# ===========================================================================
# Threshold boundary — total_score == 50 is AWARDED (>=)
# ===========================================================================
class TestCLEPThresholdBoundary:
    def test_score_at_threshold_awarded(self, api):
        """PRD §3.10: "If the parent `ScoreReport.total_score` is at
        least the recommended score for the subject (the boundary at
        exact equality is awarded, not denied), the award's
        `credit_status` is `AWARDED` and `credit_units` is set from
        the credit-units table".

        Claim: total_score == 50 for CLEP_COLLEGE_ALGEBRA yields
        AWARDED with credit_units=3.
        """
        reset_clock_to("2026-05-01T00:00:00.000Z")
        cand = create_candidate()
        event, reg, report = _complete_clep_event_with_score(
            cand, subject="CLEP_COLLEGE_ALGEBRA", total_score=50,
        )
        res = api.post_clep_credit(
            event["id"], reg["id"], report["id"],
            TEST_USERS["credits_officer_headers"],
        )
        award = validate_success(res, 201)
        assert_clep_credit_award(award)
        assert award["credit_status"] == "AWARDED"
        assert award["credit_units"] == 3, (
            "PRD §3.10: CLEP_COLLEGE_ALGEBRA awards 3 credit units"
        )
        assert award["posted_by_user_id"] == CREDITS_OFFICER_ID

    def test_score_just_below_threshold_denied(self, api):
        """PRD §3.10: "otherwise `credit_status` is `DENIED` and
        `credit_units` is zero."

        Claim: total_score == 49 for CLEP_COLLEGE_ALGEBRA yields
        DENIED with credit_units=0.
        """
        reset_clock_to("2026-05-01T00:00:00.000Z")
        cand = create_candidate()
        event, reg, report = _complete_clep_event_with_score(
            cand, subject="CLEP_COLLEGE_ALGEBRA", total_score=49,
        )
        res = api.post_clep_credit(
            event["id"], reg["id"], report["id"],
            TEST_USERS["credits_officer_headers"],
        )
        award = validate_success(res, 201)
        assert award["credit_status"] == "DENIED"
        assert award["credit_units"] == 0

    @pytest.mark.parametrize("subject,expected_units", [
        ("CLEP_COLLEGE_ALGEBRA", 3),
        ("CLEP_AMERICAN_GOVERNMENT", 3),
        ("CLEP_BIOLOGY", 6),
        ("CLEP_CHEMISTRY", 6),
        ("CLEP_COLLEGE_COMPOSITION", 6),
    ])
    def test_credit_units_lookup_per_subject(self, api, subject, expected_units):
        """PRD §3.10: "the credit-units table assigns 3 units to
        `CLEP_COLLEGE_ALGEBRA` and `CLEP_AMERICAN_GOVERNMENT`, and 6
        units to `CLEP_BIOLOGY`, `CLEP_CHEMISTRY`, and
        `CLEP_COLLEGE_COMPOSITION`."

        Claim: each subject's AWARDED row carries the expected
        credit_units.
        """
        reset_clock_to("2026-05-01T00:00:00.000Z")
        cand = create_candidate()
        event, reg, report = _complete_clep_event_with_score(
            cand, subject=subject, total_score=75,
        )
        res = api.post_clep_credit(
            event["id"], reg["id"], report["id"],
            TEST_USERS["credits_officer_headers"],
        )
        award = validate_success(res, 201)
        assert award["credit_status"] == "AWARDED"
        assert award["credit_units"] == expected_units


# ===========================================================================
# Wrong test_type
# ===========================================================================
class TestCLEPInvalidContext:
    def test_post_clep_credit_against_sat_rejected(self, api):
        """PRD §3.10: "The parent `TestEvent`'s `test_type` must be
        `CLEP`; otherwise the post is rejected with
        `ERR_CLEP_INVALID_CONTEXT`."

        Claim: posting CLEP credit against a SAT ScoreReport returns
        ERR_CLEP_INVALID_CONTEXT.
        """
        reset_clock_to("2026-05-01T00:00:00.000Z")
        cand = create_candidate()
        event, reg = complete_registration_lifecycle(cand, test_type="SAT")
        report = post_score_report(
            event["id"], reg["id"],
            section_scores={"reading_writing": 600, "math": 700},
            total_score=1300,
        )
        res = api.post_clep_credit(
            event["id"], reg["id"], report["id"],
            TEST_USERS["credits_officer_headers"],
        )
        validate_error(res, ApiErrorId.ERR_CLEP_INVALID_CONTEXT.value)


# ===========================================================================
# Duplicate post is rejected
# ===========================================================================
class TestCLEPDuplicate:
    def test_second_clep_post_for_same_score_report_rejected(self, api):
        """PRD §3.10: "The award row is keyed uniquely by
        `score_report_id`; a second post for the same score report is
        rejected with `ERR_CLEP_AWARD_ALREADY_POSTED`".

        Claim: a second clep-credit POST for the same score report
        returns ERR_CLEP_AWARD_ALREADY_POSTED.
        """
        reset_clock_to("2026-05-01T00:00:00.000Z")
        cand = create_candidate()
        event, reg, report = _complete_clep_event_with_score(
            cand, subject="CLEP_BIOLOGY", total_score=60,
        )
        # First post.
        validate_success(api.post_clep_credit(
            event["id"], reg["id"], report["id"],
            TEST_USERS["credits_officer_headers"],
        ), 201)
        # Second post.
        res = api.post_clep_credit(
            event["id"], reg["id"], report["id"],
            TEST_USERS["credits_officer_headers"],
        )
        validate_error(res, ApiErrorId.ERR_CLEP_AWARD_ALREADY_POSTED.value)


# ===========================================================================
# posted_by_user_id captured on DENIED outcomes too
# ===========================================================================
class TestPostedByCaptured:
    def test_denied_award_also_records_posted_by(self, api):
        """PRD §3.10: "The award row also records ... `posted_by_user_id`
        set from the officer's `X-User-ID` — the field is recorded on
        both `AWARDED` and `DENIED` outcomes."

        Claim: a DENIED CLEP award still records posted_by_user_id.
        """
        reset_clock_to("2026-05-01T00:00:00.000Z")
        cand = create_candidate()
        event, reg, report = _complete_clep_event_with_score(
            cand, subject="CLEP_CHEMISTRY", total_score=30,
        )
        custom = make_credits_officer_headers("credits-officer-custom-1")
        res = api.post_clep_credit(
            event["id"], reg["id"], report["id"], custom,
        )
        award = validate_success(res, 201)
        assert award["credit_status"] == "DENIED"
        assert award["posted_by_user_id"] == "credits-officer-custom-1", (
            "PRD §3.10: posted_by_user_id is recorded on AWARDED and DENIED outcomes"
        )
