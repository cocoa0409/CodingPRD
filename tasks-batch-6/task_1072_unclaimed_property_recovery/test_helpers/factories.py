"""Payload factories — one per entity, request input fields only."""

DEFAULTS = {
    "HOLDER_LEGAL_NAME": "Acme Bank",
    "INCORPORATION_STATE": "NY",
    "HOLDER_TYPE": "BANK",
    "PT_CODE": "AC01",
    "PT_NAME": "Savings",
    "DORMANCY_PERIOD_YEARS": 3,
    "DORMANCY_BASIS": "LAST_ACTIVITY",
    "STATE_CODE": "CA",
    "OWNER_NAME": "Jane Doe",
    "SSN_LAST4": "1234",
    "ADDRESS_STATE": "CA",
    "EMAIL": "jane@example.com",
    "FIRM_NAME": "FindIt LLC",
    "REGISTERED_STATE": "CA",
    "LICENSE_NUMBER": "L1",
    "MAX_FEE_PCT": 0.10,
    "AMOUNT_CENTS": 100000,
    "LAST_ACTIVITY_DATE": "2020-01-01T00:00:00Z",
    "ISSUE_DATE": "2020-01-01T00:00:00Z",
    "REPORT_YEAR": 2026,
}


def create_holder_payload(**overrides) -> dict:
    payload = {
        "legal_name": DEFAULTS["HOLDER_LEGAL_NAME"],
        "incorporation_state": DEFAULTS["INCORPORATION_STATE"],
        "holder_type": DEFAULTS["HOLDER_TYPE"],
    }
    payload.update(overrides)
    return payload


def create_property_type_payload(**overrides) -> dict:
    payload = {
        "code": DEFAULTS["PT_CODE"],
        "name": DEFAULTS["PT_NAME"],
        "dormancy_period_years": DEFAULTS["DORMANCY_PERIOD_YEARS"],
        "dormancy_basis": DEFAULTS["DORMANCY_BASIS"],
        "interest_bearing": False,
        "due_diligence_required": False,
        "due_diligence_min_days": 0,
    }
    payload.update(overrides)
    return payload


def create_state_account_payload(state_code=DEFAULTS["STATE_CODE"], **overrides) -> dict:
    payload = {"state_code": state_code}
    payload.update(overrides)
    return payload


def create_owner_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["OWNER_NAME"],
        "ssn_last4": DEFAULTS["SSN_LAST4"],
        "address_state": DEFAULTS["ADDRESS_STATE"],
        "email": DEFAULTS["EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_recovery_firm_payload(**overrides) -> dict:
    payload = {
        "legal_name": DEFAULTS["FIRM_NAME"],
        "registered_state": DEFAULTS["REGISTERED_STATE"],
        "license_number": DEFAULTS["LICENSE_NUMBER"],
        "max_fee_pct": DEFAULTS["MAX_FEE_PCT"],
    }
    payload.update(overrides)
    return payload


def create_property_payload(holder_id, property_type_id, **overrides) -> dict:
    payload = {
        "holder_id": holder_id,
        "property_type_id": property_type_id,
        "owner_name": DEFAULTS["OWNER_NAME"],
        "owner_last_known_state": DEFAULTS["STATE_CODE"],
        "amount_cents": DEFAULTS["AMOUNT_CENTS"],
        "last_activity_date": DEFAULTS["LAST_ACTIVITY_DATE"],
    }
    payload.update(overrides)
    return payload


def create_report_payload(holder_id, report_state=DEFAULTS["STATE_CODE"],
                          report_period_year=DEFAULTS["REPORT_YEAR"], **overrides) -> dict:
    payload = {
        "holder_id": holder_id,
        "report_state": report_state,
        "report_period_year": report_period_year,
    }
    payload.update(overrides)
    return payload


def add_property_payload(property_id, expected_report_version, **overrides) -> dict:
    payload = {
        "property_id": property_id,
        "expected_report_version": expected_report_version,
    }
    payload.update(overrides)
    return payload


def notice_payload(method="MAIL", **overrides) -> dict:
    payload = {"method": method}
    payload.update(overrides)
    return payload


def create_claim_payload(property_id, claimant_owner_id, filed_by, **overrides) -> dict:
    payload = {
        "property_id": property_id,
        "claimant_owner_id": claimant_owner_id,
        "filed_by": filed_by,
    }
    payload.update(overrides)
    return payload


def evidence_payload(doc_type="GOV_ID", **overrides) -> dict:
    payload = {"doc_type": doc_type}
    payload.update(overrides)
    return payload


def review_payload(decision, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_audit_case_payload(holder_id, **overrides) -> dict:
    payload = {"holder_id": holder_id}
    payload.update(overrides)
    return payload


def close_assess_payload(assessed_penalty_cents, findings, **overrides) -> dict:
    payload = {
        "assessed_penalty_cents": assessed_penalty_cents,
        "findings": findings,
    }
    payload.update(overrides)
    return payload
