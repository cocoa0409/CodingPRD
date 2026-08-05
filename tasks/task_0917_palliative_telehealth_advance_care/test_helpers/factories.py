"""Payload factories — one per creating operation, input fields only."""

import itertools

from .constants import USER_IDS

_MRN_COUNTER = itertools.count(1)


def next_mrn(prefix: str = "MRN") -> str:
    """A fresh mrn: the value must be unique across every patient."""
    return f"{prefix}-{next(_MRN_COUNTER):05d}"


def patient_payload(**overrides) -> dict:
    payload = {
        "mrn": next_mrn(),
        "full_name": "Test Patient",
        "date_of_birth": "1950-01-01",
        "jurisdiction_code": "JUR_TWO_WITNESS",
        "attending_clinician_user_id": USER_IDS["ATTENDING"],
        "opioid_status": "OPIOID_TOLERANT",
    }
    payload.update(overrides)
    return payload


def referral_payload(patient_id, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "source": "HOSPITAL_DISCHARGE",
        "prognosis_months": 6,
        "serious_illness_criteria_count": 3,
    }
    payload.update(overrides)
    return payload


def referral_decision_payload(decision="ACCEPT", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def surrogate_payload(patient_id, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "person_user_id": USER_IDS["SPOUSE"],
        "person_name": "Test Surrogate",
        "relationship": "SPOUSE",
        "is_beneficiary": False,
    }
    payload.update(overrides)
    return payload


def capacity_determination_payload(capacity_status="LACKS_CAPACITY", **overrides) -> dict:
    payload = {
        "capacity_status": capacity_status,
        "determination_note": "capacity determined at the bedside",
    }
    payload.update(overrides)
    return payload


def death_event_payload(**overrides) -> dict:
    payload = {"pronouncing_clinician_user_id": USER_IDS["PHYSICIAN"]}
    payload.update(overrides)
    return payload


def document_payload(patient_id, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "document_type": "LIVING_WILL",
        "stated_code_status": "DNR",
    }
    payload.update(overrides)
    return payload


def signature_payload(signature_type="WITNESS", signer_user_id=None, **overrides) -> dict:
    payload = {
        "signature_type": signature_type,
        "signer_user_id": signer_user_id or USER_IDS["WITNESS_1"],
    }
    payload.update(overrides)
    return payload


def code_status_order_payload(patient_id, requested_code_status="DNR", **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "requested_code_status": requested_code_status,
    }
    payload.update(overrides)
    return payload


def code_status_attestation_payload(attestation_role="CLINICIAN", **overrides) -> dict:
    payload = {
        "attestation_role": attestation_role,
        "attestation_text": "goals of care discussed and documented",
    }
    payload.update(overrides)
    return payload


def care_plan_payload(patient_id, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "plan_title": "Comfort plan",
        "problem_list": ["pain"],
    }
    payload.update(overrides)
    return payload


def care_plan_revision_payload(expected_care_plan_version, revised_problem_list, **overrides) -> dict:
    payload = {
        "expected_care_plan_version": expected_care_plan_version,
        "revised_problem_list": revised_problem_list,
    }
    payload.update(overrides)
    return payload


def symptom_assessment_payload(patient_id, care_plan_id, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "care_plan_id": care_plan_id,
        "reporter_type": "SELF",
        "item_pain": 6,
        "item_dyspnea": 6,
        "item_nausea": 6,
        "item_anxiety": 6,
        "item_fatigue": 6,
    }
    payload.update(overrides)
    return payload


def triage_update_payload(action="ACKNOWLEDGE", **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


def conference_payload(patient_id, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "conference_type": "IDT",
        "modality": "TELEHEALTH",
        "scheduled_start": "2026-06-02T09:00:00Z",
        "scheduled_end": "2026-06-02T10:00:00Z",
    }
    payload.update(overrides)
    return payload


def conference_hold_payload(documented_minutes=46, **overrides) -> dict:
    payload = {"documented_minutes": documented_minutes}
    payload.update(overrides)
    return payload


def conference_attestation_payload(discipline="PHYSICIAN", **overrides) -> dict:
    payload = {
        "discipline": discipline,
        "note_text": f"{discipline.lower()} note recorded",
    }
    payload.update(overrides)
    return payload


def medication_order_payload(patient_id, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "drug": "MORPHINE_PO",
        "dose_amount": 30,
        "days_supply": 14,
    }
    payload.update(overrides)
    return payload


def medication_attestation_payload(attestation_type="VERIFICATION", **overrides) -> dict:
    payload = {"attestation_type": attestation_type}
    payload.update(overrides)
    return payload


def discontinue_payload(**overrides) -> dict:
    payload = {"discontinue_reason": "no longer required"}
    payload.update(overrides)
    return payload


def dme_inventory_payload(**overrides) -> dict:
    payload = {
        "device_type": "HOSPITAL_BED",
        "total_units": 5,
        "prior_auth_required": False,
    }
    payload.update(overrides)
    return payload


def dme_order_payload(patient_id, inventory_item_id, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "inventory_item_id": inventory_item_id,
        "quantity": 1,
        "delivery_window_start": "2026-06-10T09:00:00Z",
        "delivery_window_end": "2026-06-10T11:00:00Z",
    }
    payload.update(overrides)
    return payload


def hospice_election_payload(patient_id, **overrides) -> dict:
    payload = {"patient_id": patient_id}
    payload.update(overrides)
    return payload


def hospice_certification_payload(terminal_diagnosis_code="C34.90", **overrides) -> dict:
    payload = {"terminal_diagnosis_code": terminal_diagnosis_code}
    payload.update(overrides)
    return payload


def hospice_period_payload(expected_election_version, period_start, **overrides) -> dict:
    payload = {
        "expected_election_version": expected_election_version,
        "period_start": period_start,
    }
    payload.update(overrides)
    return payload


def escalation_payload(patient_id, symptom_assessment_id, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "symptom_assessment_id": symptom_assessment_id,
        "contact_summary": "after-hours call from the family",
    }
    payload.update(overrides)
    return payload


def escalation_response_payload(response_type="ACKNOWLEDGE", **overrides) -> dict:
    payload = {"response_type": response_type}
    payload.update(overrides)
    return payload


def claim_payload(patient_id, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "service_date": "2026-06-01T09:00:00Z",
        "documented_minutes": 46,
        "modality": "IN_PERSON",
    }
    payload.update(overrides)
    return payload


def claim_attest_payload(**overrides) -> dict:
    payload = {"attestation_statement": "time and content documented"}
    payload.update(overrides)
    return payload


def adjudication_payload(outcome="PAID", **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload
