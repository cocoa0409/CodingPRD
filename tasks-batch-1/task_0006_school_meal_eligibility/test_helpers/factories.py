"""Payload factories — one per entity, input fields only.

Defaults are sane minimal payloads; tests pass keyword overrides for fields
they need to control.
"""
import uuid


def _unique_suffix() -> str:
    return uuid.uuid4().hex[:8]


def create_household_payload(**overrides) -> dict:
    suffix = _unique_suffix()
    defaults = {
        "primary_parent_name": f"Parent {suffix}",
        "family_size": 4,
        "annual_income_cents": 4_500_000,   # $45,000/yr default
        "address_state": "CA",
        "direct_certification_flag": False,
    }
    defaults.update(overrides)
    return defaults


def create_student_payload(household_id: str, **overrides) -> dict:
    suffix = _unique_suffix()
    defaults = {
        "household_id": household_id,
        "full_name": f"Student {suffix}",
        "school_code": "ELEM-101",
        "grade_level": 3,
    }
    defaults.update(overrides)
    return defaults


def create_allergy_profile_payload(student_id: str, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
    }
    defaults.update(overrides)
    return defaults


def create_meal_application_payload(household_id: str, **overrides) -> dict:
    defaults = {
        "household_id": household_id,
        "school_year": "2025-2026",
    }
    defaults.update(overrides)
    return defaults


def create_eligibility_determination_payload(
    household_id: str,
    source: str = "DIRECT_CERTIFICATION",
    tier: str = "FREE",
    valid_from_utc: str = "2026-01-01T00:00:00.000Z",
    valid_to_utc: str = "2026-08-31T23:59:59.000Z",
    **overrides,
) -> dict:
    defaults = {
        "household_id": household_id,
        "source": source,
        "tier": tier,
        "valid_from_utc": valid_from_utc,
        "valid_to_utc": valid_to_utc,
    }
    defaults.update(overrides)
    return defaults


def create_menu_item_payload(**overrides) -> dict:
    suffix = _unique_suffix()
    defaults = {
        "school_code": "ELEM-101",
        "name": f"Item {suffix}",
        "list_price_cents": 300,
        "federal_reimbursement_free_cents": 470,
        "federal_reimbursement_reduced_cents": 430,
        "federal_reimbursement_paid_cents": 70,
        "allergens_present": [],
        "calories": 300,
    }
    defaults.update(overrides)
    return defaults


def create_topup_payload(amount_cents: int, idempotency_key: str = None, **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
        "idempotency_key": idempotency_key if idempotency_key is not None
                           else f"key-{_unique_suffix()}",
    }
    defaults.update(overrides)
    return defaults


def create_service_transaction_payload(student_id: str, menu_item_id: str, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "menu_item_id": menu_item_id,
    }
    defaults.update(overrides)
    return defaults


def create_reimbursement_claim_payload(
    school_code: str,
    period_start_utc: str,
    period_end_utc: str,
    accounting_basis: str = "CASH",
    **overrides,
) -> dict:
    defaults = {
        "school_code": school_code,
        "period_start_utc": period_start_utc,
        "period_end_utc": period_end_utc,
        "accounting_basis": accounting_basis,
    }
    defaults.update(overrides)
    return defaults


def create_approve_payload(decision_reason: str = "verified") -> dict:
    return {"decision_reason": decision_reason}


def create_deny_payload(decision_reason: str = "denied") -> dict:
    return {"decision_reason": decision_reason}


def create_appeal_payload(appeal_reason: str, expected_mealapplication_version: int) -> dict:
    return {
        "appeal_reason": appeal_reason,
        "expected_mealapplication_version": expected_mealapplication_version,
    }


def create_reject_tx_payload(rejection_reason: str = "MANUAL") -> dict:
    return {"rejection_reason": rejection_reason}


def create_refund_tx_payload(expected_servicetransaction_version: int) -> dict:
    return {"expected_servicetransaction_version": expected_servicetransaction_version}


def create_resolve_dispute_payload(resolution: str) -> dict:
    return {"resolution": resolution}


def create_revoke_determination_payload(expected_eligibilitydetermination_version: int) -> dict:
    return {
        "expected_eligibilitydetermination_version": expected_eligibilitydetermination_version,
    }


def create_reject_claim_payload(rejection_reason: str = "audit failure") -> dict:
    return {"rejection_reason": rejection_reason}
