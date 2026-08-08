"""Payload factories — one per resource, input fields only."""
import itertools

from .constants import HIGH_TIER_REFERRAL_INPUTS

_MRN_SEQ = itertools.count(1)


def next_mrn(prefix: str = "MRN") -> str:
    """Unique medical record number; external_mrn must be unique per patient."""
    return f"{prefix}-{next(_MRN_SEQ):06d}"


def create_patient_payload(**overrides) -> dict:
    payload = {
        "external_mrn": next_mrn(),
        "full_name": "Ada Reyes",
        "date_of_birth": "1952-03-14",
    }
    payload.update(overrides)
    return payload


def create_facility_payload(**overrides) -> dict:
    payload = {
        "name": "Mercy General",
        "facility_type": "ACUTE_HOSPITAL",
        "network_status": "IN_NETWORK",
    }
    payload.update(overrides)
    return payload


def create_payer_payload(**overrides) -> dict:
    payload = {
        "name": "Northstar Health",
        "tcm_covered": True,
        "tcm_rate_multiplier": 1.0,
        "coinsurance_rate": 0.2,
        "contact_deadline_basis": "BUSINESS_DAYS",
    }
    payload.update(overrides)
    return payload


def create_navigator_payload(**overrides) -> dict:
    payload = {
        "full_name": "Nora Vance",
        "active_episode_cap": 5,
        "cap_policy": "COUNT",
    }
    payload.update(overrides)
    return payload


def create_referral_payload(patient_id, facility_id, payer_id, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "facility_id": facility_id,
        "payer_id": payer_id,
        "discharge_date": "2026-05-01",
        "discharge_datetime": "2026-05-01T14:00:00Z",
        "discharge_disposition": "HOME",
    }
    payload.update(HIGH_TIER_REFERRAL_INPUTS)
    payload.update(overrides)
    return payload


def accept_referral_payload(navigator_id, **overrides) -> dict:
    payload = {"navigator_id": navigator_id}
    payload.update(overrides)
    return payload


def close_referral_payload(**overrides) -> dict:
    payload = {"outcome": "DENIED", "closure_reason_code": "NOT_ELIGIBLE"}
    payload.update(overrides)
    return payload


def risk_assessment_payload(**overrides) -> dict:
    payload = {
        "comorbidity_count": 5,
        "prior_ed_visits_6mo": 2,
        "prior_admissions_6mo": 1,
        "social_risk_flags_count": 3,
    }
    payload.update(overrides)
    return payload


def contact_attempt_payload(**overrides) -> dict:
    payload = {"modality": "PHONE"}
    payload.update(overrides)
    return payload


def contact_disposition_payload(**overrides) -> dict:
    payload = {"outcome": "CONNECTED"}
    payload.update(overrides)
    return payload


def book_visit_payload(navigator_id, **overrides) -> dict:
    payload = {
        "navigator_id": navigator_id,
        "scheduled_start": "2026-05-05T15:00:00Z",
        "scheduled_end": "2026-05-05T16:00:00Z",
    }
    payload.update(overrides)
    return payload


def complete_visit_payload(documented_elements, **overrides) -> dict:
    payload = {"documented_elements": list(documented_elements)}
    payload.update(overrides)
    return payload


def amend_visit_payload(documented_elements, expected_visit_version, **overrides) -> dict:
    payload = {
        "documented_elements": list(documented_elements),
        "expected_visit_version": expected_visit_version,
    }
    payload.update(overrides)
    return payload


def close_encounter_payload(**overrides) -> dict:
    payload = {"outcome": "NO_SHOW"}
    payload.update(overrides)
    return payload


def reschedule_visit_payload(**overrides) -> dict:
    payload = {
        "scheduled_start": "2026-05-06T09:00:00Z",
        "scheduled_end": "2026-05-06T10:00:00Z",
    }
    payload.update(overrides)
    return payload


def discrepancy_payload(expected_med_reconciliation_version, **overrides) -> dict:
    payload = {
        "medication_name": "metformin",
        "discrepancy_type": "DOSE_MISMATCH",
        "severity": "LOW",
        "expected_med_reconciliation_version": expected_med_reconciliation_version,
    }
    payload.update(overrides)
    return payload


def discrepancy_disposition_payload(**overrides) -> dict:
    payload = {"disposition": "RESOLVED", "resolution_note": "dose verified"}
    payload.update(overrides)
    return payload


def barrier_payload(**overrides) -> dict:
    payload = {"barrier_type": "TRANSPORTATION", "description": "no ride to clinic"}
    payload.update(overrides)
    return payload


def close_barrier_payload(**overrides) -> dict:
    payload = {"outcome": "RESOLVED"}
    payload.update(overrides)
    return payload


def red_flag_payload(**overrides) -> dict:
    payload = {"category": "CLINICAL_SYMPTOM", "initial_tier": "TIER_2"}
    payload.update(overrides)
    return payload


def resolve_red_flag_payload(**overrides) -> dict:
    payload = {"resolution_outcome": "RESOLVED_AT_HOME"}
    payload.update(overrides)
    return payload


def readmission_payload(**overrides) -> dict:
    payload = {"readmission_date": "2026-05-15", "classification": "UNPLANNED_INPATIENT"}
    payload.update(overrides)
    return payload


def retract_readmission_payload(**overrides) -> dict:
    payload = {"retraction_reason": "coding error"}
    payload.update(overrides)
    return payload


def prepare_claim_payload(visit_id, **overrides) -> dict:
    payload = {"visit_id": visit_id}
    payload.update(overrides)
    return payload


def adjudicate_claim_payload(**overrides) -> dict:
    payload = {"outcome": "PAID"}
    payload.update(overrides)
    return payload


def propose_handoff_payload(to_navigator_id, expected_episode_version, **overrides) -> dict:
    payload = {
        "to_navigator_id": to_navigator_id,
        "handoff_type": "INTERNAL_NAVIGATOR",
        "expected_episode_version": expected_episode_version,
    }
    payload.update(overrides)
    return payload


def respond_handoff_payload(**overrides) -> dict:
    payload = {"response": "ACCEPT"}
    payload.update(overrides)
    return payload
