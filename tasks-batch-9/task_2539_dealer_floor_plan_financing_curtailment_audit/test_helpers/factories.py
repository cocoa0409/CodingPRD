"""Payload factories — one per entity, client-supplied input fields only."""
from typing import Any, Dict

from .constants import TEST_DEFAULTS


def create_dealer_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "legal_name": "Test Floorplan Motors LLC",
        "franchise_type": "FRANCHISE_NEW_CAR",
        "state_code": "TX",
    }
    payload.update(overrides)
    return payload


def create_credit_line_payload(dealer_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "dealer_id": dealer_id,
        "credit_limit_cents": TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
        "advance_rate_bps_new": TEST_DEFAULTS["ADVANCE_RATE_BPS_NEW"],
        "advance_rate_bps_used": TEST_DEFAULTS["ADVANCE_RATE_BPS_USED"],
        "advance_rate_bps_demonstrator": TEST_DEFAULTS["ADVANCE_RATE_BPS_DEMONSTRATOR"],
        "max_unit_advance_cents_new": TEST_DEFAULTS["MAX_UNIT_ADVANCE_CENTS_NEW"],
        "max_unit_advance_cents_used": TEST_DEFAULTS["MAX_UNIT_ADVANCE_CENTS_USED"],
        "max_unit_advance_cents_demonstrator": TEST_DEFAULTS[
            "MAX_UNIT_ADVANCE_CENTS_DEMONSTRATOR"
        ],
        "class_sublimit_cents_used": TEST_DEFAULTS["CLASS_SUBLIMIT_CENTS_USED"],
        "class_sublimit_cents_demonstrator": TEST_DEFAULTS[
            "CLASS_SUBLIMIT_CENTS_DEMONSTRATOR"
        ],
        "curtailment_grace_days": TEST_DEFAULTS["CURTAILMENT_GRACE_DAYS"],
    }
    payload.update(overrides)
    return payload


def create_curtailment_tier_payload(
    inventory_class: str = "NEW",
    age_days_from: int = 90,
    age_days_to=None,
    cumulative_paydown_bps: int = 1000,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "inventory_class": inventory_class,
        "age_days_from": age_days_from,
        "age_days_to": age_days_to,
        "cumulative_paydown_bps": cumulative_paydown_bps,
    }
    payload.update(overrides)
    return payload


def create_unit_payload(
    dealer_id: str, credit_line_id: str, vin: str, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "dealer_id": dealer_id,
        "credit_line_id": credit_line_id,
        "vin": vin,
        "inventory_class": "NEW",
        "invoice_amount_cents": TEST_DEFAULTS["UNIT_INVOICE_AMOUNT_CENTS"],
        "invoice_date": "2026-08-01",
        "odometer_miles": 5,
        "title_document_type": "MSO",
    }
    payload.update(overrides)
    return payload


def title_custody_payload(new_custody_status: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"new_custody_status": new_custody_status}
    payload.update(overrides)
    return payload


def ineligibility_payload(reason_code: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"ineligibility_reason_code": reason_code}
    payload.update(overrides)
    return payload


def request_advance_payload(
    requested_amount_cents: int, dealer_invoice_reference: str, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "requested_amount_cents": requested_amount_cents,
        "dealer_invoice_reference": dealer_invoice_reference,
    }
    payload.update(overrides)
    return payload


def fund_advance_payload(
    expected_credit_line_version: int,
    disbursement_reference: str = "WIRE-TEST-0001",
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "expected_credit_line_version": expected_credit_line_version,
        "disbursement_reference": disbursement_reference,
    }
    payload.update(overrides)
    return payload


def reject_advance_payload(reason_code: str = "CREDIT_DECLINE", **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason_code": reason_code}
    payload.update(overrides)
    return payload


def reverse_advance_payload(
    expected_credit_line_version: int, reason_code: str = "FUNDING_ERROR", **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "expected_credit_line_version": expected_credit_line_version,
        "reason_code": reason_code,
    }
    payload.update(overrides)
    return payload


def curtailment_run_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def aging_exception_payload(
    requested_extension_days: int = 15,
    justification_code: str = "RETAIL_DEAL_PENDING",
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "requested_extension_days": requested_extension_days,
        "justification_code": justification_code,
    }
    payload.update(overrides)
    return payload


def aging_exception_decision_payload(
    decision: str, reason_code: str, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision, "reason_code": reason_code}
    payload.update(overrides)
    return payload


def reinstate_credit_line_payload(reason_code: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason_code": reason_code}
    payload.update(overrides)
    return payload


def schedule_audit_payload(
    dealer_id: str,
    window_start_date: str,
    window_end_date: str,
    audit_type: str = "ANNOUNCED",
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "dealer_id": dealer_id,
        "audit_type": audit_type,
        "window_start_date": window_start_date,
        "window_end_date": window_end_date,
    }
    payload.update(overrides)
    return payload


def observation_payload(
    unit_id: str,
    observed_condition: str = "PRESENT",
    title_verified: bool = True,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "unit_id": unit_id,
        "observed_condition": observed_condition,
        "title_verified": title_verified,
    }
    payload.update(overrides)
    return payload


def remittance_payload(
    dealer_id: str,
    intent: str,
    amount_cents: int,
    expected_dealer_version: int,
    payment_reference: str = "PAY-TEST-0001",
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "dealer_id": dealer_id,
        "intent": intent,
        "amount_cents": amount_cents,
        "payment_reference": payment_reference,
        "expected_dealer_version": expected_dealer_version,
    }
    payload.update(overrides)
    return payload


def covenant_test_payload(
    period_end_date: str,
    reported_tangible_net_worth_cents: int,
    reported_ebitda_cents: int,
    reported_interest_expense_cents: int,
    reported_curtailment_paid_cents: int,
    reported_unrestricted_cash_cents: int,
    trailing_sot_incident_count: int = 0,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "period_end_date": period_end_date,
        "reported_tangible_net_worth_cents": reported_tangible_net_worth_cents,
        "reported_ebitda_cents": reported_ebitda_cents,
        "reported_interest_expense_cents": reported_interest_expense_cents,
        "reported_curtailment_paid_cents": reported_curtailment_paid_cents,
        "reported_unrestricted_cash_cents": reported_unrestricted_cash_cents,
        # Named on the payload but authoritatively derived by the service.
        "trailing_sot_incident_count": trailing_sot_incident_count,
    }
    payload.update(overrides)
    return payload


def remedy_action_payload(
    action_type: str, reason_code: str, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action_type": action_type, "reason_code": reason_code}
    payload.update(overrides)
    return payload


def make_vin(seed: str) -> str:
    """Build a 17-character uppercase alphanumeric VIN from a short seed."""
    body = "".join(ch for ch in seed.upper() if ch.isalnum())
    return (body + "0" * 17)[:17]
