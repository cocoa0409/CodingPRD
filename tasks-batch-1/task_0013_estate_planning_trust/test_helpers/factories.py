"""Payload factories — one per entity, input fields only.

All factories follow the rule: only `source: input` fields are populated.
Computed fields (status, gross_estate_value_cents, etc.) and system fields
(created_at, version) are server-set.
"""


def create_decedent_payload(
    full_legal_name: str = "Test Decedent",
    date_of_birth: str = "1950-01-01T00:00:00Z",
    domicile_state_code: str = "CA",
    ssn_last4: str = "0001",
    **overrides,
) -> dict:
    payload = {
        "full_legal_name": full_legal_name,
        "date_of_birth": date_of_birth,
        "domicile_state_code": domicile_state_code,
        "ssn_last4": ssn_last4,
    }
    payload.update(overrides)
    return payload


def create_estate_payload(decedent_id: str, **overrides) -> dict:
    payload = {"decedent_id": decedent_id}
    payload.update(overrides)
    return payload


def create_asset_payload(
    estate_id: str,
    category: str = "BANK_ACCOUNT",
    description: str = "Test Asset",
    appraised_value_cents: int = 100000,
    beneficiary_designation_id: str = None,
    **overrides,
) -> dict:
    payload = {
        "estate_id": estate_id,
        "category": category,
        "description": description,
        "appraised_value_cents": appraised_value_cents,
    }
    if beneficiary_designation_id is not None:
        payload["beneficiary_designation_id"] = beneficiary_designation_id
    payload.update(overrides)
    return payload


def create_beneficiary_designation_payload(
    estate_id: str,
    beneficiary_full_name: str = "Test Beneficiary",
    relationship: str = "CHILD",
    share_basis_points: int = 10000,
    contingent_of_designation_id: str = None,
    **overrides,
) -> dict:
    payload = {
        "estate_id": estate_id,
        "beneficiary_full_name": beneficiary_full_name,
        "relationship": relationship,
        "share_basis_points": share_basis_points,
    }
    if contingent_of_designation_id is not None:
        payload["contingent_of_designation_id"] = contingent_of_designation_id
    payload.update(overrides)
    return payload


def create_executor_payload(
    estate_id: str,
    full_legal_name: str = "Test Executor",
    role_type: str = "EXECUTOR",
    is_also_beneficiary: bool = False,
    **overrides,
) -> dict:
    payload = {
        "estate_id": estate_id,
        "full_legal_name": full_legal_name,
        "role_type": role_type,
        "is_also_beneficiary": is_also_beneficiary,
    }
    payload.update(overrides)
    return payload


def create_poa_payload(
    decedent_id: str,
    agent_full_name: str = "Test Agent",
    scope: str = "FINANCIAL",
    **overrides,
) -> dict:
    payload = {
        "decedent_id": decedent_id,
        "agent_full_name": agent_full_name,
        "scope": scope,
    }
    payload.update(overrides)
    return payload


def activate_poa_payload(
    effective_at: str,
    effective_until: str = None,
    **overrides,
) -> dict:
    payload = {"effective_at": effective_at}
    if effective_until is not None:
        payload["effective_until"] = effective_until
    payload.update(overrides)
    return payload


def create_directive_payload(
    decedent_id: str,
    directive_type: str = "LIVING_WILL",
    physician_attester_user_id: str = None,
    hipaa_authorized_recipients=None,
    **overrides,
) -> dict:
    payload = {
        "decedent_id": decedent_id,
        "directive_type": directive_type,
    }
    if physician_attester_user_id is not None:
        payload["physician_attester_user_id"] = physician_attester_user_id
    if hipaa_authorized_recipients is not None:
        payload["hipaa_authorized_recipients"] = hipaa_authorized_recipients
    payload.update(overrides)
    return payload


def create_guardianship_payload(
    estate_id: str,
    ward_full_name: str = "Test Ward",
    ward_date_of_birth: str = "2015-01-01T00:00:00Z",
    guardian_full_name: str = "Test Guardian",
    **overrides,
) -> dict:
    payload = {
        "estate_id": estate_id,
        "ward_full_name": ward_full_name,
        "ward_date_of_birth": ward_date_of_birth,
        "guardian_full_name": guardian_full_name,
    }
    payload.update(overrides)
    return payload


def create_creditor_claim_payload(
    estate_id: str,
    creditor_name: str = "Test Creditor",
    amount_cents: int = 10000,
    claim_class: str = "UNSECURED",
    filed_at: str = "2026-02-01T00:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "estate_id": estate_id,
        "creditor_name": creditor_name,
        "amount_cents": amount_cents,
        "claim_class": claim_class,
        "filed_at": filed_at,
    }
    payload.update(overrides)
    return payload


def create_probate_order_payload(
    estate_id: str,
    order_type: str,
    judge_user_id: str = "test-judge-1",
    **overrides,
) -> dict:
    payload = {
        "estate_id": estate_id,
        "order_type": order_type,
        "judge_user_id": judge_user_id,
    }
    payload.update(overrides)
    return payload
