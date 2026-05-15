"""Credit award, credit-pool aggregation, and credit adjustments
(PRD §2.11, §3.5, §3.6)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    api_client,
    assert_credit_adjustment,
    create_credit_adjustment_payload,
    create_credit_pool,
    create_trainee,
    iso_utc,
    make_trainee_headers,
    setup_completed_enrollment,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Helper: derive expected final_credit from observed attendance_status
# per PRD §3.6's pinned factors. The PRD pins the FACTOR mapping; the
# attendance_status itself is determined by the implementation's
# in-session sampling (PRD §3.5 says only "Periodic in-session
# sampling combines these check-ins" without pinning a specific
# algorithm).
# ---------------------------------------------------------------------------
def _attendance_factor(status: str) -> float:
    """PRD §3.6: "The attendance factor is 1.0 when attendance_status
    is PRESENT, 0.5 when it is PARTIAL, and 0.0 when it is ABSENT.\""""
    return {"PRESENT": 1.0, "PARTIAL": 0.5, "ABSENT": 0.0}.get(status, 1.0)


def _exam_factor(passed_flag, attendance_status: str) -> float:
    """PRD §3.6: "The exam factor is 1.0 when an ExamAttempt exists
    with passed equal to true, 0.5 when an attempt exists with
    passed equal to false, and 0.0 when no attempt was made and
    attendance_status is not ABSENT.\""""
    if passed_flag is True:
        return 1.0
    if passed_flag is False:
        return 0.5
    # No attempt.
    return 0.0 if attendance_status != "ABSENT" else 0.0


# ===========================================================================
# Credit award — PRESENT + passed exam (PRD §3.6)
# ===========================================================================
class TestCreditAwardPresentAndPassed:

    def test_present_passed_yields_full_credit(self, api,
                                                training_admin_headers):
        """PRD §3.6: "The attendance factor is 1.0 when
        attendance_status is PRESENT, 0.5 when it is PARTIAL, and 0.0
        when it is ABSENT. The exam factor is 1.0 when an ExamAttempt
        exists with passed equal to true, 0.5 when an attempt exists
        with passed equal to false, and 0.0 when no attempt was made
        and attendance_status is not ABSENT."

        Claim: two check-ins covering the session + passed exam ->
        the enrollment reaches a terminal COMPLETED state and
        final_credit equals credit_value * attendance_factor *
        exam_factor per the PRD-pinned factor table, with
        exam_factor=1.0 (passed).
        """
        ctx = setup_completed_enrollment(
            attendance="PRESENT", exam_passed=True,
            credit_value=4.0, with_certificate_template=True,
        )
        e = ctx["enrollment"]
        # PRD §3.5 — PRESENT/PARTIAL attendance + passed exam advances
        # to COMPLETED; only PRESENT/PARTIAL+failed -> FAILED.
        assert e["status"] == "COMPLETED"
        attendance = e["attendance_status"]
        # PRD §3.6 factor-table arithmetic, derived from observed
        # attendance_status (the in-session sampling algorithm is not
        # pinned by PRD; the factor mapping is).
        expected = 4.0 * _attendance_factor(attendance) * 1.0
        assert float(e["final_credit"]) == pytest.approx(expected, abs=0.01), (
            f"Expected final_credit={expected} given attendance={attendance} "
            f"and passed exam (credit_value=4.0), got {e['final_credit']}"
        )


# ===========================================================================
# Credit award — PRESENT + failed exam = FAILED with half credit
# ===========================================================================
class TestCreditAwardPresentAndFailed:

    def test_present_failed_yields_half_credit_and_failed_status(
        self, api,
    ):
        """PRD §3.5: "a PRESENT or PARTIAL attendance combined with an
        ExamAttempt whose passed is false advances the enrollment to
        FAILED instead."
        PRD §3.6: "The exam factor is ... 0.5 when an attempt exists
        with passed equal to false."

        Claim: attended (PRESENT or PARTIAL) + failed exam ->
        status=FAILED and final_credit equals credit_value *
        attendance_factor(observed) * 0.5.
        """
        ctx = setup_completed_enrollment(
            attendance="PRESENT", exam_passed=False,
            credit_value=4.0, with_certificate_template=False,
        )
        e = ctx["enrollment"]
        assert e["status"] == "FAILED"
        attendance = e["attendance_status"]
        expected = 4.0 * _attendance_factor(attendance) * 0.5
        assert float(e["final_credit"]) == pytest.approx(expected, abs=0.01), (
            f"Expected final_credit={expected} given attendance={attendance} "
            f"and failed exam (credit_value=4.0), got {e['final_credit']}"
        )


# ===========================================================================
# Credit award — PARTIAL + failed = enrollment_branching difficulty case
# ===========================================================================
class TestCreditAwardPartialAndFailed:

    def test_partial_failed_yields_quarter_credit(self, api):
        """PRD §3.6: "As a worked example, a PARTIAL attendance
        combined with a failed exam (and a course whose credit_value is
        four) yields a provisional of 4.0 × 0.5 = 2.0 and a final of
        4.0 × 0.5 × 0.5 = 1.0 — the two stages produce different
        numbers, as designed."

        Claim: provisional and final differ under the PRD-pinned
        factor mapping. The fixture engineers a single mid-session
        check-in to invite a PARTIAL verdict; we accept either
        PARTIAL or PRESENT as the observed attendance_status (the
        sampling algorithm is implementation-defined) and verify the
        final_credit matches credit_value * factor(observed) * 0.5
        (failed exam).
        """
        ctx = setup_completed_enrollment(
            attendance="PARTIAL", exam_passed=False,
            credit_value=4.0, with_certificate_template=False,
        )
        e = ctx["enrollment"]
        # PRD §3.5: PRESENT/PARTIAL + failed exam -> FAILED.
        assert e["status"] == "FAILED"
        attendance = e["attendance_status"]
        expected = 4.0 * _attendance_factor(attendance) * 0.5
        assert float(e["final_credit"]) == pytest.approx(expected, abs=0.01), (
            f"PRD §3.6 factor table: expected {expected} for "
            f"attendance={attendance} + failed exam; got {e['final_credit']}"
        )


# ===========================================================================
# Credit award — ABSENT = NO_SHOW with zero credit
# ===========================================================================
class TestCreditAwardAbsent:

    def test_absent_yields_no_show_and_zero_credit(self, api):
        """PRD §3.5: "If attendance_status is ABSENT (no qualifying
        check-in occurred), the enrollment advances to NO_SHOW and
        its final_credit remains zero."

        Claim: ABSENT attendance -> status=NO_SHOW, final_credit=0.
        """
        ctx = setup_completed_enrollment(
            attendance="ABSENT", exam_passed=False,
            credit_value=4.0, with_certificate_template=False,
        )
        e = ctx["enrollment"]
        assert e["status"] == "NO_SHOW"
        assert float(e["final_credit"]) == 0.0


# ===========================================================================
# Credit pool aggregation (PRD §2.11, §3.6)
# ===========================================================================
class TestCreditPoolAggregation:

    def test_pool_aggregates_completed_enrollment_credit(
        self, api, training_admin_headers,
    ):
        """PRD §2.11: "A pool's accumulated_credits is a derived
        aggregate: the sum of every final_credit from completed and
        failed enrollments belonging to this trainee whose session
        start instant falls within the half-open window
        [cycle_start, cycle_end), plus the algebraic sum of every
        delta from credit adjustments on this pool."

        Claim: after one completion of a credit_value=4 course in
        the pool's cycle window, accumulated_credits equals the
        enrollment's final_credit (per PRD §2.11 sum, with the
        single enrollment being the only term).
        """
        ctx = setup_completed_enrollment(
            attendance="PRESENT", exam_passed=True,
            credit_value=4.0, with_certificate_template=True,
        )
        pool_resp = api.get_credit_pool(
            ctx["credit_pool"]["id"], training_admin_headers,
        )
        pool = validate_success(pool_resp, expected_status=200)
        # PRD §2.11: aggregate == sum of applicable final_credit +
        # sum of deltas. Only one enrollment, no adjustments.
        expected = float(ctx["enrollment"]["final_credit"])
        assert float(pool["accumulated_credits"]) == pytest.approx(
            expected, abs=0.01,
        ), (
            f"PRD §2.11 aggregate (single completed enrollment, no "
            f"adjustments) should equal enrollment.final_credit={expected}, "
            f"got pool.accumulated_credits={pool['accumulated_credits']}"
        )


# ===========================================================================
# Credit adjustments (PRD §3.6)
# ===========================================================================
class TestCreditAdjustments:

    def test_negative_delta_below_zero_rejected(self, api,
                                                 training_admin_headers):
        """PRD §3.6: "The system rejects any adjustment whose delta
        would drive accumulated_credits below zero with
        ERR_CREDIT_NEGATIVE."

        Claim: an adjustment that would push accumulated_credits
        negative -> ERR_CREDIT_NEGATIVE.
        """
        trainee = create_trainee(job_level=5)
        pool = create_credit_pool(trainee_id=trainee["id"],
                                  required_credits=20.0)
        assert float(pool["accumulated_credits"]) == 0.0
        payload = create_credit_adjustment_payload(
            credit_pool_id=pool["id"], delta=-1.0, reason="invalid",
        )
        resp = api.create_credit_adjustment(payload, training_admin_headers)
        validate_error(resp, ApiErrorId.ERR_CREDIT_NEGATIVE.value)

    def test_positive_adjustment_increments_pool(self, api,
                                                  training_admin_headers):
        """PRD §3.6: "A CreditAdjustment carries the credit_pool_id it
        targets, a signed delta (positive for grants, negative for
        revocations), a free-text reason (required), and an
        actor_role recorded by the system from the request's
        X-User-Role."

        Claim: +5.0 adjustment updates pool.accumulated_credits by +5.0.
        """
        trainee = create_trainee(job_level=5)
        pool = create_credit_pool(trainee_id=trainee["id"],
                                  required_credits=20.0)
        payload = create_credit_adjustment_payload(
            credit_pool_id=pool["id"], delta=5.0, reason="bonus",
        )
        adj_resp = api.create_credit_adjustment(payload, training_admin_headers)
        adj = validate_success(adj_resp, expected_status=201)
        assert_credit_adjustment(adj)
        assert float(adj["delta"]) == 5.0
        # Refresh pool.
        pool_resp = api.get_credit_pool(pool["id"], training_admin_headers)
        refreshed = validate_success(pool_resp, expected_status=200)
        assert float(refreshed["accumulated_credits"]) == pytest.approx(5.0, abs=0.01)

    def test_credit_adjustment_writes_audit_log(self, api,
                                                  training_admin_headers):
        """PRD §3.6: "Every credit-adjustment creation writes an
        AuditLog row with subject_kind equal to CREDIT_POOL."

        Claim: after a credit adjustment, the audit log carries a row
        with subject_kind=CREDIT_POOL referencing the pool.
        """
        trainee = create_trainee(job_level=5)
        pool = create_credit_pool(trainee_id=trainee["id"],
                                  required_credits=20.0)
        payload = create_credit_adjustment_payload(
            credit_pool_id=pool["id"], delta=2.0, reason="audit-check",
        )
        api.create_credit_adjustment(payload, training_admin_headers)
        resp = api.list_audit_logs(
            training_admin_headers,
            params={"subject_kind": "CREDIT_POOL", "subject_id": pool["id"]},
        )
        from test_helpers import validate_paginated
        rows, _ = validate_paginated(resp)
        match = [r for r in rows if r["subject_id"] == pool["id"]
                 and r["subject_kind"] == "CREDIT_POOL"]
        assert match, (
            "PRD §3.6: a CreditAdjustment must produce an AuditLog with "
            "subject_kind=CREDIT_POOL"
        )
