"""Payload factories — input fields only, sensible defaults overridable."""

from .constants import (
    DEFAULT_COLLECTION,
    DEFAULT_CONSULT_DUE,
    DEFAULT_DOB,
    DEFAULT_LOAN_DUE_BACK,
    DEFAULT_LOAN_OUT,
    DEFAULT_RECEIVED,
)

_mrn_counter = {"n": 0}


def next_mrn(prefix: str = "MRN") -> str:
    """Distinct MRN per call so multiple patients can coexist in one test."""
    _mrn_counter["n"] += 1
    return f"{prefix}-{_mrn_counter['n']:04d}"


def create_patient_payload(**overrides) -> dict:
    defaults = {
        "mrn": next_mrn(),
        "full_name": "Test Patient",
        "date_of_birth": DEFAULT_DOB,
    }
    defaults.update(overrides)
    return defaults


def create_pathologist_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Dr Test",
        "subspecialties": ["GI"],
    }
    defaults.update(overrides)
    return defaults


def create_coverage_window_payload(**overrides) -> dict:
    defaults = {
        "window_type": "CONSULT_SERVICE",
        "start_at": "2026-08-03T10:00:00Z",
        "end_at": "2026-08-03T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(**overrides) -> dict:
    defaults = {
        "subspecialty": "GI",
    }
    defaults.update(overrides)
    return defaults


def accession_specimen_payload(**overrides) -> dict:
    defaults = {
        "patient_mrn": "MRN-0001",
        "patient_dob": DEFAULT_DOB,
        "specimen_type": "BIOPSY",
        "anatomical_site": "Colon",
        "collection_datetime": DEFAULT_COLLECTION,
        "received_datetime": DEFAULT_RECEIVED,
        "container_count": 1,
    }
    defaults.update(overrides)
    return defaults


def gross_payload(**overrides) -> dict:
    defaults = {"gross_description": "biopsy fragments"}
    defaults.update(overrides)
    return defaults


def reject_payload(**overrides) -> dict:
    defaults = {"reason": "no tissue in container"}
    defaults.update(overrides)
    return defaults


def create_block_payload(**overrides) -> dict:
    defaults = {"block_label": "A1"}
    defaults.update(overrides)
    return defaults


def create_slide_payload(**overrides) -> dict:
    defaults = {"slide_label": "A1-1"}
    defaults.update(overrides)
    return defaults


def section_payload(consumption_pct=10.0) -> dict:
    return {"consumption_pct": consumption_pct}


def qc_review_payload(result="PASS", **overrides) -> dict:
    payload = {"result": result}
    payload.update(overrides)
    return payload


def create_stain_order_payload(**overrides) -> dict:
    defaults = {"stain_type": "MUCIN"}
    defaults.update(overrides)
    return defaults


def result_stain_payload(result_value="POSITIVE") -> dict:
    return {"result_value": result_value}


def create_reflex_rule_payload(**overrides) -> dict:
    defaults = {
        "name": "Reflex rule",
        "trigger_stain_type": "HER2_IHC",
        "trigger_result": "POSITIVE",
        "followup_stain_type": "KI67",
        "priority": 1,
    }
    defaults.update(overrides)
    return defaults


def create_consultation_payload(**overrides) -> dict:
    defaults = {
        "subspecialty": "GI",
        "question_text": "grade?",
        "due_at": DEFAULT_CONSULT_DUE,
    }
    defaults.update(overrides)
    return defaults


def answer_payload(**overrides) -> dict:
    defaults = {"opinion_text": "agree", "concordance": "CONCORDANT"}
    defaults.update(overrides)
    return defaults


def create_discrepancy_payload(**overrides) -> dict:
    defaults = {"severity": "LEVEL_1", "description": "qa note"}
    defaults.update(overrides)
    return defaults


def create_release_request_payload(**overrides) -> dict:
    defaults = {
        "material_type": "SLIDE",
        "requesting_institution": "County Hospital",
        "reason": "external review",
        "requested_out_at": DEFAULT_LOAN_OUT,
        "due_back_at": DEFAULT_LOAN_DUE_BACK,
    }
    defaults.update(overrides)
    return defaults


def sign_out_payload(**overrides) -> dict:
    defaults = {"diagnosis_text": "Benign"}
    defaults.update(overrides)
    return defaults


def amend_payload(**overrides) -> dict:
    defaults = {"diagnosis_text": "Amended diagnosis", "amendment_reason": "clarification"}
    defaults.update(overrides)
    return defaults


def cancel_case_payload(**overrides) -> dict:
    defaults = {"reason": "order withdrawn"}
    defaults.update(overrides)
    return defaults
