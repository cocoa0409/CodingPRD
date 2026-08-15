"""Adherence reporting: dual-variant percentages, threshold boundary, patient
status cycle, review chain guards, and derived-field reconciliation.

Covers PRD §3.4 (adherence reporting and compliance enforcement).
"""
import pytest

from test_helpers import (
    assert_adherence_report,
    finalize_adherence_report,
    finalize_compliant_report,
    finalize_non_compliant_report,
    get_patient,
    ingest_adherence_report,
    setup_therapy_patient,
    validate_error,
    validate_success,
)


class TestAdherenceDualVariant:
    """Provisional (divide by nights reported) vs final (divide by full window)."""

    def test_provisional_divides_by_nights_reported(self, api,
                                                    respiratory_therapist_headers):
        """PRD §3.4: "The **provisional** variant, `adherence_pct_provisional`,
        is available immediately at ingestion and while the report is under
        review: it is the compliant nights divided by the nights actually
        reported, times one hundred"

        Design: Difficulty/dual_variant_calc/adherence_provisional_vs_final_missing_nights
        """
        ctx = setup_therapy_patient()
        report = ingest_adherence_report(ctx["patient"]["id"],
                                         ctx["enrollment"]["id"],
                                         window_end_on="2026-08-30",
                                         nights_reported=25, compliant_nights=18)
        assert_adherence_report(report)
        assert report["report_status"] == "RECEIVED"
        # 18/25 * 100 = 72.0 (missing nights ignored in the provisional variant)
        assert report["adherence_pct_provisional"] == pytest.approx(72.0, abs=1e-6)
        assert report["adherence_pct_final"] is None

        under_review = validate_success(api.begin_review_report(
            report["id"], respiratory_therapist_headers))
        assert under_review["adherence_pct_provisional"] == pytest.approx(72.0, abs=1e-6)

    def test_final_divides_by_full_window(self, api, respiratory_therapist_headers):
        """PRD §3.4: "The **final** variant, `adherence_pct_final`, is computed
        only at finalization: it is the compliant nights divided by the payer's
        full `compliance_window_days`, times one hundred — so nights with no
        data count as non-compliant."

        Design: Difficulty/dual_variant_calc/adherence_provisional_vs_final_missing_nights
        """
        ctx = setup_therapy_patient()
        report = ingest_adherence_report(ctx["patient"]["id"],
                                         ctx["enrollment"]["id"],
                                         window_end_on="2026-08-30",
                                         nights_reported=25, compliant_nights=18)
        finalized = finalize_adherence_report(report["id"])
        assert finalized["report_status"] == "FINALIZED"
        # 18/30 * 100 = 60.0 (missing nights count as non-compliant)
        assert finalized["adherence_pct_final"] == pytest.approx(60.0, abs=1e-6)
        assert finalized["adherence_pct_provisional"] == pytest.approx(72.0, abs=1e-6)
        assert finalized["adherence_pct_final"] != finalized["adherence_pct_provisional"]


class TestComplianceThresholdBoundary:
    def test_exactly_at_threshold_is_compliant(self, api):
        """PRD §3.4: "`is_compliance_current` becomes true exactly when the
        final percentage is **at least** the payer's `compliance_threshold_pct`
        — equality counts as compliant"

        Design: Difficulty/boundary_precision_check/adherence_threshold_inclusive_at_exact_70pct
        """
        ctx = setup_therapy_patient()
        report = ingest_adherence_report(ctx["patient"]["id"],
                                         ctx["enrollment"]["id"],
                                         window_end_on="2026-08-30",
                                         nights_reported=30, compliant_nights=21)
        finalized = finalize_adherence_report(report["id"])
        # 21/30 * 100 = 70.0 — equals the 70% threshold exactly.
        assert finalized["adherence_pct_final"] == pytest.approx(70.0, abs=1e-6)

        patient = get_patient(ctx["patient"]["id"])
        assert patient["adherence_percentage"] == pytest.approx(70.0, abs=1e-6)
        assert patient["is_compliance_current"] is True
        assert patient["patient_status"] == "ACTIVE_THERAPY"

    def test_one_night_below_threshold_triggers_hold(self, api):
        """PRD §3.4: "When a finalized report's `adherence_pct_final` falls
        below the payer threshold, a patient in `ACTIVE_THERAPY` moves to
        `NON_COMPLIANT_HOLD`"

        Design: Difficulty/boundary_precision_check/adherence_threshold_inclusive_at_exact_70pct
        """
        ctx = setup_therapy_patient()
        report = ingest_adherence_report(ctx["patient"]["id"],
                                         ctx["enrollment"]["id"],
                                         window_end_on="2026-08-30",
                                         nights_reported=30, compliant_nights=20)
        finalized = finalize_adherence_report(report["id"])
        # 20/30 * 100 = 66.7 — one compliant night below the threshold.
        assert finalized["adherence_pct_final"] == pytest.approx(66.7, abs=1e-6)

        patient = get_patient(ctx["patient"]["id"])
        assert patient["adherence_percentage"] == pytest.approx(66.7, abs=1e-6)
        assert patient["is_compliance_current"] is False
        assert patient["patient_status"] == "NON_COMPLIANT_HOLD"


class TestPatientStatusCycle:
    def test_non_compliant_finalize_moves_patient_to_hold(self, api):
        """PRD §3.4: "When a finalized report's `adherence_pct_final` falls
        below the payer threshold, a patient in `ACTIVE_THERAPY` moves to
        `NON_COMPLIANT_HOLD`"

        Design: Difficulty/non_linear_state_machine/patient_therapy_status_cycle_via_adherence
        """
        ctx = setup_therapy_patient(acquisition_type="RENTAL")
        patient = get_patient(ctx["patient"]["id"])
        assert patient["patient_status"] == "ACTIVE_THERAPY"

        finalize_non_compliant_report(patient["id"], ctx["enrollment"]["id"],
                                      window_end_on="2026-08-30",
                                      nights_reported=30, compliant_nights=10)
        held = get_patient(patient["id"])
        assert held["patient_status"] == "NON_COMPLIANT_HOLD"
        # 10/30 * 100 = 33.3
        assert held["adherence_percentage"] == pytest.approx(33.3, abs=1e-6)

    def test_compliant_finalize_returns_patient_to_active_therapy(self, api):
        """PRD §3.4: "When a later finalized report meets or exceeds the
        threshold, the patient returns from `NON_COMPLIANT_HOLD` to
        `ACTIVE_THERAPY`"

        Design: Difficulty/non_linear_state_machine/patient_therapy_status_cycle_via_adherence
        """
        ctx = setup_therapy_patient(acquisition_type="RENTAL")
        patient = ctx["patient"]
        enrollment = ctx["enrollment"]
        finalize_non_compliant_report(patient["id"], enrollment["id"],
                                      window_end_on="2026-08-30",
                                      nights_reported=30, compliant_nights=10)
        assert get_patient(patient["id"])["patient_status"] == "NON_COMPLIANT_HOLD"

        finalize_compliant_report(patient["id"], enrollment["id"],
                                  window_end_on="2026-09-15",
                                  nights_reported=30, compliant_nights=25)
        restored = get_patient(patient["id"])
        assert restored["patient_status"] == "ACTIVE_THERAPY"
        # 25/30 * 100 = 83.3
        assert restored["adherence_percentage"] == pytest.approx(83.3, abs=1e-6)


class TestReviewChain:
    def test_finalize_from_received_rejected(self, api, respiratory_therapist_headers):
        """PRD §3.4: "From `UNDER_REVIEW`, the therapist either finalizes or
        rejects; both require the report to be in `UNDER_REVIEW`
        (`ERR_REPORT_NOT_UNDER_REVIEW` otherwise)."

        Design: Corner/state_machines/adherence_report_finalize_from_received_rejected
        """
        ctx = setup_therapy_patient()
        report = ingest_adherence_report(ctx["patient"]["id"],
                                         ctx["enrollment"]["id"],
                                         window_end_on="2026-08-30",
                                         nights_reported=30, compliant_nights=25)
        assert report["report_status"] == "RECEIVED"
        res = api.finalize_report(report["id"], respiratory_therapist_headers)
        validate_error(res, "ERR_REPORT_NOT_UNDER_REVIEW", expected_status=409)

    def test_reject_leaves_patient_fields_untouched(self, api,
                                                    respiratory_therapist_headers):
        """PRD §3.4: "Rejection instead moves the report to `REJECTED` and
        leaves every patient field untouched."

        Design: Corner/state_machines/adherence_report_reject_leaves_patient_unchanged
        """
        ctx = setup_therapy_patient()
        report = ingest_adherence_report(ctx["patient"]["id"],
                                         ctx["enrollment"]["id"],
                                         window_end_on="2026-08-30",
                                         nights_reported=30, compliant_nights=5)
        validate_success(api.begin_review_report(report["id"],
                                                 respiratory_therapist_headers))
        pre = get_patient(ctx["patient"]["id"])
        assert pre["patient_status"] == "ACTIVE_THERAPY"
        assert pre["adherence_percentage"] is None

        rejected = validate_success(api.reject_report(report["id"],
                                                      respiratory_therapist_headers))
        assert rejected["report_status"] == "REJECTED"

        post = get_patient(ctx["patient"]["id"])
        assert post["patient_status"] == "ACTIVE_THERAPY"
        assert post["adherence_percentage"] is None
        assert post["is_compliance_current"] is False


class TestProvisionalEdge:
    def test_provisional_zero_nights_is_zero(self, api):
        """PRD §3.4: "or exactly 0.0 when no nights were reported at all."

        Design: Corner/calculations/adherence_provisional_zero_nights
        """
        ctx = setup_therapy_patient()
        report = ingest_adherence_report(ctx["patient"]["id"],
                                         ctx["enrollment"]["id"],
                                         window_end_on="2026-08-30",
                                         nights_reported=0, compliant_nights=0)
        assert_adherence_report(report)
        assert report["adherence_pct_provisional"] == pytest.approx(0.0, abs=1e-9)


class TestAdherenceDerivedFieldReconciliation:
    def test_latest_finalize_overwrites_adherence_percentage(self, api):
        """PRD §3.2: "`adherence_percentage` and `is_compliance_current`
        reflect the most recent finalized adherence report"

        Design: Corner/cross_cutting_layers/derived_field_adherence_percentage_reconciled_on_finalize
        """
        ctx = setup_therapy_patient()
        patient = ctx["patient"]
        enrollment = ctx["enrollment"]

        ingest_and_finalized_first = ingest_adherence_report(
            patient["id"], enrollment["id"], window_end_on="2026-08-30",
            nights_reported=30, compliant_nights=15)
        finalize_adherence_report(ingest_and_finalized_first["id"])
        after_first = get_patient(patient["id"])
        # 15/30 * 100 = 50.0
        assert after_first["adherence_percentage"] == pytest.approx(50.0, abs=1e-6)

        second = ingest_adherence_report(patient["id"], enrollment["id"],
                                         window_end_on="2026-09-15",
                                         nights_reported=30, compliant_nights=24)
        finalize_adherence_report(second["id"])
        after_second = get_patient(patient["id"])
        # 24/30 * 100 = 80.0 — overwrite, not accumulate.
        assert after_second["adherence_percentage"] == pytest.approx(80.0, abs=1e-6)
        assert after_second["is_compliance_current"] is True

    def test_immediate_consistency_after_finalize(self, api):
        """PRD §3.4: "Finalization re-verifies the window arithmetic
        (`ERR_INVALID_WINDOW` if inconsistent), sets `report_status` to
        `FINALIZED`, records the therapist in `reviewed_by_user_id`, computes
        `adherence_pct_final`, and then settles the patient record:
        `adherence_percentage` becomes the final percentage,
        `is_compliance_current` becomes true exactly when the final percentage
        is **at least** the payer's `compliance_threshold_pct`"

        Design: Corner/consistency_model/immediate_consistency_after_finalize
        """
        ctx = setup_therapy_patient()
        report = ingest_adherence_report(ctx["patient"]["id"],
                                         ctx["enrollment"]["id"],
                                         window_end_on="2026-08-30",
                                         nights_reported=30, compliant_nights=27)
        finalized = finalize_adherence_report(report["id"])
        # 27/30 * 100 = 90.0
        assert finalized["adherence_pct_final"] == pytest.approx(90.0, abs=1e-6)

        # Read immediately after the 200 response: no eventual-consistency lag.
        patient = get_patient(ctx["patient"]["id"])
        assert patient["adherence_percentage"] == pytest.approx(90.0, abs=1e-6)
        assert patient["is_compliance_current"] is True
