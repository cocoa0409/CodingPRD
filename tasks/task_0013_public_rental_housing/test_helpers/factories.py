"""Payload factories for the Public Rental Housing API.

One factory per entity. Only fields the PRD describes as input are emitted; computed and
system-managed fields (id, status, created_at, updated_at, version, applicant_user_id,
queue_score, etc.) are NOT included in factory output — they are server-derived.

All factories accept arbitrary `**overrides` so tests can pin specific values for
boundary or branch coverage.
"""

import uuid as _uuid
from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


# ──────────────────────────────────────────────────────────
# HousingProgram
# ──────────────────────────────────────────────────────────


def create_program_payload(
    name: Optional[str] = None,
    description: Optional[str] = None,
    notice_period_length: int = TEST_DEFAULTS["NOTICE_PERIOD_LENGTH"],
    grace_period_length: int = TEST_DEFAULTS["GRACE_PERIOD_LENGTH"],
    per_capita_income_threshold_cents: int = TEST_DEFAULTS["PER_CAPITA_INCOME_THRESHOLD_CENTS"],
    per_capita_asset_threshold_cents: int = TEST_DEFAULTS["PER_CAPITA_ASSET_THRESHOLD_CENTS"],
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name or f"Test Program {_uuid.uuid4().hex[:8]}",
        "notice_period_length": notice_period_length,
        "grace_period_length": grace_period_length,
        "per_capita_income_threshold_cents": per_capita_income_threshold_cents,
        "per_capita_asset_threshold_cents": per_capita_asset_threshold_cents,
    }
    if description is not None:
        payload["description"] = description
    payload.update(overrides)
    return payload


# ──────────────────────────────────────────────────────────
# Application
# ──────────────────────────────────────────────────────────


def make_household_member(
    citizen_id: Optional[str] = None,
    relation: str = "SELF",
    dob: str = "1985-01-01",
    has_disability: bool = False,
    special_care_category: str = "NONE",
) -> Dict[str, Any]:
    return {
        "citizen_id": citizen_id or f"CIT-{_uuid.uuid4().hex[:8]}",
        "relation": relation,
        "dob": dob,
        "has_disability": has_disability,
        "special_care_category": special_care_category,
    }


def create_application_payload(
    household_members: Optional[List[Dict[str, Any]]] = None,
    household_type: str = "LOW_INCOME",
    declared_monthly_income_cents: int = TEST_DEFAULTS["DECLARED_MONTHLY_INCOME_CENTS"],
    declared_total_assets_cents: int = TEST_DEFAULTS["DECLARED_TOTAL_ASSETS_CENTS"],
    residence_start_period: int = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    if household_members is None:
        household_members = [make_household_member()]
    payload: Dict[str, Any] = {
        "household_members": household_members,
        "household_type": household_type,
        "declared_monthly_income_cents": declared_monthly_income_cents,
        "declared_total_assets_cents": declared_total_assets_cents,
        "residence_start_period": residence_start_period,
    }
    payload.update(overrides)
    return payload


# ──────────────────────────────────────────────────────────
# HousingUnit
# ──────────────────────────────────────────────────────────

_APARTMENT_BEDROOMS = {
    "STUDIO": 0,
    "ONE_BEDROOM": 1,
    "TWO_BEDROOM": 2,
    "THREE_BEDROOM": 3,
}


def create_housing_unit_payload(
    unit_code: Optional[str] = None,
    apartment_type: str = "ONE_BEDROOM",
    bedroom_count: Optional[int] = None,
    square_meters: int = 50,
    monthly_base_rent_cents: int = TEST_DEFAULTS["MONTHLY_BASE_RENT_CENTS"],
    location_priority_tier: int = 3,
    accessibility_compliant: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    if bedroom_count is None:
        bedroom_count = _APARTMENT_BEDROOMS.get(apartment_type, 1)
    payload: Dict[str, Any] = {
        "unit_code": unit_code or f"UNIT-{_uuid.uuid4().hex[:8].upper()}",
        "apartment_type": apartment_type,
        "bedroom_count": bedroom_count,
        "square_meters": square_meters,
        "monthly_base_rent_cents": monthly_base_rent_cents,
        "location_priority_tier": location_priority_tier,
        "accessibility_compliant": accessibility_compliant,
    }
    payload.update(overrides)
    return payload


# ──────────────────────────────────────────────────────────
# Allocation / Objection / Contract
# ──────────────────────────────────────────────────────────


def create_allocation_payload(housing_unit_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"housing_unit_id": housing_unit_id}
    payload.update(overrides)
    return payload


def create_objection_payload(
    reason_text: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        # PRD §3.4: reason_text must be at least 20 characters.
        "reason_text": reason_text
        or "Submitted objection regarding allocation match for this housing unit.",
    }
    payload.update(overrides)
    return payload


def create_sign_payload(
    lease_start_period: int,
    lease_end_period: int,
    signature_blob: str = "SIGNATURE-BLOB-DATA",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "signature_blob": signature_blob,
        "lease_start_period": lease_start_period,
        "lease_end_period": lease_end_period,
    }
    payload.update(overrides)
    return payload


# ──────────────────────────────────────────────────────────
# RentReduction / AnnualReview
# ──────────────────────────────────────────────────────────


def create_rent_reduction_payload(
    hardship_category: str = "UNEMPLOYMENT",
    declared_hardship_income_cents: int = 10_000,
    supporting_documents: Optional[List[Dict[str, Any]]] = None,
    requested_discount_bps: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    if supporting_documents is None:
        supporting_documents = [
            {
                "doc_type": "unemployment_letter",
                "doc_ref": f"DOC-{_uuid.uuid4().hex[:8]}",
                "issued_period": 0,
            }
        ]
    payload: Dict[str, Any] = {
        "hardship_category": hardship_category,
        "declared_hardship_income_cents": declared_hardship_income_cents,
        "supporting_documents": supporting_documents,
    }
    if requested_discount_bps is not None:
        payload["requested_discount_bps"] = requested_discount_bps
    payload.update(overrides)
    return payload


def create_annual_review_payload(
    updated_household_members: Optional[List[Dict[str, Any]]] = None,
    updated_declared_monthly_income_cents: Optional[int] = None,
    updated_declared_total_assets_cents: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if updated_household_members is not None:
        payload["updated_household_members"] = updated_household_members
    if updated_declared_monthly_income_cents is not None:
        payload["updated_declared_monthly_income_cents"] = updated_declared_monthly_income_cents
    if updated_declared_total_assets_cents is not None:
        payload["updated_declared_total_assets_cents"] = updated_declared_total_assets_cents
    payload.update(overrides)
    return payload


# ──────────────────────────────────────────────────────────
# SyncEvent factories — one per event_type the PRD describes.
# Per PRD §2.6 the integration gateway emits these to drive cross-check, deposit
# verification, and audit logs.
# ──────────────────────────────────────────────────────────


def create_sync_event_payload(
    event_type: str,
    subject_type: str,
    subject_id: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "event_type": event_type,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "payload": payload,
    }


def civil_affairs_household_payload(citizen_ids: List[str]) -> Dict[str, Any]:
    """Payload for CIVIL_AFFAIRS_HOUSEHOLD: lists every citizen_id present in the household
    register. Cross-check requires every Application household_member.citizen_id appear here.
    """
    return {"citizen_ids": list(citizen_ids)}


def public_security_identity_payload(
    citizen_records: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Payload for PUBLIC_SECURITY_IDENTITY: each record is
    {citizen_id, identity_verified}. Cross-check requires every household_member's
    citizen_id resolve to identity_verified=true.
    """
    return {"citizen_records": list(citizen_records)}


def tax_income_assets_payload(
    monthly_income_cents: int, total_assets_cents: int
) -> Dict[str, Any]:
    """PRD §2.6: TAX_INCOME_ASSETS payload contains monthly_income_cents and
    total_assets_cents. Used for per-capita threshold checks at cross-check, and as the
    verified income source for the final rent-reduction discount tier.
    """
    return {
        "monthly_income_cents": monthly_income_cents,
        "total_assets_cents": total_assets_cents,
    }


def payment_deposit_payload(amount_cents: int) -> Dict[str, Any]:
    """PRD §2.6: PAYMENT_DEPOSIT payload contains amount_cents. The pay-deposit
    precondition compares this to contract.deposit_amount_cents.
    """
    return {"amount_cents": amount_cents}
