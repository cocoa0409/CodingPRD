"""Payload factories — one per entity, client-supplied input fields only.

Every factory takes `**overrides` so a test can pin exactly the field under
examination and let the rest fall back to a sensible value. Optional fields are
omitted rather than defaulted, so the server's own defaults are what get
exercised unless a test asks otherwise.
"""
from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


def board_config_payload(**overrides: Any) -> Dict[str, Any]:
    """Registration payload for a state board of nursing."""
    payload: Dict[str, Any] = {
        "state_code": TEST_DEFAULTS["BOARD_STATE_CODE"],
        "board_name": TEST_DEFAULTS["BOARD_NAME"],
    }
    payload.update(overrides)
    return payload


def education_program_payload(state_board_config_id: str, **overrides: Any) -> Dict[str, Any]:
    """Registration payload for a nursing education program."""
    payload: Dict[str, Any] = {
        "state_board_config_id": state_board_config_id,
        "program_code": "OH-BSN-01",
        "program_name": "Buckeye BSN",
        "degree_level": "BSN",
        "nclex_first_time_pass_rate_bp": 8800,
        "approval_expires_on": TEST_DEFAULTS["PROGRAM_APPROVAL_EXPIRES_ON"],
    }
    payload.update(overrides)
    return payload


def nurse_payload(home_board_config_id: str, **overrides: Any) -> Dict[str, Any]:
    """Creation payload for a nurse identity record."""
    payload: Dict[str, Any] = {
        "home_board_config_id": home_board_config_id,
        "full_name": "Dana Reed",
        "birth_year": 1988,
        "ssn_last4": "4417",
        "declared_primary_state": "OH",
    }
    payload.update(overrides)
    return payload


def residency_evidence_entry(evidence_type: str, state_code: str,
                             effective_date: str) -> Dict[str, Any]:
    """One entry of a nurse's ordered residency evidence array."""
    return {
        "evidence_type": evidence_type,
        "state_code": state_code,
        "effective_date": effective_date,
    }


def license_application_payload(nurse_id: str, board_config_id: str,
                                education_program_id: Optional[str] = None,
                                **overrides: Any) -> Dict[str, Any]:
    """Examination-route RN application payload."""
    payload: Dict[str, Any] = {
        "nurse_id": nurse_id,
        "board_config_id": board_config_id,
        "pathway": "EXAMINATION",
        "credential_type": "RN",
        "nclex_result": "PASS",
    }
    if education_program_id is not None:
        payload["education_program_id"] = education_program_id
    payload.update(overrides)
    return payload


def endorsement_application_payload(nurse_id: str, board_config_id: str,
                                    **overrides: Any) -> Dict[str, Any]:
    """Endorsement-route RN application payload."""
    payload: Dict[str, Any] = {
        "nurse_id": nurse_id,
        "board_config_id": board_config_id,
        "pathway": "ENDORSEMENT",
        "credential_type": "RN",
        "prior_license_state": "MI",
        "prior_license_number": "MI-RN-99881",
    }
    payload.update(overrides)
    return payload


def screening_offense_record(offense_code: str, disposition_date: str) -> Dict[str, Any]:
    """One entry of the criminal-history vendor's answer."""
    return {"offense_code": offense_code, "disposition_date": disposition_date}


def license_payload(source_application_id: str, **overrides: Any) -> Dict[str, Any]:
    """Credential minting payload — the only supplied value is the application."""
    payload: Dict[str, Any] = {"source_application_id": source_application_id}
    payload.update(overrides)
    return payload


def renewal_application_payload(license_id: str, expected_license_version: int,
                                **overrides: Any) -> Dict[str, Any]:
    """Renewal filing creation payload, carrying the mandatory version guard."""
    payload: Dict[str, Any] = {
        "license_id": license_id,
        "expected_license_version": expected_license_version,
    }
    payload.update(overrides)
    return payload


def ce_record_payload(**overrides: Any) -> Dict[str, Any]:
    """Continuing-education credit claim payload."""
    payload: Dict[str, Any] = {
        "provider_code": "OHNA-100",
        "provider_accredited": True,
        "category": "LIVE_CONTACT",
        "minutes": 1800,
        "completion_date": "2027-03-15T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def practice_hour_period(start_on: str, end_on: str, hours: int,
                         employer_name: str = "Mercy General Hospital") -> Dict[str, Any]:
    """One documented employment period: inclusive start, exclusive end, hours."""
    return {
        "employer_name": employer_name,
        "start_on": start_on,
        "end_on": end_on,
        "hours": hours,
    }


def complaint_payload(license_id: str, **overrides: Any) -> Dict[str, Any]:
    """Complaint intake payload."""
    payload: Dict[str, Any] = {
        "license_id": license_id,
        "complainant_type": "PATIENT",
        "violation_category": "PRACTICE_STANDARD",
        "incident_date": "2026-07-02T00:00:00Z",
        "allegation_codes": [],
        "employer_custodian_codes": [TEST_DEFAULTS["CUSTODIAN_PRIMARY"]],
    }
    payload.update(overrides)
    return payload


def evidence_request_payload(**overrides: Any) -> Dict[str, Any]:
    """Records demand payload with a half-open hold window."""
    payload: Dict[str, Any] = {
        "record_class": "EMPLOYER_PERSONNEL",
        "custodian_code": TEST_DEFAULTS["CUSTODIAN_PRIMARY"],
        "hold_start_at": "2026-08-05T00:00:00Z",
        "hold_end_at": "2026-09-05T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def monitoring_agreement_payload(nurse_id: str, complaint_id: str,
                                 **overrides: Any) -> Dict[str, Any]:
    """Alternative-to-discipline monitoring offer payload."""
    payload: Dict[str, Any] = {
        "nurse_id": nurse_id,
        "complaint_id": complaint_id,
        "start_date": "2026-09-01T00:00:00Z",
        "end_date": "2027-09-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def disciplinary_proceeding_payload(complaint_id: str, expected_complaint_version: int,
                                    seated_member_user_ids: Optional[List[str]] = None,
                                    **overrides: Any) -> Dict[str, Any]:
    """Proceeding opening payload, carrying the mandatory version guard."""
    payload: Dict[str, Any] = {
        "complaint_id": complaint_id,
        "expected_complaint_version": expected_complaint_version,
        "seated_member_user_ids": seated_member_user_ids
        if seated_member_user_ids is not None
        else ["bm-1", "bm-2", "bm-3"],
        "hearing_date": "2026-09-15T00:00:00Z",
        "notice_period_days": 30,
    }
    payload.update(overrides)
    return payload
