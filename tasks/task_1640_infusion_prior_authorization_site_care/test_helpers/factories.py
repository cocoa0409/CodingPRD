"""Payload factories — one per entity, input fields only.

Defaults mirror the PRD's example values; every factory accepts **overrides so
tests can steer exactly the fields they exercise.
"""
from .constants import (
    DEFAULT_PATIENT,
    DEFAULT_POLICY,
    DEFAULT_REQUEST,
    DEFAULT_SITE_AMOUNTS,
)


def create_policy_payload(**overrides) -> dict:
    payload = dict(DEFAULT_POLICY)
    payload.update(overrides)
    return payload


def create_patient_payload(**overrides) -> dict:
    payload = dict(DEFAULT_PATIENT)
    payload.update(overrides)
    return payload


def create_auth_request_payload(patient_id, policy_id, **overrides) -> dict:
    payload = dict(DEFAULT_REQUEST)
    payload.update({"patient_id": patient_id, "policy_id": policy_id})
    payload.update(overrides)
    return payload


def create_site_determination_payload(**overrides) -> dict:
    payload = dict(DEFAULT_SITE_AMOUNTS)
    payload.update(overrides)
    return payload


def create_criteria_payload(criterion_code="DIAG_CONFIRM",
                            response_value="biopsy-on-file", **overrides) -> dict:
    payload = {"criterion_code": criterion_code, "response_value": response_value}
    payload.update(overrides)
    return payload


def review_criteria_payload(outcome="ACCEPTED") -> dict:
    return {"outcome": outcome}


def determination_payload(outcome, expected_authorization_version,
                          denial_reason=None) -> dict:
    payload = {
        "outcome": outcome,
        "expected_authorization_version": expected_authorization_version,
    }
    if denial_reason is not None:
        payload["denial_reason"] = denial_reason
    return payload


def verify_benefit_payload(determined_channel="MEDICAL") -> dict:
    return {"determined_channel": determined_channel}


def create_appeal_payload(reason="new-evidence") -> dict:
    return {"reason": reason}


def appeal_decision_payload(outcome="UPHELD") -> dict:
    return {"outcome": outcome}


def create_p2p_payload(reviewer_user_id="md-9",
                       scheduled_start="2026-08-05T10:00:00Z",
                       scheduled_end="2026-08-05T10:30:00Z") -> dict:
    return {
        "reviewer_user_id": reviewer_user_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }


def reschedule_p2p_payload(scheduled_start, scheduled_end) -> dict:
    return {"scheduled_start": scheduled_start, "scheduled_end": scheduled_end}


def complete_p2p_payload(outcome="UPHOLD") -> dict:
    return {"outcome": outcome}


def create_line_item_payload(description="drug", allowed_amount_cents=100000,
                             billed_charges_cents=100000, **overrides) -> dict:
    payload = {
        "description": description,
        "allowed_amount_cents": allowed_amount_cents,
        "billed_charges_cents": billed_charges_cents,
    }
    payload.update(overrides)
    return payload


def create_chair_payload(site_type="OFFICE", label="CH-1", **overrides) -> dict:
    payload = {"site_type": site_type, "label": label}
    payload.update(overrides)
    return payload


def create_appointment_payload(chair_id, scheduled_start, scheduled_end) -> dict:
    return {
        "chair_id": chair_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }


def create_dose_change_payload(new_dose_mg) -> dict:
    return {"new_dose_mg": new_dose_mg}


def dose_change_decision_payload(outcome) -> dict:
    return {"outcome": outcome}
