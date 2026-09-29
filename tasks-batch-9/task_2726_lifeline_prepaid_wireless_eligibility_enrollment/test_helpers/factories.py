"""Request payload factories.

Every money field is emitted as a JSON integer number of cents, never a string.
Identifier-shaped inputs that the API enforces uniqueness on (spin_id, imei and the
subscriber identity triple) are drawn from process-local sequences so a single test
can create many rows without colliding.
"""

import itertools
from typing import Any, Dict, List, Optional

_spin_seq = itertools.count(1)
_sac_seq = itertools.count(1)
_imei_seq = itertools.count(1)
_person_seq = itertools.count(1)


def next_spin_id() -> str:
    """A distinct nine digit SPIN."""
    return f"1430{next(_spin_seq):05d}"


def next_study_area_code() -> str:
    """A distinct six digit study area code."""
    return f"48{next(_sac_seq):04d}"


def next_imei() -> str:
    """A distinct fifteen digit IMEI."""
    return f"35000000{next(_imei_seq):07d}"


def provider_payload(
    name: str = "SafeLink Wireless",
    spin_id: Optional[str] = None,
    study_area_code: Optional[str] = None,
    licensed_state_codes: Optional[List[str]] = None,
    enrollment_cap: Optional[int] = 50,
    status: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name,
        "spin_id": spin_id or next_spin_id(),
        "study_area_code": study_area_code or next_study_area_code(),
        "licensed_state_codes": list(licensed_state_codes or ["TX"]),
    }
    if enrollment_cap is not None:
        payload["enrollment_cap"] = enrollment_cap
    if status is not None:
        payload["status"] = status
    payload.update(overrides)
    return payload


def address_payload(
    address_line1: str = "1200 N Main St",
    city: str = "El Paso",
    state_code: str = "TX",
    postal_code: str = "79901",
    unit_designator: Optional[str] = "Apt 4B",
    include_unit: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "address_line1": address_line1,
        "city": city,
        "state_code": state_code,
        "postal_code": postal_code,
    }
    if include_unit:
        payload["unit_designator"] = unit_designator
    payload.update(overrides)
    return payload


def distinct_address_payload(index: int, state_code: str = "TX") -> Dict[str, Any]:
    """An address that cannot collide with any other index in the same test."""
    return {
        "address_line1": f"{100 + index} Distinct Way",
        "city": "El Paso",
        "state_code": state_code,
        "postal_code": "79901",
    }


def subscriber_payload(
    address_id: str,
    full_name: str = "Ana Ruiz",
    date_of_birth: str = "1980-04-11",
    last4_ssn: str = "4417",
    household_size: int = 4,
    annual_income_cents: int = 3000000,
    last_3mo_income_cents: Optional[int] = 750000,
    qualifying_benefit: Optional[str] = "NONE",
    tribal_lands_flag: Optional[bool] = False,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": full_name,
        "date_of_birth": date_of_birth,
        "last4_ssn": last4_ssn,
        "address_id": address_id,
        "household_size": household_size,
        "annual_income_cents": annual_income_cents,
    }
    if last_3mo_income_cents is not None:
        payload["last_3mo_income_cents"] = last_3mo_income_cents
    if qualifying_benefit is not None:
        payload["qualifying_benefit"] = qualifying_benefit
    if tribal_lands_flag is not None:
        payload["tribal_lands_flag"] = tribal_lands_flag
    payload.update(overrides)
    return payload


def distinct_person_fields() -> Dict[str, Any]:
    """A name, birth date and SSN suffix triple that no other call reuses."""
    n = next(_person_seq)
    return {
        "full_name": f"Person Number{n:03d}",
        "date_of_birth": "1980-04-11",
        "last4_ssn": f"{(4000 + n) % 10000:04d}",
    }


def eligibility_check_payload(
    claimed_basis: str = "INCOME",
    proof_document_ref: Optional[str] = "DOC-1",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"claimed_basis": claimed_basis}
    if proof_document_ref is not None:
        payload["proof_document_ref"] = proof_document_ref
    payload.update(overrides)
    return payload


def verifier_result_payload(
    verifier_outcome: str = "MATCH",
    verifier_reason_code: Optional[str] = None,
    matched_benefit: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"verifier_outcome": verifier_outcome}
    if verifier_reason_code is not None:
        payload["verifier_reason_code"] = verifier_reason_code
    if matched_benefit is not None:
        payload["matched_benefit"] = matched_benefit
    payload.update(overrides)
    return payload


def resubmit_documentation_payload(
    proof_document_ref: str = "DOC-REPLACEMENT", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"proof_document_ref": proof_document_ref}
    payload.update(overrides)
    return payload


def enrollment_payload(
    subscriber_id: str,
    provider_id: str,
    eligibility_check_id: str,
    certified_address_id: str,
    service_type: str = "VOICE",
    one_per_household_attested: Optional[bool] = True,
    benefit_start_date: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "subscriber_id": subscriber_id,
        "provider_id": provider_id,
        "eligibility_check_id": eligibility_check_id,
        "certified_address_id": certified_address_id,
        "service_type": service_type,
    }
    if one_per_household_attested is not None:
        payload["one_per_household_attested"] = one_per_household_attested
    if benefit_start_date is not None:
        payload["benefit_start_date"] = benefit_start_date
    payload.update(overrides)
    return payload


def usage_payload(
    usage_at: Optional[str] = None,
    usage_kind: Optional[str] = "OUTBOUND_CALL",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if usage_at is not None:
        payload["usage_at"] = usage_at
    if usage_kind is not None:
        payload["usage_kind"] = usage_kind
    payload.update(overrides)
    return payload


def recertify_payload(
    household_size: int = 4,
    annual_income_cents: int = 3000000,
    last_3mo_income_cents: int = 750000,
    attested_qualifying_benefit: str = "NONE",
    attestation_ref: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "household_size": household_size,
        "annual_income_cents": annual_income_cents,
        "last_3mo_income_cents": last_3mo_income_cents,
        "attested_qualifying_benefit": attested_qualifying_benefit,
    }
    if attestation_ref is not None:
        payload["attestation_ref"] = attestation_ref
    payload.update(overrides)
    return payload


def de_enroll_payload(
    de_enrollment_reason: str = "SUBSCRIBER_REQUEST",
    note: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"de_enrollment_reason": de_enrollment_reason}
    if note is not None:
        payload["note"] = note
    payload.update(overrides)
    return payload


def device_payload(
    imei: Optional[str] = None,
    model_tier: str = "BASIC",
    unit_cost_cents: int = 2100,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "imei": imei or next_imei(),
        "model_tier": model_tier,
        "unit_cost_cents": unit_cost_cents,
    }
    payload.update(overrides)
    return payload


def device_issuance_payload(
    device_id: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if device_id is not None:
        payload["device_id"] = device_id
    payload.update(overrides)
    return payload


def device_return_payload(
    return_condition: str = "GOOD", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"return_condition": return_condition}
    payload.update(overrides)
    return payload


def service_transfer_payload(
    enrollment_id: str,
    target_provider_id: str,
    expected_enrollment_version: int,
    subscriber_consent_ref: str = "CONSENT-1",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "enrollment_id": enrollment_id,
        "target_provider_id": target_provider_id,
        "subscriber_consent_ref": subscriber_consent_ref,
        "expected_enrollment_version": expected_enrollment_version,
    }
    payload.update(overrides)
    return payload


def transfer_accept_payload(
    acceptance_note: Optional[str] = "port accepted", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if acceptance_note is not None:
        payload["acceptance_note"] = acceptance_note
    payload.update(overrides)
    return payload


def transfer_reject_payload(
    rejection_reason: str = "CONSENT_INVALID",
    rejection_note: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"rejection_reason": rejection_reason}
    if rejection_note is not None:
        payload["rejection_note"] = rejection_note
    payload.update(overrides)
    return payload


def claim_payload(
    provider_id: str,
    service_month: str,
    expected_provider_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "provider_id": provider_id,
        "service_month": service_month,
        "expected_provider_version": expected_provider_version,
    }
    payload.update(overrides)
    return payload


def claim_file_payload(
    certifying_officer_ref: str = "OFFICER-1", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"certifying_officer_ref": certifying_officer_ref}
    payload.update(overrides)
    return payload


def audit_draw_payload(sample_size: int = 1, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"sample_size": sample_size}
    payload.update(overrides)
    return payload


def adjudicate_payload(
    finding: str = "COMPLIANT",
    finding_note: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"finding": finding}
    if finding_note is not None:
        payload["finding_note"] = finding_note
    payload.update(overrides)
    return payload


def duplicate_resolution_payload(
    resolution: str,
    expected_address_version: int,
    declared_household_count: Optional[int] = None,
    independent_household_worksheet_ref: Optional[str] = None,
    resolution_note: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "resolution": resolution,
        "expected_address_version": expected_address_version,
    }
    if declared_household_count is not None:
        payload["declared_household_count"] = declared_household_count
    if independent_household_worksheet_ref is not None:
        payload["independent_household_worksheet_ref"] = (
            independent_household_worksheet_ref
        )
    if resolution_note is not None:
        payload["resolution_note"] = resolution_note
    payload.update(overrides)
    return payload


def subscriber_case_payload(
    subscriber_id: str,
    enrollment_id: str,
    case_type: str = "SERVICE_COMPLAINT",
    narrative: str = "My handset stopped connecting to the network last week",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "subscriber_id": subscriber_id,
        "enrollment_id": enrollment_id,
        "case_type": case_type,
        "narrative": narrative,
    }
    payload.update(overrides)
    return payload


def assign_review_payload(reviewer_ref: str = "REV-1", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reviewer_ref": reviewer_ref}
    payload.update(overrides)
    return payload


def decide_case_payload(
    decision: str,
    decision_rationale: str = "the record supports this outcome",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "decision": decision,
        "decision_rationale": decision_rationale,
    }
    payload.update(overrides)
    return payload
