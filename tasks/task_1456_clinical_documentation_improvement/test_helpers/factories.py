"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def create_cdi_program_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "facility_name": f"Facility-{n}",
        "program_code": f"PROG-{n}",
        "baseline_cmi": 1.0,
    }
    defaults.update(overrides)
    return defaults


def create_escalation_policy_payload(cdi_program_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "cdi_program_id": cdi_program_id,
        "name": f"EP-{n}",
        "response_due_periods": 1,
        "escalation_stage_periods": 1,
        "max_escalation_stage": 1,
        "is_default": True,
    }
    defaults.update(overrides)
    return defaults


def create_provider_payload(cdi_program_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "cdi_program_id": cdi_program_id,
        "npi": f"NPI-{n}",
        "full_name": f"Dr. Test-{n}",
        "specialty": "Internal Medicine",
    }
    defaults.update(overrides)
    return defaults


def create_patient_case_payload(cdi_program_id, attending_provider_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "cdi_program_id": cdi_program_id,
        "mrn": f"MRN-{n}",
        "admission_period": 0,
        "discharge_period": 5,
        "attending_provider_id": attending_provider_id,
        "initial_drg_code": "DRG-A",
        "initial_drg_weight": 1.0,
    }
    defaults.update(overrides)
    return defaults


def create_cdi_review_payload(patient_case_id, **overrides) -> dict:
    defaults = {"patient_case_id": patient_case_id}
    defaults.update(overrides)
    return defaults


def create_cdi_query_payload(cdi_review_id, provider_id, escalation_policy_id, **overrides) -> dict:
    defaults = {
        "cdi_review_id": cdi_review_id,
        "provider_id": provider_id,
        "escalation_policy_id": escalation_policy_id,
        "query_text": "Please clarify the documented acuity.",
        "clinical_indicators": ["WBC-14"],
        "proposed_drg_code": "DRG-B",
        "proposed_drg_weight": 2.0,
        "proposed_soi": 2,
        "proposed_rom": 2,
    }
    defaults.update(overrides)
    return defaults


def create_query_response_payload(**overrides) -> dict:
    defaults = {
        "response_type": "AGREE",
        "response_text": "Agreed, documentation updated.",
    }
    defaults.update(overrides)
    return defaults


def create_finalize_coding_payload(coder_drg_code, coder_drg_weight, expected_case_version,
                                   **overrides) -> dict:
    defaults = {
        "coder_drg_code": coder_drg_code,
        "coder_drg_weight": coder_drg_weight,
        "expected_case_version": expected_case_version,
    }
    defaults.update(overrides)
    return defaults


def create_denial_risk_target_payload(cdi_program_id, **overrides) -> dict:
    defaults = {
        "cdi_program_id": cdi_program_id,
        "drg_code": "DRG-A",
        "required_evidence_tags": ["TAG-1"],
        "severity_floor": 1,
        "active_from_period": 0,
        "active_to_period": 10,
    }
    defaults.update(overrides)
    return defaults


def create_provider_education_event_payload(provider_id, source_query_id, **overrides) -> dict:
    defaults = {
        "provider_id": provider_id,
        "pattern_tag": "LEADING_LANGUAGE",
        "points_deducted": 5,
        "source_query_id": source_query_id,
        "note": "education note",
    }
    defaults.update(overrides)
    return defaults


def create_resolve_reconciliation_payload(**overrides) -> dict:
    defaults = {
        "outcome": "CDI_PREVAILS",
        "resolution_note": "Resolved per documentation review.",
    }
    defaults.update(overrides)
    return defaults
