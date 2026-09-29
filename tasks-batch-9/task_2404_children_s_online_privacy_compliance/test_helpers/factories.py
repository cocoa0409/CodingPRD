"""Payload factories — one per entity, carrying only client-supplied input fields."""

from typing import List, Optional

from .constants import REQUIRED_CONTENT_KEYS, TEST_DEFAULTS


def online_service_payload(**overrides) -> dict:
    payload = {
        "name": "Test Kids Service",
        "operator_organization": TEST_DEFAULTS["OPERATOR_ORGANIZATION"],
        "service_category": TEST_DEFAULTS["SERVICE_CATEGORY"],
        "subject_matter_code": TEST_DEFAULTS["SUBJECT_MATTER_CODE"],
    }
    payload.update(overrides)
    return payload


def design_factor_evidence_payload(service_id: str, factor_code: str, rating: str, **overrides) -> dict:
    payload = {
        "service_id": service_id,
        "evidence_kind": "DESIGN_FACTOR",
        "factor_code": factor_code,
        "rating": rating,
    }
    payload.update(overrides)
    return payload


def audience_sample_evidence_payload(
    service_id: str,
    measurement_method: str,
    period_start: str,
    period_end: str,
    total_users: int,
    users_under_13: int,
    sample_verified: Optional[bool] = None,
    **overrides,
) -> dict:
    payload = {
        "service_id": service_id,
        "evidence_kind": "AUDIENCE_SAMPLE",
        "measurement_method": measurement_method,
        "period_start": period_start,
        "period_end": period_end,
        "total_users": total_users,
        "users_under_13": users_under_13,
    }
    if sample_verified is not None:
        payload["sample_verified"] = sample_verified
    payload.update(overrides)
    return payload


def age_screen_payload(service_id: str, **overrides) -> dict:
    payload = {
        "service_id": service_id,
        "mechanism": "NEUTRAL_DOB_ENTRY",
        "retry_allowed_on_fail": False,
        "outcome_session_persisted": True,
    }
    payload.update(overrides)
    return payload


def parental_notice_payload(
    service_id: str,
    expected_service_version: int,
    content_keys: Optional[List[str]] = None,
    **overrides,
) -> dict:
    payload = {
        "service_id": service_id,
        "notice_label": "Notice r1",
        "delivery_channel": TEST_DEFAULTS["DELIVERY_CHANNEL"],
        "content_keys": list(REQUIRED_CONTENT_KEYS) if content_keys is None else content_keys,
        "expected_service_version": expected_service_version,
    }
    payload.update(overrides)
    return payload


def activity_payload(
    service_id: str,
    activity_code: str = TEST_DEFAULTS["ACTIVITY_CODE"],
    participation_required_elements: Optional[List[str]] = None,
    **overrides,
) -> dict:
    payload = {
        "service_id": service_id,
        "activity_code": activity_code,
        "participation_required_elements": (
            ["SCREEN_NAME"]
            if participation_required_elements is None
            else participation_required_elements
        ),
    }
    payload.update(overrides)
    return payload


def consent_request_payload(
    service_id: str,
    notice_id: str,
    parent_email: str,
    child_pseudonym: str,
    expected_service_version: int,
    intended_uses: Optional[List[str]] = None,
    consent_method: str = "KNOWLEDGE_BASED_AUTH",
    **overrides,
) -> dict:
    payload = {
        "service_id": service_id,
        "notice_id": notice_id,
        "parent_email": parent_email,
        "child_pseudonym": child_pseudonym,
        "intended_uses": ["PARTICIPATION_CORE"] if intended_uses is None else intended_uses,
        "consent_method": consent_method,
        "expected_service_version": expected_service_version,
    }
    payload.update(overrides)
    return payload


def child_data_record_payload(
    service_id: str,
    consent_request_id: str,
    activity_id: str,
    data_element_code: str = "SCREEN_NAME",
    purpose_code: str = "PARTICIPATION_CORE",
    age_screen_outcome: str = "UNDER_13",
    **overrides,
) -> dict:
    payload = {
        "service_id": service_id,
        "consent_request_id": consent_request_id,
        "activity_id": activity_id,
        "data_element_code": data_element_code,
        "purpose_code": purpose_code,
        "age_screen_outcome": age_screen_outcome,
    }
    payload.update(overrides)
    return payload


def parental_rights_request_payload(
    service_id: str,
    consent_request_id: str,
    right_type: str,
    requester_email: str,
    **overrides,
) -> dict:
    payload = {
        "service_id": service_id,
        "consent_request_id": consent_request_id,
        "right_type": right_type,
        "requester_email": requester_email,
    }
    payload.update(overrides)
    return payload


def third_party_integration_payload(
    service_id: str,
    vendor_name: str,
    integration_type: str,
    collects_persistent_identifier: bool,
    placement_area: str,
    **overrides,
) -> dict:
    payload = {
        "service_id": service_id,
        "vendor_name": vendor_name,
        "integration_type": integration_type,
        "collects_persistent_identifier": collects_persistent_identifier,
        "placement_area": placement_area,
    }
    payload.update(overrides)
    return payload


def retention_schedule_payload(
    service_id: str,
    data_element_code: str = "SCREEN_NAME",
    purpose_code: str = "PARTICIPATION_CORE",
    retention_days: int = 30,
    disposal_method: str = "ANONYMIZE",
    effective_from: str = TEST_DEFAULTS["SCHEDULE_EFFECTIVE_FROM"],
    effective_to: str = TEST_DEFAULTS["SCHEDULE_EFFECTIVE_TO"],
    defined_purpose_statement: str = "Retained for participation, then disposed of.",
    **overrides,
) -> dict:
    payload = {
        "service_id": service_id,
        "data_element_code": data_element_code,
        "purpose_code": purpose_code,
        "retention_days": retention_days,
        "disposal_method": disposal_method,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "defined_purpose_statement": defined_purpose_statement,
    }
    payload.update(overrides)
    return payload


def safe_harbor_program_payload(
    program_name: str = "Test Seal", regulator_approved: bool = True, **overrides
) -> dict:
    payload = {"program_name": program_name, "regulator_approved": regulator_approved}
    payload.update(overrides)
    return payload


def safe_harbor_assessment_payload(
    service_id: str, program_id: str, assessment_year: int = 2026, **overrides
) -> dict:
    payload = {
        "service_id": service_id,
        "program_id": program_id,
        "assessment_year": assessment_year,
    }
    payload.update(overrides)
    return payload
