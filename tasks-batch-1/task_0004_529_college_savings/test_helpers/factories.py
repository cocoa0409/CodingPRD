"""Payload factories — one per entity, input fields only."""
from typing import Any, Dict, Optional


def create_donor_payload(
    full_name: str = "Test Donor",
    state_code: str = "CA",
    federal_tax_id_last4: str = "1111",
    email: str = "donor@x.com",
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "full_name": full_name,
        "state_code": state_code,
        "federal_tax_id_last4": federal_tax_id_last4,
        "email": email,
    }
    payload.update(overrides)
    return payload


def create_beneficiary_payload(
    full_name: str = "Test Beneficiary",
    date_of_birth: str = "2008-06-01",
    relationship_class: str = "CHILD",
    federal_tax_id_last4: str = "2222",
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "full_name": full_name,
        "date_of_birth": date_of_birth,
        "relationship_class": relationship_class,
        "federal_tax_id_last4": federal_tax_id_last4,
    }
    payload.update(overrides)
    return payload


def create_account_payload(donor_id: str, beneficiary_id: str, **overrides) -> Dict[str, Any]:
    payload = {"donor_id": donor_id, "beneficiary_id": beneficiary_id}
    payload.update(overrides)
    return payload


def create_scheduled_contribution_payload(
    account_id: str,
    amount_cents: int = 50_000,
    cadence: str = "MONTHLY",
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "account_id": account_id,
        "amount_cents": amount_cents,
        "cadence": cadence,
    }
    payload.update(overrides)
    return payload


def create_contribution_payload(
    account_id: str,
    amount_cents: int = 100_000,
    contribution_kind: str = "LUMP_SUM",
    scheduled_contribution_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "account_id": account_id,
        "amount_cents": amount_cents,
        "contribution_kind": contribution_kind,
    }
    if scheduled_contribution_id is not None:
        payload["scheduled_contribution_id"] = scheduled_contribution_id
    payload.update(overrides)
    return payload


def create_withdrawal_payload(
    account_id: str,
    amount_cents: int = 50_000,
    expense_class: str = "HIGHER_ED_TUITION",
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "account_id": account_id,
        "amount_cents": amount_cents,
        "expense_class": expense_class,
    }
    payload.update(overrides)
    return payload


def create_beneficiary_change_payload(
    account_id: str, to_beneficiary_id: str, **overrides
) -> Dict[str, Any]:
    payload = {"account_id": account_id, "to_beneficiary_id": to_beneficiary_id}
    payload.update(overrides)
    return payload


def create_state_tax_incentive_payload(donor_id: str, tax_year: int, **overrides) -> Dict[str, Any]:
    payload = {"donor_id": donor_id, "tax_year": tax_year}
    payload.update(overrides)
    return payload


def create_form_1099q_payload(
    account_id: str, tax_year: int, supersedes_form_id: Optional[str] = None, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"account_id": account_id, "tax_year": tax_year}
    if supersedes_form_id is not None:
        payload["supersedes_form_id"] = supersedes_form_id
    payload.update(overrides)
    return payload


def approve_withdrawal_payload(expected_account_version: int) -> Dict[str, Any]:
    return {"expected_account_version": expected_account_version}


def approve_beneficiary_change_payload(expected_account_version: int) -> Dict[str, Any]:
    return {"expected_account_version": expected_account_version}
