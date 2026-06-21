"""Non-linear dose lifecycle, fork-join adjudication, and the multi-hop
recall and adverse-event cascades."""
from test_helpers import (
    validate_success, get_success_data, ApiErrorId,
    setup_patient_with_doses, setup_submitted_report, issue_recall,
    reverse_recall, setup_certified_patient, run_evaluation,
    setup_adverse_event_under_review, find_antigen_result,
    api_client, make_registrar_headers, create_product_payload,
)

REG = make_registrar_headers()

DTAP = dict(product_code="DTAP", antigen="DTAP", doses_in_series=5,
            min_age_days=42, recommended_age_days=60, min_interval_days=28,
            grace_period_days=4)
C1 = dict(product_code="C1", antigen="C1", doses_in_series=1, min_age_days=0,
          recommended_age_days=0, min_interval_days=0, grace_period_days=4)


class TestImmunizationRecallCycle:
    def test_dose_returns_to_recorded_after_recall_reverse(self, api):
        """PRD §3.9: "every Immunization struck by this recall transitions from
        INVALIDATED back to RECORDED."

        A recalled (INVALIDATED) dose returns to RECORDED status when the recall
        is reversed — the one cycle in the dose lifecycle.

        Design: Difficulty/non_linear_state_machine/immunization_recall_invalidate_then_revalidate_cycle
        """
        _, _, lot, _, doses = setup_patient_with_doses(
            dose_dates=["2025-02-08"],
            product_overrides=create_product_payload(**DTAP),
            patient_overrides={"date_of_birth": "2025-01-01"})
        recall = issue_recall(lot["id"], reason="manufacturer defect")
        reverse_recall(lot["id"], recall["id"])
        dose = get_success_data(api_client.get_immunization(doses[0]["id"], REG))
        assert dose["status"] == "RECORDED", \
            f"expected RECORDED after reverse, got {dose['status']}"

    def test_dose_validity_recomputed_to_valid_after_reverse(self, api):
        """PRD §3.9: "the dose's validity is recomputed by the dose-validity
        replay — which may resolve to VALID or, if interval or age rules now
        fail, to an interval or age failure".

        The single age-valid dose recomputes to VALID after the recall reversal.

        Design: Difficulty/non_linear_state_machine/immunization_recall_invalidate_then_revalidate_cycle
        """
        _, _, lot, _, doses = setup_patient_with_doses(
            dose_dates=["2025-02-08"],
            product_overrides=create_product_payload(**DTAP),
            patient_overrides={"date_of_birth": "2025-01-01"})
        recall = issue_recall(lot["id"], reason="manufacturer defect")
        reverse_recall(lot["id"], recall["id"])
        dose = get_success_data(api_client.get_immunization(doses[0]["id"], REG))
        assert dose["validity"] == "VALID", \
            f"expected VALID after reverse, got {dose['validity']}"


class TestProviderReportForkJoin:
    def test_partial_reject_status_when_one_line_fails(self, api):
        """PRD §3.8: "When at least one line passes and at least one line fails,
        the report transitions from SUBMITTED to PARTIALLY_REJECTED".

        A 2-line report (one good lot, one recalled lot) adjudicates to
        PARTIALLY_REJECTED.

        Design: Difficulty/non_linear_state_machine/provider_report_fork_join_partial_reject
        """
        _, _, lots, _, report = setup_submitted_report(
            lines=[{"lot_key": "main", "administered_date": "2025-06-01"},
                   {"lot_key": "bad", "administered_date": "2025-07-01"}],
            line_count=2,
            product_overrides=create_product_payload(**DTAP),
            patient_overrides={"date_of_birth": "2024-01-01"},
            extra_lots={"bad": {"lot_number": "LF-BAD"}})
        # recall the bad lot before adjudication
        issue_recall(lots["bad"]["id"], reason="recalled before report")
        data = validate_success(
            api_client.adjudicate_provider_report(report["id"], REG))
        assert data["status"] == "PARTIALLY_REJECTED", \
            f"expected PARTIALLY_REJECTED, got {data['status']}"

    def test_partial_reject_split_counts(self, api):
        """PRD §3.8: "an Immunization is materialized only for the accepted lines
        and only those lots' administered_count values are incremented, while
        accepted_count and rejected_count are set to the realized split."

        accepted_count == 1 and rejected_count == 1 for the one-good/one-recalled
        split.

        Design: Difficulty/non_linear_state_machine/provider_report_fork_join_partial_reject
        """
        _, _, lots, _, report = setup_submitted_report(
            lines=[{"lot_key": "main", "administered_date": "2025-06-01"},
                   {"lot_key": "bad", "administered_date": "2025-07-01"}],
            line_count=2,
            product_overrides=create_product_payload(**DTAP),
            patient_overrides={"date_of_birth": "2024-01-01"},
            extra_lots={"bad": {"lot_number": "LF-BAD"}})
        issue_recall(lots["bad"]["id"], reason="recalled before report")
        data = validate_success(
            api_client.adjudicate_provider_report(report["id"], REG))
        assert data["accepted_count"] == 1, \
            f"expected accepted_count 1, got {data['accepted_count']}"
        assert data["rejected_count"] == 1, \
            f"expected rejected_count 1, got {data['rejected_count']}"


class TestRecallTransitiveCascade:
    def test_recall_invalidates_dose_hop_one(self, api):
        """PRD §3.9: "Cascade hop one: every Immunization on the lot that is
        RECORDED or AMENDED transitions to INVALIDATED, its validity is set to
        INVALID_RECALL".

        Design: Difficulty/transitive_cascade/recall_invalidates_dose_recomputes_eval_revokes_cert
        """
        _, _, lot, patient, dose, _evaluation, _cert = setup_certified_patient()
        issue_recall(lot["id"], reason="contamination")
        d = get_success_data(api_client.get_immunization(dose["id"], REG))
        assert d["status"] == "INVALIDATED", \
            f"expected INVALIDATED, got {d['status']}"

    def test_recall_revokes_active_certificate_hop_three(self, api):
        """PRD §3.7: "when a lot recall or a confirmed serious adverse-event
        cascade recomputes a patient's evaluation and the recomputed
        overall_status drops to BEHIND or NON_COMPLIANT, the patient's ACTIVE
        certificate transitions from ACTIVE to REVOKED".

        Design: Difficulty/transitive_cascade/recall_invalidates_dose_recomputes_eval_revokes_cert
        """
        _, _, lot, patient, _dose, _evaluation, cert = setup_certified_patient()
        issue_recall(lot["id"], reason="contamination")
        c = get_success_data(api_client.get_certificate(cert["id"], REG))
        assert c["status"] == "REVOKED", \
            f"expected REVOKED after recall cascade, got {c['status']}"


class TestConfirmedSeriousAeCascade:
    def test_confirmed_serious_ae_creates_contraindication(self, api):
        """PRD §3.5: "Confirming an event whose seriousness is SERIOUS creates,
        as cascade hop one, a CONTRAINDICATED AllergyRecord of origin
        ADVERSE_EVENT on the patient for the dose's product antigen".

        Design: Difficulty/transitive_cascade/confirmed_serious_ae_creates_contraindication_marks_noncompliant
        """
        _, _, _, patient, _dose, ae = setup_adverse_event_under_review(
            "SERIOUS", doses_in_series=2)
        validate_success(api_client.confirm_adverse_event(ae["id"], REG))
        records, _meta = _list_allergy(api, patient["id"])
        ae_records = [r for r in records
                      if r["origin"] == "ADVERSE_EVENT" and r["antigen"] == "C1"]
        assert len(ae_records) == 1, \
            f"expected one ADVERSE_EVENT contraindication, got {records}"
        assert ae_records[0]["severity"] == "CONTRAINDICATED"

    def test_confirmed_serious_ae_marks_evaluation_noncompliant(self, api):
        """PRD §3.5: "the affected antigen is rendered unsatisfiable, so the
        patient's next evaluation marks that antigen, and therefore the overall
        posture, NON_COMPLIANT."

        Design: Difficulty/transitive_cascade/confirmed_serious_ae_creates_contraindication_marks_noncompliant
        """
        _, _, _, patient, _dose, ae = setup_adverse_event_under_review(
            "SERIOUS", doses_in_series=2)
        validate_success(api_client.confirm_adverse_event(ae["id"], REG))
        ev = run_evaluation(patient["id"], "2026-06-01")
        assert ev["overall_status"] == "NON_COMPLIANT", \
            f"expected NON_COMPLIANT, got {ev['overall_status']}"


def _list_allergy(api, patient_id):
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(
        api.list_patient_allergy_records(patient_id, REG))
