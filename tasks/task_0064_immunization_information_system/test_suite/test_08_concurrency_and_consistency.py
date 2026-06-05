"""Optimistic concurrency on certificate issuance, derived-field reconciliation
after a recall, and the immediate (atomic) recall cascade."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    setup_evaluated_patient, issue_certificate, run_evaluation, issue_recall,
    setup_patient_with_doses, create_product, create_provider, create_lot,
    create_patient, set_clock, record_dose, api_client, make_registrar_headers,
    create_product_payload,
)

REG = make_registrar_headers()
C1 = dict(product_code="C1", antigen="C1", doses_in_series=1, min_age_days=0,
          recommended_age_days=0, min_interval_days=0)


def _setup_up_to_date_patient():
    """Single-dose-compliant patient + UP_TO_DATE evaluation. Returns
    (patient_id, evaluation_id, patient_version, lot_id)."""
    (_p, _prov, lot, patient, _doses, ev, pv) = setup_evaluated_patient(
        as_of_date="2026-06-01", dose_dates=["2025-01-01"],
        product_overrides=create_product_payload(**C1),
        patient_overrides={"date_of_birth": "2024-01-01"})
    return patient["id"], ev["id"], pv, lot["id"]


def test_occ_correct_version_issues_certificate(api):
    """PRD §2.10: "A certificate-issuance request must carry
    expected_patient_version as a non-optional field, and that value must equal
    the target patient's current version."
    PRD §3.7: "The certificate's certificate_type is derived from the snapshot:
    COMPLETE when the evaluation is UP_TO_DATE".

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_issues_certificate
    """
    patient_id, eval_id, pv, _lot = _setup_up_to_date_patient()
    data = validate_success(
        issue_certificate(patient_id, eval_id, pv), expected_status=201)
    assert data["certificate_type"] == "COMPLETE", f"got {data['certificate_type']}"
    assert data["status"] == "ACTIVE", f"got {data['status']}"


def test_occ_stale_version_rejected_on_second_issue(api):
    """PRD §2.10: "If it does not match — for example because an earlier issuance
    has already superseded the patient's prior certificate and thereby
    incremented the patient's version while changing active_certificate_id — the
    request is rejected with ERR_STALE_PATIENT_VERSION (HTTP 412)".

    A second issuance carrying the pre-issue version is rejected.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_rejected_on_second_issue
    """
    patient_id, eval_id, pv, _lot = _setup_up_to_date_patient()
    validate_success(issue_certificate(patient_id, eval_id, pv),
                     expected_status=201)
    validate_error(issue_certificate(patient_id, eval_id, pv),
                   ApiErrorId.ERR_STALE_PATIENT_VERSION.value)


def test_schedule_status_reconciled_after_recall(api):
    """PRD §2.6: "A Patient carries schedule_status, a copy of the overall_status
    of that patient's most recent ScheduleEvaluation".
    PRD §3.6: "then copies the resulting overall_status onto the patient's
    schedule_status".

    After a recall invalidates the patient's only dose, a re-run evaluation
    drops overall_status and Patient.schedule_status to BEHIND.

    Design: Corner/cross_cutting_complexity_layers/derived_schedule_status_reconciled_after_recall
    """
    set_clock("2026-06-01T00:00:00Z")
    product = create_product(**create_product_payload(**C1))
    provider = create_provider(authorized_product_codes=["C1"])
    lot = create_lot(product["id"])
    patient = create_patient(date_of_birth="2024-01-01")
    record_dose(patient["id"], lot["id"], provider["id"], "2025-01-01")
    run_evaluation(patient["id"], "2026-06-01")
    issue_recall(lot["id"], reason="contamination")
    ev = run_evaluation(patient["id"], "2026-06-01")
    pat = get_success_data(api_client.get_patient(patient["id"], REG))
    assert ev["overall_status"] == "BEHIND", f"got {ev['overall_status']}"
    assert pat["schedule_status"] == "BEHIND", f"got {pat['schedule_status']}"


def test_recall_cascade_atomic_in_single_response(api):
    """PRD §3.9: "every Immunization on the lot that is RECORDED or AMENDED
    transitions to INVALIDATED ... the recall's invalidated_count is set to the
    number of doses struck."

    A recall on a lot with two recorded doses returns invalidated_count 2 in the
    same response.

    Design: Corner/consistency_model/recall_cascade_atomic_in_single_response
    """
    set_clock("2026-06-01T00:00:00Z")
    product = create_product(**create_product_payload(**C1))
    provider = create_provider(authorized_product_codes=["C1"])
    lot = create_lot(product["id"])
    pat_a = create_patient(full_name="Child AA", date_of_birth="2024-01-01")
    pat_b = create_patient(full_name="Child BB", date_of_birth="2024-01-01")
    record_dose(pat_a["id"], lot["id"], provider["id"], "2025-01-01")
    record_dose(pat_b["id"], lot["id"], provider["id"], "2025-01-01")
    recall = validate_success(
        api_client.create_recall(lot["id"], {"reason": "lot-wide"}, REG),
        expected_status=201)
    assert recall["invalidated_count"] == 2, \
        f"expected invalidated_count 2, got {recall['invalidated_count']}"
