"""Request payload builders.

Each builder mirrors one endpoint's declared input list, omitting optional
fields unless the caller supplies them so the server applies its own declared
defaults.
"""

from typing import Optional

from .constants import (
    ENGINEER_USER_ID,
    POS_SECTION_MIN_WORD_COUNT,
    SPONSOR_USER_ID,
)
from .types import JsonDict


def project_payload(
    building_address: str,
    year_built: int,
    total_unit_count: int,
    sponsor_user_id: str = SPONSOR_USER_ID,
    max_overlapping_remediations: Optional[int] = None,
) -> JsonDict:
    payload = {
        "building_address": building_address,
        "year_built": year_built,
        "total_unit_count": total_unit_count,
        "sponsor_user_id": sponsor_user_id,
    }
    if max_overlapping_remediations is not None:
        payload["max_overlapping_remediations"] = max_overlapping_remediations
    return payload


def report_payload(
    report_label: str = "ER-1",
    inspection_date: str = "2026-07-10T00:00:00Z",
    submitted_by_user_id: str = ENGINEER_USER_ID,
) -> JsonDict:
    return {
        "report_label": report_label,
        "inspection_date": inspection_date,
        "submitted_by_user_id": submitted_by_user_id,
    }


def component_payload(
    component_type: str,
    remaining_useful_life_years: int,
    effective_age_years: int,
    replacement_cost_cents: int,
    funded_pct_bp: int = 0,
    condition_rating: str = "EXCELLENT",
    planned_remediation_gain_years: Optional[int] = None,
    is_life_safety: Optional[bool] = None,
    is_structural: Optional[bool] = None,
) -> JsonDict:
    payload = {
        "component_type": component_type,
        "remaining_useful_life_years": remaining_useful_life_years,
        "effective_age_years": effective_age_years,
        "replacement_cost_cents": replacement_cost_cents,
        "funded_pct_bp": funded_pct_bp,
        "condition_rating": condition_rating,
    }
    if planned_remediation_gain_years is not None:
        payload["planned_remediation_gain_years"] = planned_remediation_gain_years
    if is_life_safety is not None:
        payload["is_life_safety"] = is_life_safety
    if is_structural is not None:
        payload["is_structural"] = is_structural
    return payload


def assessment_payload(variant: str, expected_engineering_report_version: int) -> JsonDict:
    return {
        "variant": variant,
        "expected_engineering_report_version": expected_engineering_report_version,
    }


def package_payload(
    declaration_text_ref: str = "decl/ref-a",
    bylaws_text_ref: str = "bylaws/ref-a",
    boundary_convention: str = "CENTERLINE",
) -> JsonDict:
    return {
        "declaration_text_ref": declaration_text_ref,
        "bylaws_text_ref": bylaws_text_ref,
        "boundary_convention": boundary_convention,
    }


def unit_payload(
    unit_number: str,
    base_percentage_interest_bp: int,
    floor_level: int = 1,
    heated_square_feet: int = 900,
    boundary_note: str = "as platted",
) -> JsonDict:
    return {
        "unit_number": unit_number,
        "floor_level": floor_level,
        "heated_square_feet": heated_square_feet,
        "boundary_note": boundary_note,
        "base_percentage_interest_bp": base_percentage_interest_bp,
    }


def pos_payload(
    declaration_package_id: str, reserve_study_id: str, initial_budget_id: str
) -> JsonDict:
    return {
        "declaration_package_id": declaration_package_id,
        "reserve_study_id": reserve_study_id,
        "initial_budget_id": initial_budget_id,
    }


def section_payload(
    body_ref: str,
    word_count: int = POS_SECTION_MIN_WORD_COUNT,
    attested_by_user_id: Optional[str] = None,
) -> JsonDict:
    payload = {"body_ref": body_ref, "word_count": word_count}
    if attested_by_user_id is not None:
        payload["attested_by_user_id"] = attested_by_user_id
    return payload


def amendment_payload(material_change: bool, amendment_summary: str) -> JsonDict:
    return {"material_change": material_change, "amendment_summary": amendment_summary}


def household_payload(
    household_label: str,
    tenancy_start_date: str,
    monthly_rent_cents: int,
    protected_class: Optional[str] = None,
    occupied_unit_id: Optional[str] = None,
) -> JsonDict:
    payload = {
        "household_label": household_label,
        "tenancy_start_date": tenancy_start_date,
        "monthly_rent_cents": monthly_rent_cents,
    }
    if protected_class is not None:
        payload["protected_class"] = protected_class
    if occupied_unit_id is not None:
        payload["occupied_unit_id"] = occupied_unit_id
    return payload


def reserve_study_payload(
    engineering_report_id: str,
    method: str = "COMPONENT_METHOD",
    opening_reserve_balance_cents: Optional[int] = None,
) -> JsonDict:
    payload = {"engineering_report_id": engineering_report_id, "method": method}
    if opening_reserve_balance_cents is not None:
        payload["opening_reserve_balance_cents"] = opening_reserve_balance_cents
    return payload


def budget_payload(
    reserve_study_id: str,
    annual_operating_expense_cents: int,
    expected_conversion_project_version: int,
    fiscal_year_label: str = "FY2027",
) -> JsonDict:
    return {
        "reserve_study_id": reserve_study_id,
        "fiscal_year_label": fiscal_year_label,
        "annual_operating_expense_cents": annual_operating_expense_cents,
        "expected_conversion_project_version": expected_conversion_project_version,
    }


def batch_payload(
    batch_sequence_no: int,
    window_start_at: str,
    window_end_at: str,
    min_presale_threshold_pct: float = 50.00,
    min_absolute_unit_count: int = 1,
) -> JsonDict:
    return {
        "batch_sequence_no": batch_sequence_no,
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
        "min_presale_threshold_pct": min_presale_threshold_pct,
        "min_absolute_unit_count": min_absolute_unit_count,
    }


def assignment_payload(
    purchase_agreement_id: str, expected_closing_batch_version: int
) -> JsonDict:
    return {
        "purchase_agreement_id": purchase_agreement_id,
        "expected_closing_batch_version": expected_closing_batch_version,
    }


def agreement_payload(
    purchaser_name: str,
    purchaser_tax_id: str,
    purchaser_type: str,
    price_cents: int,
    deposit_cents: int,
    expected_unit_version: int,
    tenant_household_id: Optional[str] = None,
) -> JsonDict:
    payload = {
        "purchaser_name": purchaser_name,
        "purchaser_tax_id": purchaser_tax_id,
        "purchaser_type": purchaser_type,
        "price_cents": price_cents,
        "deposit_cents": deposit_cents,
        "expected_unit_version": expected_unit_version,
    }
    if tenant_household_id is not None:
        payload["tenant_household_id"] = tenant_household_id
    return payload


def claim_payload(
    major_component_id: str,
    defect_description: str,
    claimed_cost_cents: int,
    reported_by_unit_id: Optional[str] = None,
) -> JsonDict:
    payload = {
        "major_component_id": major_component_id,
        "defect_description": defect_description,
        "claimed_cost_cents": claimed_cost_cents,
    }
    if reported_by_unit_id is not None:
        payload["reported_by_unit_id"] = reported_by_unit_id
    return payload


def triage_payload(decision: str, triage_note: Optional[str] = None) -> JsonDict:
    payload = {"decision": decision}
    if triage_note is not None:
        payload["triage_note"] = triage_note
    return payload


def remediation_payload(remediation_start_at: str, remediation_end_at: str) -> JsonDict:
    return {
        "remediation_start_at": remediation_start_at,
        "remediation_end_at": remediation_end_at,
    }


def peer_review_payload(
    decision: str, reviewed_by_user_id: str, review_note: Optional[str] = None
) -> JsonDict:
    payload = {"decision": decision, "reviewed_by_user_id": reviewed_by_user_id}
    if review_note is not None:
        payload["review_note"] = review_note
    return payload


# --- component presets used repeatedly by the recipes ------------------------
def roof_standard() -> JsonDict:
    """A sound roof: 30 remaining years, EXCELLENT, 10000000 cents to replace."""
    return component_payload("ROOF", 30, 10, 10000000, 0, "EXCELLENT")


def foundation_structural() -> JsonDict:
    """A structural foundation component worth 4000000 cents."""
    return component_payload(
        "FOUNDATION", 40, 10, 4000000, 0, "EXCELLENT", is_structural=True
    )
