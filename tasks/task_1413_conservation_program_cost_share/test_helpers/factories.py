"""Payload factories — one per creatable resource, input fields only (PRD §3/§4)."""
from .constants import (
    DEFAULT_ADVANCE_CAP_PCT,
    DEFAULT_ITEM_DEADLINE,
    DEFAULT_WINDOW_END,
    DEFAULT_WINDOW_START,
    TEST_DEFAULTS,
)


def create_program_payload(**overrides) -> dict:
    defaults = {
        "program_name": "Test Program",
        "fiscal_year": 2026,
        "state_code": "IA",
        "window_start": DEFAULT_WINDOW_START,
        "window_end": DEFAULT_WINDOW_END,
    }
    defaults.update(overrides)
    return defaults


def create_pool_payload(**overrides) -> dict:
    defaults = {
        "pool_type": "GENERAL",
        "allocated_cents": TEST_DEFAULTS["POOL_GENERAL_ALLOCATED"],
    }
    defaults.update(overrides)
    return defaults


def create_rate_payload(**overrides) -> dict:
    defaults = {
        "practice_code": "FENCE",
        "unit": "FOOT",
        "standard_rate_cents": TEST_DEFAULTS["FENCE_STANDARD_RATE"],
        "hu_rate_cents": TEST_DEFAULTS["FENCE_HU_RATE"],
        "lifespan_years": TEST_DEFAULTS["FENCE_LIFESPAN_YEARS"],
    }
    defaults.update(overrides)
    return defaults


def create_criterion_payload(**overrides) -> dict:
    defaults = {
        "criterion_code": "SOIL_HEALTH",
        "weight": 1.0,
        "max_points": 40,
    }
    defaults.update(overrides)
    return defaults


def create_applicant_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Test Producer",
        "hu_category": "NONE",
        "parcel_ids": ["P-100"],
    }
    defaults.update(overrides)
    return defaults


def planned_practice(practice_code="FENCE", quantity=1000) -> dict:
    return {"practice_code": practice_code, "quantity": quantity}


def create_application_payload(program_id, applicant_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "applicant_id": applicant_id,
        "parcel_id": "P-100",
        "planned_practices": [planned_practice()],
        "self_reported_answers": {"SOIL_HEALTH": 10},
    }
    defaults.update(overrides)
    return defaults


def screen_payload(decision="SCREENED_IN", verified_answers=None) -> dict:
    payload = {"decision": decision}
    if verified_answers is not None:
        payload["verified_answers"] = verified_answers
    return payload


def create_contract_payload(application_id) -> dict:
    return {"application_id": application_id}


def create_practice_item_payload(**overrides) -> dict:
    defaults = {
        "practice_code": "FENCE",
        "planned_quantity": 1000,
        "implementation_deadline": DEFAULT_ITEM_DEADLINE,
    }
    defaults.update(overrides)
    return defaults


def patch_practice_item_payload(expected_item_version, **overrides) -> dict:
    payload = {"expected_item_version": expected_item_version}
    payload.update(overrides)
    return payload


def certify_payload(certified_quantity=1000) -> dict:
    return {"certified_quantity": certified_quantity}


def create_payment_request_payload(contract_id, practice_item_id, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "practice_item_id": practice_item_id,
        "documented_cost_cents": 300000,
        "documentation_refs": ["receipt-1"],
    }
    defaults.update(overrides)
    return defaults


def create_advance_payload(practice_item_id, issued_cents=180000) -> dict:
    return {"practice_item_id": practice_item_id, "issued_cents": issued_cents}


def return_advance_payload(amount_cents) -> dict:
    return {"amount_cents": amount_cents}


def create_modification_payload(kind, **overrides) -> dict:
    payload = {"kind": kind}
    payload.update(overrides)
    return payload


def adjudicate_modification_payload(expected_contract_version) -> dict:
    return {"expected_contract_version": expected_contract_version}


def create_spot_check_payload(contract_id, practice_item_id, payment_request_id=None) -> dict:
    payload = {"contract_id": contract_id, "practice_item_id": practice_item_id}
    if payment_request_id is not None:
        payload["payment_request_id"] = payment_request_id
    return payload


def record_result_payload(result="PASS", failure_reason=None) -> dict:
    payload = {"result": result}
    if failure_reason is not None:
        payload["failure_reason"] = failure_reason
    return payload


def pay_demand_payload(amount_cents) -> dict:
    return {"amount_cents": amount_cents}
