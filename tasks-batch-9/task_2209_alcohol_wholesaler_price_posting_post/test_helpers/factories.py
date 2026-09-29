"""Payload factories — one per entity, carrying only client-supplied input fields."""

from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


def set_clock_payload(to_iso8601: str) -> Dict[str, Any]:
    return {"to_iso8601": to_iso8601}


def create_state_program_payload(**overrides: Any) -> Dict[str, Any]:
    """Only `state_code` and `program_name` are required; everything else defaults."""
    payload: Dict[str, Any] = {
        "state_code": TEST_DEFAULTS["STATE_CODE"],
        "program_name": TEST_DEFAULTS["PROGRAM_NAME"],
    }
    payload.update(overrides)
    return payload


def create_wholesaler_payload(state_program_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "license_number": TEST_DEFAULTS["LICENSE_NUMBER_A"],
        "legal_name": TEST_DEFAULTS["LEGAL_NAME_A"],
        "state_program_id": state_program_id,
    }
    payload.update(overrides)
    return payload


def set_license_status_payload(license_status: str) -> Dict[str, Any]:
    return {"license_status": license_status}


def create_licensee_user_payload(
    wholesaler_id: str, user_role: str = "FILING_AGENT", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "wholesaler_id": wholesaler_id,
        "full_name": TEST_DEFAULTS["FILING_AGENT_NAME"],
        "user_role": user_role,
    }
    payload.update(overrides)
    return payload


def create_brand_payload(wholesaler_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "wholesaler_id": wholesaler_id,
        "brand_name": TEST_DEFAULTS["BRAND_NAME"],
        "supplier_name": TEST_DEFAULTS["SUPPLIER_NAME"],
        "beverage_class": TEST_DEFAULTS["BEVERAGE_CLASS"],
        "registration_effective_from": TEST_DEFAULTS["REGISTRATION_EFFECTIVE_FROM"],
        "registration_expires_on": TEST_DEFAULTS["REGISTRATION_EXPIRES_ON"],
    }
    payload.update(overrides)
    return payload


def reject_brand_payload(rejection_reason: str = "Supplier appointment letter missing.") -> Dict[str, Any]:
    return {"rejection_reason": rejection_reason}


def create_price_schedule_payload(
    wholesaler_id: str, state_program_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "wholesaler_id": wholesaler_id,
        "state_program_id": state_program_id,
        "posting_month": TEST_DEFAULTS["POSTING_MONTH"],
    }
    payload.update(overrides)
    return payload


def return_for_correction_payload(
    return_reason: str = "Package configuration does not match the supplier appointment.",
) -> Dict[str, Any]:
    return {"return_reason": return_reason}


def create_price_schedule_item_payload(
    schedule_id: str, brand_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "schedule_id": schedule_id,
        "brand_id": brand_id,
        "size_ml": TEST_DEFAULTS["SIZE_ML"],
        "bottles_per_case": TEST_DEFAULTS["BOTTLES_PER_CASE"],
        "case_price_cents": TEST_DEFAULTS["CASE_PRICE_CENTS"],
        "unit_price_cents": TEST_DEFAULTS["UNIT_PRICE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_quantity_discount_tier_payload(
    item_id: str, min_cases: int = 5, discount_pct: float = 0.10, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "item_id": item_id,
        "min_cases": min_cases,
        "discount_pct": discount_pct,
    }
    payload.update(overrides)
    return payload


def create_combination_sale_payload(
    schedule_id: str,
    member_item_ids: List[str],
    combined_case_price_cents: int,
    promo_starts_at: str = "2026-10-01T00:00:00Z",
    promo_ends_at: str = "2026-10-10T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "schedule_id": schedule_id,
        "member_item_ids": list(member_item_ids),
        "promo_starts_at": promo_starts_at,
        "promo_ends_at": promo_ends_at,
        "combined_case_price_cents": combined_case_price_cents,
    }
    payload.update(overrides)
    return payload


def create_hold_amendment_payload(
    amending_item_id: str,
    reference_item_id: str,
    new_case_price_cents: int,
    new_unit_price_cents: int,
    expected_schedule_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "amending_item_id": amending_item_id,
        "reference_item_id": reference_item_id,
        "new_case_price_cents": new_case_price_cents,
        "new_unit_price_cents": new_unit_price_cents,
        "expected_schedule_version": expected_schedule_version,
    }
    payload.update(overrides)
    return payload


def reject_hold_amendment_payload(
    rejection_reason: str = "The matched posting is not comparable.",
) -> Dict[str, Any]:
    return {"rejection_reason": rejection_reason}


def revoke_hold_amendment_payload(
    revocation_reason: str = "The matched competitor posting was itself withdrawn.",
) -> Dict[str, Any]:
    return {"revocation_reason": revocation_reason}


def create_error_correction_payload(
    item_id: str,
    corrected_case_price_cents: int,
    corrected_unit_price_cents: int,
    reason: str = "Case price keyed from the wrong supplier quote sheet.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "item_id": item_id,
        "corrected_case_price_cents": corrected_case_price_cents,
        "corrected_unit_price_cents": corrected_unit_price_cents,
        "reason": reason,
    }
    payload.update(overrides)
    return payload


def deny_error_correction_payload(
    denial_reason: str = "No supporting quote sheet supplied.",
) -> Dict[str, Any]:
    return {"denial_reason": denial_reason}


def create_retailer_invoice_payload(
    wholesaler_id: str, invoice_date: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "wholesaler_id": wholesaler_id,
        "retailer_license_number": TEST_DEFAULTS["RETAILER_LICENSE_NUMBER"],
        "invoice_date": invoice_date,
    }
    payload.update(overrides)
    return payload


def create_invoice_line_payload(
    invoice_id: str,
    item_id: str,
    case_price_charged_cents: int,
    unit_price_charged_cents: int,
    cases_quantity: Optional[int] = None,
    bottles_quantity: Optional[int] = None,
    promotional_allowance_cents: Optional[int] = None,
    depletion_allowance_cents: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Quantities and allowances are optional on input and default to 0 server-side."""
    payload: Dict[str, Any] = {
        "invoice_id": invoice_id,
        "item_id": item_id,
        "case_price_charged_cents": case_price_charged_cents,
        "unit_price_charged_cents": unit_price_charged_cents,
    }
    if cases_quantity is not None:
        payload["cases_quantity"] = cases_quantity
    if bottles_quantity is not None:
        payload["bottles_quantity"] = bottles_quantity
    if promotional_allowance_cents is not None:
        payload["promotional_allowance_cents"] = promotional_allowance_cents
    if depletion_allowance_cents is not None:
        payload["depletion_allowance_cents"] = depletion_allowance_cents
    payload.update(overrides)
    return payload


def create_compliance_audit_payload(
    wholesaler_id: str,
    state_program_id: str,
    audit_period_month: str,
    expected_wholesaler_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "wholesaler_id": wholesaler_id,
        "state_program_id": state_program_id,
        "audit_period_month": audit_period_month,
        "expected_wholesaler_version": expected_wholesaler_version,
    }
    payload.update(overrides)
    return payload


def void_compliance_audit_payload(
    void_reason: str = "The collected invoices were superseded by a corrected filing.",
) -> Dict[str, Any]:
    return {"void_reason": void_reason}


def create_posting_run_payload(state_program_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"state_program_id": state_program_id}
    payload.update(overrides)
    return payload
