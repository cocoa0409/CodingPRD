"""Payload factories for every client-supplied input field in the PRD."""

import itertools

from .constants import TEST_DEFAULTS

_cert_seq = itertools.count(1)
_dept_seq = itertools.count(1)
_serial_seq = itertools.count(1)
_lot_seq = itertools.count(1)
_mrn_seq = itertools.count(1)


def next_certificate_number() -> str:
    """A fresh ten-character CMS-style certificate number."""
    return "45D22430{:02d}".format(next(_cert_seq) % 100)


def next_department_code() -> str:
    return "DEPT-{:03d}".format(100 + next(_dept_seq))


def next_serial_number() -> str:
    return "SN-{:04d}".format(1000 + next(_serial_seq))


def next_lot_number() -> str:
    return "LOT-{:04d}".format(1000 + next(_lot_seq))


def next_patient_mrn() -> str:
    return "MRN-{:04d}".format(7000 + next(_mrn_seq))


# ── Certificates and coverage (PRD 3.1) ────────────────────────────


def certificate_payload(**overrides) -> dict:
    payload = {
        "certificate_number": next_certificate_number(),
        "certificate_type": "CERTIFICATE_OF_WAIVER",
        "permitted_complexity": "WAIVED",
        "effective_date": "2026-01-01",
        "expiration_date": "2027-12-31",
    }
    payload.update(overrides)
    return payload


def moderate_certificate_payload(**overrides) -> dict:
    payload = certificate_payload(
        certificate_type="CERTIFICATE_OF_COMPLIANCE",
        permitted_complexity="MODERATE",
    )
    payload.update(overrides)
    return payload


def coverage_payload(site_id: str, certificate_id: str, **overrides) -> dict:
    payload = {
        "site_id": site_id,
        "certificate_id": certificate_id,
        "coverage_start": "2026-01-01",
        "coverage_end": "2027-12-31",
    }
    payload.update(overrides)
    return payload


# ── Sites and directors (PRD 3.2) ──────────────────────────────────


def site_payload(**overrides) -> dict:
    payload = {
        "name": "Point-Of-Care Ward",
        "department_code": next_department_code(),
        "complexity_scope": "WAIVED",
    }
    payload.update(overrides)
    return payload


def director_payload(lab_director_operator_id: str) -> dict:
    return {"lab_director_operator_id": lab_director_operator_id}


# ── Operators, training and access (PRD 3.3) ───────────────────────


def operator_payload(site_id: str, **overrides) -> dict:
    payload = {
        "site_id": site_id,
        "full_name": "Alma Ruiz",
        "role_title": "MEDICAL_TECHNOLOGIST",
        "hire_date": "2026-02-01",
    }
    payload.update(overrides)
    return payload


def training_payload(**overrides) -> dict:
    payload = {
        "training_module_code": TEST_DEFAULTS["TRAINING_MODULE_CODE"],
        "completed_on": "2026-08-01",
    }
    payload.update(overrides)
    return payload


def reinstatement_payload(**overrides) -> dict:
    payload = {"justification": "Retraining verified, operator returning to duty"}
    payload.update(overrides)
    return payload


# ── Competency assessments (PRD 3.3) ───────────────────────────────


def assessment_payload(
    operator_id: str,
    assessor_operator_id: str,
    expected_operator_version: int,
    **overrides,
) -> dict:
    payload = {
        "operator_id": operator_id,
        "assessor_operator_id": assessor_operator_id,
        "device_model": TEST_DEFAULTS["DEVICE_MODEL"],
        "assessment_type": "INITIAL",
        "methods_demonstrated": 6,
        "effective_date": "2026-08-01",
        "expires_at": "2027-08-01",
        "expected_operator_version": expected_operator_version,
    }
    payload.update(overrides)
    return payload


def assessment_decision_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision, "note": "All six elements observed"}
    payload.update(overrides)
    return payload


# ── Instruments (PRD 3.4) ──────────────────────────────────────────


def device_payload(site_id: str, **overrides) -> dict:
    payload = {
        "site_id": site_id,
        "device_model": TEST_DEFAULTS["DEVICE_MODEL"],
        "serial_number": next_serial_number(),
        "analyte": TEST_DEFAULTS["ANALYTE"],
        "complexity_class": "WAIVED",
        "connectivity_mode": "INTERFACED",
        "qc_frequency_days": TEST_DEFAULTS["QC_FREQUENCY_DAYS"],
    }
    payload.update(overrides)
    return payload


def qc_unlock_payload(confirming_qc_run_id: str, **overrides) -> dict:
    payload = {
        "confirming_qc_run_id": confirming_qc_run_id,
        "note": "Repeat control in range",
    }
    payload.update(overrides)
    return payload


def retire_payload(**overrides) -> dict:
    payload = {"reason": "Instrument decommissioned and removed from the ward"}
    payload.update(overrides)
    return payload


# ── Storage, readings and reagent lots (PRD 3.5) ───────────────────


def storage_unit_payload(site_id: str, **overrides) -> dict:
    payload = {
        "site_id": site_id,
        "name": "Fridge A",
        "min_temp_c": TEST_DEFAULTS["STORAGE_MIN_C"],
        "max_temp_c": TEST_DEFAULTS["STORAGE_MAX_C"],
    }
    payload.update(overrides)
    return payload


def temperature_reading_payload(reading_c: float, **overrides) -> dict:
    payload = {
        "reading_c": reading_c,
        "recorded_at": "2026-08-01T00:00:00Z",
        "recorded_by_user_id": "probe-gateway-1",
    }
    payload.update(overrides)
    return payload


def excursion_resolution_payload(lot_disposition: str, **overrides) -> dict:
    payload = {
        "assessment_note": (
            "Door ajar for 20 minutes; manufacturer confirms stability"
        ),
        "lot_disposition": lot_disposition,
    }
    payload.update(overrides)
    return payload


def reagent_lot_payload(site_id: str, storage_unit_id: str, **overrides) -> dict:
    payload = {
        "site_id": site_id,
        "storage_unit_id": storage_unit_id,
        "device_model": TEST_DEFAULTS["DEVICE_MODEL"],
        "lot_number": next_lot_number(),
        "expiration_date": "2027-06-30",
        "received_at": "2026-08-01T00:00:00Z",
        "control_min_level_1": TEST_DEFAULTS["CONTROL_MIN_L1"],
        "control_max_level_1": TEST_DEFAULTS["CONTROL_MAX_L1"],
        "control_min_level_2": TEST_DEFAULTS["CONTROL_MIN_L2"],
        "control_max_level_2": TEST_DEFAULTS["CONTROL_MAX_L2"],
    }
    payload.update(overrides)
    return payload


def lot_verify_payload(level_1_qc_run_id: str, level_2_qc_run_id: str) -> dict:
    return {
        "level_1_qc_run_id": level_1_qc_run_id,
        "level_2_qc_run_id": level_2_qc_run_id,
    }


# ── Control runs (PRD 3.4) ─────────────────────────────────────────


def qc_run_payload(
    device_id: str,
    reagent_lot_id: str,
    operator_id: str,
    control_level: str,
    measured_value: float,
    **overrides,
) -> dict:
    payload = {
        "device_id": device_id,
        "reagent_lot_id": reagent_lot_id,
        "operator_id": operator_id,
        "control_level": control_level,
        "measured_value": measured_value,
    }
    payload.update(overrides)
    return payload


# ── Patient results (PRD 3.6) ──────────────────────────────────────


def patient_result_payload(
    device_id: str, operator_id: str, reagent_lot_id: str, **overrides
) -> dict:
    payload = {
        "device_id": device_id,
        "operator_id": operator_id,
        "reagent_lot_id": reagent_lot_id,
        "patient_mrn": next_patient_mrn(),
        "analyte": TEST_DEFAULTS["ANALYTE"],
        "measured_value": 103.0,
        "entry_mode": "INTERFACED",
    }
    payload.update(overrides)
    return payload


def post_payload(**overrides) -> dict:
    payload = {"attestation": "Result reviewed against the patient chart"}
    payload.update(overrides)
    return payload


def correction_payload(
    corrected_value: float, expected_test_result_version: int, **overrides
) -> dict:
    payload = {
        "corrected_value": corrected_value,
        "correction_reason": "Transcription error found on chart review",
        "expected_test_result_version": expected_test_result_version,
    }
    payload.update(overrides)
    return payload


# ── Proficiency testing (PRD 3.7) ──────────────────────────────────


def pt_enrollment_payload(site_id: str, **overrides) -> dict:
    payload = {
        "site_id": site_id,
        "analyte": TEST_DEFAULTS["ANALYTE"],
        "program_year": 2026,
        "program_provider": "NationalPT",
    }
    payload.update(overrides)
    return payload


def pt_event_payload(enrollment_id: str, shipment_number: int, **overrides) -> dict:
    payload = {
        "enrollment_id": enrollment_id,
        "shipment_number": shipment_number,
        "due_date": "2026-08-10",
    }
    payload.update(overrides)
    return payload


def pt_score_payload(score_pct: float, **overrides) -> dict:
    payload = {"score_pct": score_pct, "graded_on": "2026-08-01"}
    payload.update(overrides)
    return payload


def pt_investigation_payload(**overrides) -> dict:
    payload = {
        "root_cause": "Control material stored above the labelled band",
        "corrective_action": "Probe recalibrated and staff retrained",
    }
    payload.update(overrides)
    return payload


def pt_investigation_decision_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision, "note": "Root cause accepted"}
    payload.update(overrides)
    return payload


# ── Surveys and deficiency findings (PRD 3.8) ──────────────────────


def inspection_payload(site_id: str, **overrides) -> dict:
    payload = {
        "site_id": site_id,
        "inspection_type": "INTERNAL_READINESS",
        "scheduled_date": "2026-08-01",
    }
    payload.update(overrides)
    return payload


def deficiency_payload(inspection_id: str, **overrides) -> dict:
    payload = {
        "inspection_id": inspection_id,
        "category": "PERSONNEL_COMPETENCY",
        "severity": "STANDARD_LEVEL",
        "description": "Annual competency records incomplete",
        "correction_due_date": "2026-10-31",
    }
    payload.update(overrides)
    return payload


def issue_payload(**overrides) -> dict:
    payload = {"issued_on": "2026-08-01"}
    payload.update(overrides)
    return payload


def rescind_payload(**overrides) -> dict:
    payload = {"reason": "Findings issued against the wrong department code"}
    payload.update(overrides)
    return payload


def correction_submission_payload(**overrides) -> dict:
    payload = {
        "correction_narrative": "Competency binders rebuilt for all six elements",
        "evidence_ref": "EV-1001",
    }
    payload.update(overrides)
    return payload


def correction_decision_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision, "note": "Evidence reviewed on site"}
    payload.update(overrides)
    return payload


# ── Oversight epoch (PRD 3.9) ──────────────────────────────────────


def oversight_run_payload(**overrides) -> dict:
    payload = {"note": "Scheduled oversight sweep"}
    payload.update(overrides)
    return payload
