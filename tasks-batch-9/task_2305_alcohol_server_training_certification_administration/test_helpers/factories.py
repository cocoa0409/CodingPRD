"""Payload factories — one per resource, carrying only client-supplied input fields."""
import itertools

from .constants import (
    TRAINER_CREDENTIAL_EXPIRES_AT,
    TX_APPROVAL_DECISION,
    TX_COURSE,
    TX_JURISDICTION,
)

_counter = itertools.count(1)


def unique_suffix() -> str:
    """Monotonic suffix for natural keys that must not collide inside one test."""
    return str(next(_counter))


# --------------------------------------------------------------------------- jurisdiction

def state_jurisdiction_payload(**overrides) -> dict:
    payload = dict(TX_JURISDICTION)
    payload.update(overrides)
    return payload


def minimal_state_jurisdiction_payload(**overrides) -> dict:
    """Only the two fields with no default: state_code and the mandate mapping."""
    payload = {
        "state_code": "TX",
        "mandate_type": "MANDATORY",
        "mandated_tracks": ["ON_PREMISE", "OFF_PREMISE"],
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------------- course

def course_payload(**overrides) -> dict:
    payload = dict(TX_COURSE)
    payload.update(overrides)
    return payload


def course_revision_payload(**overrides) -> dict:
    payload = {"revision_note": "corrected a typo on slide 12"}
    payload.update(overrides)
    return payload


# ------------------------------------------------------------------------ course approval

def course_approval_payload(course_id, state_jurisdiction_id, **overrides) -> dict:
    payload = {
        "course_id": course_id,
        "state_jurisdiction_id": state_jurisdiction_id,
        "submission_note": "initial filing",
    }
    payload.update(overrides)
    return payload


def approve_decision_payload(**overrides) -> dict:
    payload = dict(TX_APPROVAL_DECISION)
    payload.update(overrides)
    return payload


def request_changes_decision_payload(**overrides) -> dict:
    payload = {
        "decision": "REQUEST_CHANGES",
        "changes_requested_note": "clarify the intervention module",
    }
    payload.update(overrides)
    return payload


def reject_decision_payload(**overrides) -> dict:
    payload = {"decision": "REJECT"}
    payload.update(overrides)
    return payload


def resubmit_payload(**overrides) -> dict:
    payload = {"submission_note": "revised filing"}
    payload.update(overrides)
    return payload


# -------------------------------------------------------------------------------- trainer

def trainer_payload(**overrides) -> dict:
    payload = {"full_name": "Dana Reyes", "email": "dana@tips.example"}
    payload.update(overrides)
    return payload


def trainer_credential_payload(**overrides) -> dict:
    payload = {
        "certified_tracks": ["ON_PREMISE"],
        "certified_state_codes": ["TX"],
        "credential_expires_at": TRAINER_CREDENTIAL_EXPIRES_AT,
    }
    payload.update(overrides)
    return payload


def trainer_suspend_payload(**overrides) -> dict:
    payload = {"suspension_reason": "credential audit finding"}
    payload.update(overrides)
    return payload


# -------------------------------------------------------------------------- class session

def class_session_payload(course_id, state_jurisdiction_id, trainer_id, **overrides) -> dict:
    payload = {
        "course_id": course_id,
        "state_jurisdiction_id": state_jurisdiction_id,
        "trainer_id": trainer_id,
        "scheduled_start_at": "2026-08-10T14:00:00Z",
        "scheduled_end_at": "2026-08-10T18:00:00Z",
        "capacity": 20,
    }
    payload.update(overrides)
    return payload


def open_exam_payload(proctor_trainer_id, **overrides) -> dict:
    payload = {"proctor_trainer_id": proctor_trainer_id}
    payload.update(overrides)
    return payload


def cancel_session_payload(**overrides) -> dict:
    payload = {"cancellation_reason": "venue flood"}
    payload.update(overrides)
    return payload


# ------------------------------------------------------------------------- alcohol server

def alcohol_server_payload(state_jurisdiction_id, **overrides) -> dict:
    payload = {
        "full_name": "Ari Cole",
        "email": "ari@example.com",
        "state_jurisdiction_id": state_jurisdiction_id,
    }
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------------- enrollment

def enrollment_payload(class_session_id, alcohol_server_id,
                       expected_class_session_version, **overrides) -> dict:
    payload = {
        "class_session_id": class_session_id,
        "alcohol_server_id": alcohol_server_id,
        "expected_class_session_version": expected_class_session_version,
    }
    payload.update(overrides)
    return payload


def attendance_payload(attended, **overrides) -> dict:
    payload = {"attended": attended}
    payload.update(overrides)
    return payload


def withdraw_payload(**overrides) -> dict:
    payload = {"withdrawal_reason": "transferred to a later class"}
    payload.update(overrides)
    return payload


def submit_attempt_payload(raw_correct_count, proctor_attestation=True, **overrides) -> dict:
    payload = {
        "raw_correct_count": raw_correct_count,
        "proctor_attestation": proctor_attestation,
    }
    payload.update(overrides)
    return payload


# ------------------------------------------------------------------------ registry chain

def transmit_payload(**overrides) -> dict:
    payload = {"batch_reference": "BATCH-2026-08"}
    payload.update(overrides)
    return payload


def acknowledge_accept_payload(**overrides) -> dict:
    payload = {"result": "ACCEPTED"}
    payload.update(overrides)
    return payload


def acknowledge_reject_payload(rejection_code="NAME_MISMATCH", **overrides) -> dict:
    payload = {"result": "REJECTED", "rejection_code": rejection_code}
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------- employer account

def employer_account_payload(**overrides) -> dict:
    payload = {"legal_name": "Lone Star Taverns LLC", "billing_state_code": "TX"}
    payload.update(overrides)
    return payload


def account_status_payload(account_status, **overrides) -> dict:
    payload = {"account_status": account_status}
    payload.update(overrides)
    return payload


def seat_credit_purchase_payload(seat_quantity=80, unit_price_cents=2500, **overrides) -> dict:
    payload = {"seat_quantity": seat_quantity, "unit_price_cents": unit_price_cents}
    payload.update(overrides)
    return payload


def employer_location_payload(state_jurisdiction_id, location_name="Alamo Taproom",
                              premise_type="ON_PREMISE",
                              annual_premium_cents=4821734, **overrides) -> dict:
    payload = {
        "location_name": location_name,
        "state_jurisdiction_id": state_jurisdiction_id,
        "premise_type": premise_type,
        "annual_premium_cents": annual_premium_cents,
    }
    payload.update(overrides)
    return payload


def dram_shop_document_payload(expected_employer_account_version, **overrides) -> dict:
    payload = {
        "insurer_name": "Brazos Mutual Casualty",
        "policy_number": "DS-2026-77410",
        "coverage_period_start": "2026-09-01T00:00:00Z",
        "coverage_period_end": "2027-09-01T00:00:00Z",
        "expected_employer_account_version": expected_employer_account_version,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------- server assignment

def server_assignment_payload(alcohol_server_id, role_title="Bartender", **overrides) -> dict:
    payload = {"alcohol_server_id": alcohol_server_id, "role_title": role_title}
    payload.update(overrides)
    return payload


def end_assignment_payload(**overrides) -> dict:
    payload = {"end_reason": "resigned"}
    payload.update(overrides)
    return payload
