"""Payload factories — one per entity, input fields only (PRD section 4).

Factories never invent system-managed fields (status, derived counters,
timestamps stamped from the logical clock); they assemble only the inputs the
PRD names for each creation endpoint.
"""
from .constants import (
    DEFAULT_CE_ETHICS_REQUIRED_HOURS,
    DEFAULT_CE_REQUIRED_HOURS,
    DEFAULT_EFFECTIVE_DATE,
    DEFAULT_EXPIRATION_DATE,
    DEFAULT_ISSUE_DATE,
)


def create_agency_payload(name="Test Agency", resident_state_code="CA", **overrides) -> dict:
    payload = {"name": name, "resident_state_code": resident_state_code}
    payload.update(overrides)
    return payload


def create_producer_payload(
    npn="NPN-0001",
    full_name="Test Producer",
    resident_state_code="CA",
    agency_id=None,
    **overrides,
) -> dict:
    payload = {
        "npn": npn,
        "full_name": full_name,
        "resident_state_code": resident_state_code,
    }
    if agency_id is not None:
        payload["agency_id"] = agency_id
    payload.update(overrides)
    return payload


def create_license_payload(
    producer_id=None,
    agency_id=None,
    state_code="CA",
    license_class="RESIDENT",
    lines_of_authority=None,
    issue_date=DEFAULT_ISSUE_DATE,
    expiration_date=DEFAULT_EXPIRATION_DATE,
    ce_required_hours=DEFAULT_CE_REQUIRED_HOURS,
    ce_ethics_required_hours=DEFAULT_CE_ETHICS_REQUIRED_HOURS,
    **overrides,
) -> dict:
    payload = {
        "state_code": state_code,
        "license_class": license_class,
        "lines_of_authority": list(lines_of_authority or ["LIFE"]),
        "issue_date": issue_date,
        "expiration_date": expiration_date,
        "ce_required_hours": ce_required_hours,
        "ce_ethics_required_hours": ce_ethics_required_hours,
    }
    if producer_id is not None:
        payload["producer_id"] = producer_id
    if agency_id is not None:
        payload["agency_id"] = agency_id
    payload.update(overrides)
    return payload


def create_ce_credit_payload(
    license_id,
    provider_name="CEU Providers",
    course_title="CE Course",
    category="GENERAL",
    credit_hours=10,
    completed_on="2026-06-01T00:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "license_id": license_id,
        "provider_name": provider_name,
        "course_title": course_title,
        "category": category,
        "credit_hours": credit_hours,
        "completed_on": completed_on,
    }
    payload.update(overrides)
    return payload


def create_appointment_payload(
    producer_id=None,
    agency_id=None,
    state_code="CA",
    lines_of_authority=None,
    effective_date=DEFAULT_EFFECTIVE_DATE,
    **overrides,
) -> dict:
    payload = {
        "state_code": state_code,
        "lines_of_authority": list(lines_of_authority or ["LIFE"]),
        "effective_date": effective_date,
    }
    if producer_id is not None:
        payload["producer_id"] = producer_id
    if agency_id is not None:
        payload["agency_id"] = agency_id
    payload.update(overrides)
    return payload


def create_application_payload(
    producer_id,
    state_code="CA",
    line_of_authority="LIFE",
    applicant_name="Applicant",
    premium_cents=1_000_000,
    **overrides,
) -> dict:
    payload = {
        "producer_id": producer_id,
        "state_code": state_code,
        "line_of_authority": line_of_authority,
        "applicant_name": applicant_name,
        "premium_cents": premium_cents,
    }
    payload.update(overrides)
    return payload


def create_regulatory_action_payload(
    producer_id=None,
    agency_id=None,
    state_code="CA",
    action_type="FINE",
    fine_amount_cents=None,
    effective_date="2026-08-01T00:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "state_code": state_code,
        "action_type": action_type,
        "effective_date": effective_date,
    }
    if producer_id is not None:
        payload["producer_id"] = producer_id
    if agency_id is not None:
        payload["agency_id"] = agency_id
    if fine_amount_cents is not None:
        payload["fine_amount_cents"] = fine_amount_cents
    payload.update(overrides)
    return payload


def create_inquiry_payload(
    producer_id=None,
    agency_id=None,
    state_code="TX",
    reference_number="INQ-0001",
    **overrides,
) -> dict:
    payload = {
        "state_code": state_code,
        "reference_number": reference_number,
    }
    if producer_id is not None:
        payload["producer_id"] = producer_id
    if agency_id is not None:
        payload["agency_id"] = agency_id
    payload.update(overrides)
    return payload
