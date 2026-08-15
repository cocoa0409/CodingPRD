"""Payload factories — one per creatable resource, input fields only
(PRD §3–§4). Every factory accepts **overrides so tests control exactly the
values their claim exercises."""
from .constants import (
    APPLICATION_DEFAULTS,
    HOUSEHOLD_DEFAULTS,
    PAYMENT_DEFAULTS,
    POLICY_DEFAULTS,
    SOURCE_DEFAULTS,
    VENDOR_DEFAULTS,
)


def create_household_payload(**overrides) -> dict:
    payload = dict(HOUSEHOLD_DEFAULTS)
    payload.update(overrides)
    return payload


def create_policy_payload(**overrides) -> dict:
    payload = dict(POLICY_DEFAULTS)
    payload.update(overrides)
    return payload


def create_vendor_payload(**overrides) -> dict:
    payload = dict(VENDOR_DEFAULTS)
    payload.update(overrides)
    return payload


def create_funding_source_payload(**overrides) -> dict:
    payload = dict(SOURCE_DEFAULTS)
    payload["allowed_categories"] = list(payload["allowed_categories"])
    payload.update(overrides)
    return payload


def create_application_payload(household_id, vendor_id, **overrides) -> dict:
    payload = dict(APPLICATION_DEFAULTS)
    payload.update({"household_id": household_id, "vendor_id": vendor_id})
    payload.update(overrides)
    return payload


def create_document_payload(doc_type="EVICTION_NOTICE", file_reference="s3://docs/doc.pdf") -> dict:
    return {"doc_type": doc_type, "file_reference": file_reference}


def create_verification_payload(expected_application_version) -> dict:
    return {"expected_application_version": expected_application_version}


def complete_verification_payload(outcome, confirmed_amount_cents=None, outcome_notes=None) -> dict:
    payload = {"outcome": outcome}
    if confirmed_amount_cents is not None:
        payload["confirmed_amount_cents"] = confirmed_amount_cents
    if outcome_notes is not None:
        payload["outcome_notes"] = outcome_notes
    return payload


def create_duplication_check_payload(expected_application_version, agency_name="County HHS") -> dict:
    return {
        "agency_name": agency_name,
        "expected_application_version": expected_application_version,
    }


def resolve_duplication_check_payload(result, resolution_notes=None) -> dict:
    payload = {"result": result}
    if resolution_notes is not None:
        payload["resolution_notes"] = resolution_notes
    return payload


def override_duplication_check_payload(override_justification="override approved") -> dict:
    return {"override_justification": override_justification}


def deny_application_payload(reason_code="PROGRAM_DIRECTED") -> dict:
    return {"reason_code": reason_code}


def appeal_application_payload(appeal_reason="new documentation obtained") -> dict:
    return {"appeal_reason": appeal_reason}


def create_payment_payload(vendor_id, funding_source_id, amount_cents, **overrides) -> dict:
    payload = dict(PAYMENT_DEFAULTS)
    payload.update(
        {
            "vendor_id": vendor_id,
            "funding_source_id": funding_source_id,
            "amount_cents": amount_cents,
        }
    )
    payload.update(overrides)
    return payload


def create_case_note_payload(note_type="GENERAL", body="case note body", **overrides) -> dict:
    payload = {"note_type": note_type, "body": body}
    payload.update(overrides)
    return payload


def deposit_payload(amount_cents) -> dict:
    return {"amount_cents": amount_cents}


def adjust_award_payload(new_awarded_amount_cents, expected_award_version) -> dict:
    return {
        "new_awarded_amount_cents": new_awarded_amount_cents,
        "expected_award_version": expected_award_version,
    }


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
