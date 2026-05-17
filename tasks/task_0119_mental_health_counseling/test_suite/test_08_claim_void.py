"""Claim void within 7-day window + compensating reversal of deductible
and supervision hours.

PRD §3.8.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    CLAIM_VOID_WINDOW_DAYS,
    INDIVIDUAL_CREDIT_HOURS,
    TEST_USERS,
    advance_clock_to,
    iso_anchor_offset,
    parse_iso,
    re_get_appointment,
    re_get_claim,
    re_get_patient,
    re_get_session,
    re_get_therapist,
    setup_posted_claim_for_void_window,
    validate_error,
    validate_success,
    void_claim,
)
from test_helpers.factories import iso_utc
from datetime import timedelta


class TestClaimVoidWindow:

    def test_void_within_window_succeeds(self, api):
        """PRD §3.8: "A BillingClaim in status = POSTED may be voided
        by a PracticeAdmin or by a BillingClerk, but only when the
        owning session was completed within the last seven days as
        measured against the deterministic clock ..."

        Claim: voiding a claim 6 days after posting succeeds.
        """
        posted_at = "2026-05-01T10:00:00.000Z"
        bundle = setup_posted_claim_for_void_window(
            posted_at_iso=posted_at,
        )
        # Move clock to 6 days after posting (well inside the 7-day
        # window).
        advance_clock_to("2026-05-07T10:00:00.000Z")
        res = api.void_claim(
            bundle["claim"]["id"],
            TEST_USERS["practice_admin_headers"],
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "VOIDED"

    def test_void_at_seven_day_boundary_succeeds(self, api):
        """PRD §3.8: "but only when the owning session was completed
        within the last seven days as measured against the
        deterministic clock; an attempt outside that window is rejected
        with ERR_VOID_WINDOW_EXPIRED."

        Claim: voiding a claim exactly 7 days (168.0 hours) after
        posting is admitted (inclusive boundary), so the claim
        transitions to VOIDED.
        """
        assert CLAIM_VOID_WINDOW_DAYS == 7
        posted_at = "2026-05-01T10:00:00.000Z"
        bundle = setup_posted_claim_for_void_window(
            posted_at_iso=posted_at,
        )
        # Advance clock to exactly +7 days.
        advance_clock_to("2026-05-08T10:00:00.000Z")
        res = api.void_claim(
            bundle["claim"]["id"],
            TEST_USERS["practice_admin_headers"],
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "VOIDED"

    def test_void_strictly_past_seven_days_rejected(self, api):
        """PRD §3.8: "an attempt outside that window is rejected with
        ERR_VOID_WINDOW_EXPIRED."

        Claim: voiding a claim 7 days + 1 second after posting returns
        ERR_VOID_WINDOW_EXPIRED.
        """
        posted_at = "2026-05-01T10:00:00.000Z"
        bundle = setup_posted_claim_for_void_window(
            posted_at_iso=posted_at,
        )
        # +7 days + 1 second.
        advance_clock_to("2026-05-08T10:00:01.000Z")
        res = api.void_claim(
            bundle["claim"]["id"],
            TEST_USERS["practice_admin_headers"],
        )
        validate_error(res, "ERR_VOID_WINDOW_EXPIRED")

    def test_void_already_voided_claim_rejected(self, api):
        """PRD §3.8: "A void on a claim that has already been voided
        is rejected with ERR_CLAIM_NOT_POSTED."

        Claim: voiding a claim that is already VOIDED returns
        ERR_CLAIM_NOT_POSTED.
        """
        bundle = setup_posted_claim_for_void_window()
        void_claim(bundle["claim"]["id"])
        res = api.void_claim(
            bundle["claim"]["id"],
            TEST_USERS["practice_admin_headers"],
        )
        validate_error(res, "ERR_CLAIM_NOT_POSTED")


class TestVoidCompensatingReversal:

    def test_void_restores_patient_deductible(self, api):
        """PRD §3.8: "For an INSURANCE_IN_NETWORK claim, the amount
        previously consumed against the patient's deductible — equal
        to the smaller of charged_amount_cents at posting and
        deductible_remaining_cents at posting — is restored to
        Patient.deductible_remaining_cents."

        Claim: after void, the patient's deductible_remaining_cents
        equals the pre-completion value.
        """
        # 90834 allowed=9550, deductible_remaining=20000 ->
        # min(9550, 20000)=9550 decremented. Post-completion remaining
        # = 10450. After void, remaining must be back to 20000.
        bundle = setup_posted_claim_for_void_window(
            allowed_90834_cents=9_550,
            copay_cents=2_500,
            deductible_remaining_cents=20_000,
        )
        patient_after_post = re_get_patient(bundle["patient"]["id"])
        assert patient_after_post["deductible_remaining_cents"] == 10_450
        void_claim(bundle["claim"]["id"])
        patient_after_void = re_get_patient(bundle["patient"]["id"])
        assert patient_after_void["deductible_remaining_cents"] == 20_000

    def test_void_reverses_supervision_hours(self, api):
        """PRD §3.8: "The therapist's supervision_hours_accrued is
        reduced by the owning session's supervision_credit_hours (1.00
        or 1.50) using the same round-half-up-to-two-decimal-places
        rule, and licensure_exam_eligible is recomputed against the
        reduced total ..."

        Claim: after voiding a 90834 (INDIVIDUAL) session's claim,
        the therapist's supervision_hours_accrued is reduced by 1.00.
        """
        # Use a PRE_LICENSED setup so we exercise the supervision
        # ledger directly.
        from test_helpers import setup_pre_licensed_with_completed_session
        bundle = setup_pre_licensed_with_completed_session(
            rack_90834_cents=10_000,
        )
        therapist_after_post = re_get_therapist(bundle["therapist"]["id"])
        assert therapist_after_post[
            "supervision_hours_accrued"
        ] == pytest.approx(INDIVIDUAL_CREDIT_HOURS, abs=0.01)
        void_claim(bundle["claim"]["id"])
        therapist_after_void = re_get_therapist(bundle["therapist"]["id"])
        assert therapist_after_void[
            "supervision_hours_accrued"
        ] == pytest.approx(0.00, abs=0.01)

    def test_void_marks_session_voided_and_appointment_cancelled(self, api):
        """PRD §3.8: "Finally, the owning session is moved to status =
        VOIDED and the owning appointment is moved to status =
        CANCELLED."

        Claim: after void, Session.status=VOIDED and
        Appointment.status=CANCELLED.
        """
        bundle = setup_posted_claim_for_void_window()
        void_claim(bundle["claim"]["id"])
        session = re_get_session(bundle["session"]["id"])
        assert session["status"] == "VOIDED"
        appt = re_get_appointment(bundle["appointment"]["id"])
        assert appt["status"] == "CANCELLED"
