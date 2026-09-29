"""Payload factories — one per entity, carrying only client-supplied fields."""

from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS
from .types import (
    ActionType,
    AssuranceBasis,
    AssuranceLevel,
    CompensationType,
    DocType,
    ExtensionBasis,
    FundraiserType,
    MaterialType,
    OfficerTitle,
    RegistrationType,
    RenewalDueRule,
    SolicitationChannel,
)


def state_profile_payload(state_code: str = "CA", **overrides) -> Dict[str, Any]:
    """Only the six required fields are supplied unless a test overrides more."""
    payload: Dict[str, Any] = {
        "state_code": state_code,
        "registration_required": True,
        "renewal_due_rule": RenewalDueRule.FYE_PLUS_4M_15D.value,
        "assurance_basis": AssuranceBasis.CONTRIBUTIONS_ONLY.value,
        "review_threshold_cents": 20_000_000,
        "audit_threshold_cents": 200_000_000,
    }
    payload.update(overrides)
    return payload


def california_profile_payload(**overrides) -> Dict[str, Any]:
    """The fully-parameterised jurisdiction most filing scenarios are built on."""
    payload: Dict[str, Any] = {
        "state_code": "CA",
        "registration_required": True,
        "renewal_due_rule": RenewalDueRule.FYE_PLUS_4M_15D.value,
        "assurance_basis": AssuranceBasis.GROSS_REVENUE.value,
        "review_threshold_cents": 20_000_000,
        "audit_threshold_cents": 200_000_000,
        "donor_count_trigger": 25,
        "contribution_trigger_cents": 2_500_000,
        "online_presence_counts": True,
        "extension_allowed": True,
        "extension_max_days": 90,
        "disclosure_required_clauses": [],
        "fundraiser_contract_filing_days": 10,
        "fundraiser_bond_minimum_cents": 2_500_000,
        "coventure_filing_required": True,
        "coventure_buffer_days": 7,
        "base_filing_fee_cents": 2_500,
        "online_surcharge_cents": 1_000,
        "per_contract_fee_cents": 1_500,
        "filing_fee_cap_cents": 30_000,
        "late_fee_base_cents": 2_004,
        "late_fee_escalation_pct": 0.125,
        "late_fee_cap_cents": 50_000,
        "cure_period_days": 30,
        "reinstatement_fee_cents": 12_500,
    }
    payload.update(overrides)
    return payload


def organization_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "legal_name": TEST_DEFAULTS["ORGANIZATION_LEGAL_NAME"],
        "ein": TEST_DEFAULTS["ORGANIZATION_EIN"],
        "domicile_state_code": "CA",
        "fiscal_year_end_month": TEST_DEFAULTS["FISCAL_YEAR_END_MONTH"],
        "has_online_donation_page": True,
    }
    payload.update(overrides)
    return payload


def solicitation_activity_payload(
    organization_id: str, state_code: str = "CA", **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "organization_id": organization_id,
        "state_code": state_code,
        "fiscal_year": TEST_DEFAULTS["FISCAL_YEAR"],
        "donor_count": 25,
        "contributions_cents": 2_500_000,
        "channels": [SolicitationChannel.MAIL.value],
    }
    payload.update(overrides)
    return payload


def financial_statement_payload(
    organization_id: str, expected_organization_version: int, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "organization_id": organization_id,
        "fiscal_year": TEST_DEFAULTS["FISCAL_YEAR"],
        "total_revenue_cents": TEST_DEFAULTS["TOTAL_REVENUE_CENTS"],
        "contributions_cents": TEST_DEFAULTS["CONTRIBUTIONS_CENTS"],
        "program_expense_cents": TEST_DEFAULTS["PROGRAM_EXPENSE_CENTS"],
        "fundraising_expense_cents": TEST_DEFAULTS["FUNDRAISING_EXPENSE_CENTS"],
        "management_expense_cents": TEST_DEFAULTS["MANAGEMENT_EXPENSE_CENTS"],
        "assurance_level": AssuranceLevel.REVIEW.value,
        "expected_organization_version": expected_organization_version,
    }
    payload.update(overrides)
    return payload


def officer_disclosure_payload(
    organization_id: str,
    officer_name: str = "Dana Reyes",
    title: str = OfficerTitle.PRESIDENT.value,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "organization_id": organization_id,
        "officer_name": officer_name,
        "title": title,
    }
    payload.update(overrides)
    return payload


def state_registration_payload(
    organization_id: str,
    financial_statement_id: str,
    state_code: str = "CA",
    registration_type: str = RegistrationType.INITIAL.value,
    coverage_start: str = "2025-07-01T00:00:00Z",
    coverage_end: str = "2026-07-01T00:00:00Z",
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "organization_id": organization_id,
        "state_code": state_code,
        "registration_type": registration_type,
        "fiscal_year": TEST_DEFAULTS["FISCAL_YEAR"],
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "financial_statement_id": financial_statement_id,
    }
    payload.update(overrides)
    return payload


def registration_document_payload(
    registration_id: str,
    prepared_by_officer_id: str,
    doc_type: str = DocType.GOVERNING_DOCUMENT.value,
    page_count: int = 12,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "registration_id": registration_id,
        "doc_type": doc_type,
        "prepared_by_officer_id": prepared_by_officer_id,
        "page_count": page_count,
    }
    payload.update(overrides)
    return payload


def extension_request_payload(
    registration_id: str,
    expected_registration_version: int,
    basis: str = ExtensionBasis.IRS_990_EXTENSION.value,
    requested_days: int = 5,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "registration_id": registration_id,
        "basis": basis,
        "requested_days": requested_days,
        "expected_registration_version": expected_registration_version,
    }
    payload.update(overrides)
    return payload


def professional_fundraiser_payload(
    legal_name: str = "Beacon Solicitations LLC",
    fundraiser_type: str = FundraiserType.PROFESSIONAL_SOLICITOR.value,
    bond_expires_at: str = "2028-01-01T00:00:00Z",
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "legal_name": legal_name,
        "fundraiser_type": fundraiser_type,
        "bond_amount_cents": 5_000_000,
        "bond_expires_at": bond_expires_at,
    }
    payload.update(overrides)
    return payload


def fundraiser_registration_payload(
    fundraiser_id: str,
    state_code: str = "CA",
    bond_on_file_cents: int = 2_500_000,
    expires_at: str = "2027-01-01T00:00:00Z",
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "fundraiser_id": fundraiser_id,
        "state_code": state_code,
        "bond_on_file_cents": bond_on_file_cents,
        "expires_at": expires_at,
    }
    payload.update(overrides)
    return payload


def fundraising_contract_payload(
    organization_id: str,
    fundraiser_id: str,
    state_codes: Optional[List[str]] = None,
    contract_start: str = "2026-08-01T00:00:00Z",
    contract_end: str = "2026-12-31T00:00:00Z",
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "organization_id": organization_id,
        "fundraiser_id": fundraiser_id,
        "state_codes": list(state_codes) if state_codes else ["CA"],
        "contract_start": contract_start,
        "contract_end": contract_end,
        "compensation_type": CompensationType.FLAT_FEE.value,
        "flat_fee_cents": 500_000,
    }
    payload.update(overrides)
    return payload


def coventure_promotion_payload(
    organization_id: str,
    coventurer_id: str,
    state_codes: Optional[List[str]] = None,
    promo_start: str = "2026-09-01T00:00:00Z",
    promo_end: str = "2026-09-30T00:00:00Z",
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "organization_id": organization_id,
        "coventurer_id": coventurer_id,
        "state_codes": list(state_codes) if state_codes else ["CA"],
        "promo_start": promo_start,
        "promo_end": promo_end,
        "guaranteed_minimum_cents": 500_000,
        "per_unit_cents": 250,
        "projected_units": 3_000,
    }
    payload.update(overrides)
    return payload


def disclosure_statement_payload(
    organization_id: str,
    state_code: str = "CA",
    material_type: str = MaterialType.WEB.value,
    included_clauses: Optional[List[str]] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "organization_id": organization_id,
        "state_code": state_code,
        "material_type": material_type,
        "included_clauses": list(included_clauses) if included_clauses else [],
    }
    payload.update(overrides)
    return payload


def enforcement_action_payload(
    organization_id: str,
    registration_id: str,
    action_type: str = ActionType.PENALTY_ASSESSMENT.value,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "organization_id": organization_id,
        "registration_id": registration_id,
        "action_type": action_type,
    }
    payload.update(overrides)
    return payload
