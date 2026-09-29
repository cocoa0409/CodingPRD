"""Payload factories — one per resource, input fields only."""
import copy

from .constants import STATE_RULE_PRESETS, TEST_DEFAULTS


def state_rule_payload(state_code="CA", **overrides) -> dict:
    payload = copy.deepcopy(STATE_RULE_PRESETS[state_code])
    payload.update(overrides)
    return payload


def district_payload(**overrides) -> dict:
    payload = {
        "name": "Sending Unified",
        "district_code": TEST_DEFAULTS["SENDING_DISTRICT_CODE"],
        "state_code": "CA",
    }
    payload.update(overrides)
    return payload


def inspection_room_payload(**overrides) -> dict:
    payload = {
        "room_code": TEST_DEFAULTS["ROOM_CODE"],
        "site_name": "District Office",
        "seats": TEST_DEFAULTS["ROOM_SEATS"],
    }
    payload.update(overrides)
    return payload


def hearing_officer_payload(**overrides) -> dict:
    payload = {"full_name": "Marion Vetter", "credential": "DISTRICT_DESIGNEE"}
    payload.update(overrides)
    return payload


def student_payload(district_id, **overrides) -> dict:
    payload = {
        "district_id": district_id,
        "first_name": "Alex",
        "last_name": "Rivera",
        "dob": TEST_DEFAULTS["STUDENT_DOB"],
        "grade_level": TEST_DEFAULTS["GRADE_LEVEL"],
        "has_iep": False,
        "guardian_user_id": TEST_DEFAULTS["GUARDIAN_USER_ID"],
    }
    payload.update(overrides)
    return payload


def directory_optout_payload(categories=None, **overrides) -> dict:
    payload = {"directory_optout_categories": categories or ["NAME", "ADDRESS"]}
    payload.update(overrides)
    return payload


def directory_disclosure_payload(**overrides) -> dict:
    payload = {
        "recipient_name": "Regional Yearbook Vendor",
        "disclosed_categories": ["HONORS"],
    }
    payload.update(overrides)
    return payload


def withdrawal_payload(**overrides) -> dict:
    payload = {
        "effective_date": "2026-08-14",
        "destination_district_code": "TXD-9",
        "withdrawal_reason": "TRANSFER_OUT",
    }
    payload.update(overrides)
    return payload


def hold_payload(hold_type="LIBRARY_FINE") -> dict:
    return {"hold_type": hold_type}


def collect_component_payload(page_count, redacted_page_count=0, **overrides) -> dict:
    payload = {
        "status": "COLLECTED",
        "page_count": page_count,
        "redacted_page_count": redacted_page_count,
    }
    payload.update(overrides)
    return payload


def certify_component_payload(**overrides) -> dict:
    payload = {"status": "CERTIFIED"}
    payload.update(overrides)
    return payload


def exclude_component_payload(exclusion_reason="OTHER_STUDENT_INFO", **overrides) -> dict:
    payload = {"status": "EXCLUDED", "exclusion_reason": exclusion_reason}
    payload.update(overrides)
    return payload


def reinstate_component_payload(**overrides) -> dict:
    payload = {"status": "COLLECTED"}
    payload.update(overrides)
    return payload


def discipline_incident_payload(**overrides) -> dict:
    payload = {
        "incident_date": "2026-03-10",
        "action_type": "SUSPENSION",
        "description": "Repeated classroom disruption",
    }
    payload.update(overrides)
    return payload


def records_request_payload(student_id, requesting_district_id, responding_district_id, **overrides) -> dict:
    payload = {
        "student_id": student_id,
        "requesting_district_id": requesting_district_id,
        "responding_district_id": responding_district_id,
        "authorization_reference": "ENR-2026-0001",
    }
    payload.update(overrides)
    return payload


def validate_request_payload(**overrides) -> dict:
    payload = {"authorization_verified": True}
    payload.update(overrides)
    return payload


def mark_ready_payload(expected_cumulative_file_version, **overrides) -> dict:
    payload = {"expected_cumulative_file_version": expected_cumulative_file_version}
    payload.update(overrides)
    return payload


def release_payload(transmission_method="SECURE_PORTAL", **overrides) -> dict:
    payload = {"transmission_method": transmission_method}
    payload.update(overrides)
    return payload


def deny_payload(denial_reason="DUPLICATE_REQUEST", **overrides) -> dict:
    payload = {"denial_reason": denial_reason}
    payload.update(overrides)
    return payload


def inspection_request_payload(categories=None, copies_requested=False, **overrides) -> dict:
    payload = {
        "requested_categories": categories or ["ACADEMIC"],
        "copies_requested": copies_requested,
    }
    payload.update(overrides)
    return payload


def appointment_payload(room_id, start_at, end_at, expected_inspection_request_version, **overrides) -> dict:
    payload = {
        "room_id": room_id,
        "start_at": start_at,
        "end_at": end_at,
        "expected_inspection_request_version": expected_inspection_request_version,
    }
    payload.update(overrides)
    return payload


def attendance_payload(attended=True, **overrides) -> dict:
    payload = {"attended": attended}
    payload.update(overrides)
    return payload


def fee_transaction_payload(fee_transaction_type="PAYMENT", amount_cents=100, **overrides) -> dict:
    payload = {"fee_transaction_type": fee_transaction_type, "amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def amendment_request_payload(contested_component_id, **overrides) -> dict:
    payload = {
        "contested_component_id": contested_component_id,
        "contested_field": "gpa",
        "requested_change": "Restate term GPA as 3.40",
        "rationale": "Two grades were transposed",
    }
    payload.update(overrides)
    return payload


def amendment_decision_payload(outcome="DENY", **overrides) -> dict:
    payload = {"outcome": outcome, "decision_note": "Rubric confirmed"}
    payload.update(overrides)
    return payload


def hearing_schedule_payload(hearing_officer_id, hearing_start_at, hearing_end_at, **overrides) -> dict:
    payload = {
        "hearing_officer_id": hearing_officer_id,
        "hearing_start_at": hearing_start_at,
        "hearing_end_at": hearing_end_at,
    }
    payload.update(overrides)
    return payload


def statement_payload(statement_text="The transposed grades remain disputed.", **overrides) -> dict:
    payload = {"statement_text": statement_text}
    payload.update(overrides)
    return payload


def legal_demand_payload(**overrides) -> dict:
    payload = {
        "demand_type": "JUDICIAL_SUBPOENA",
        "issuing_authority": "Superior Court of CA",
        "case_reference": "CV-2026-0001",
        "production_scope": ["ACADEMIC"],
    }
    payload.update(overrides)
    return payload


def notification_payload(notified_party="PARENT", **overrides) -> dict:
    payload = {"notified_party": notified_party}
    payload.update(overrides)
    return payload


def production_payload(produced_page_count=40, **overrides) -> dict:
    payload = {"produced_page_count": produced_page_count}
    payload.update(overrides)
    return payload


def destruction_payload(destruction_method="CROSS_CUT_SHRED", **overrides) -> dict:
    payload = {
        "destruction_method": destruction_method,
        "certification_note": "Shredded under dual control",
    }
    payload.update(overrides)
    return payload


def clock_payload(current_utc) -> dict:
    return {"current_utc": current_utc}
