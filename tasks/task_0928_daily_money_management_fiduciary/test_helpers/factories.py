"""Payload factories - one per creatable resource, input fields only."""

from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS

DEFAULTS = {
    "CLIENT_NAME": "Rosa Mendel",
    "CLIENT_DOB": "1941-03-08",
    "INTAKE_REFERENCE": "INT-9001",
    "CARRIER_NAME": "Atlas Surety",
    "BOND_NUMBER": "SB-2026-001",
    "INSTITUTION_NAME": "First Community Bank",
    "ACCOUNT_LABEL": "Operating",
    "PAYEE_NAME": "City Power",
    "REMITTANCE_REFERENCE": "ACC-77",
    "CATEGORY_NAME": "UTILITIES",
    "INSTRUMENT_REFERENCE": "AGR-2026-11",
    "RECIPIENT_NAME": "Dana Mendel",
    "RECIPIENT_EMAIL": "dana@example.org",
    "CAPACITY_DETERMINED_ON": "2026-05-15",
}


def create_client_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "full_name": DEFAULTS["CLIENT_NAME"],
        "date_of_birth": DEFAULTS["CLIENT_DOB"],
        "intake_reference": DEFAULTS["INTAKE_REFERENCE"],
    }
    payload.update(overrides)
    return payload


def capacity_determination_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "determination": "RETAINS_CAPACITY",
        "determined_on": DEFAULTS["CAPACITY_DETERMINED_ON"],
    }
    payload.update(overrides)
    return payload


def client_status_payload(to_status: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_status": to_status}
    payload.update(overrides)
    return payload


def create_authorization_payload(client_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "client_id": client_id,
        "scope_tier": "FULL_AGENCY",
        "instrument_reference": DEFAULTS["INSTRUMENT_REFERENCE"],
        "effective_date": TEST_DEFAULTS["AUTH_EFFECTIVE_DATE"],
        "expiry_date": TEST_DEFAULTS["AUTH_EXPIRY_DATE"],
    }
    payload.update(overrides)
    return payload


def create_surety_bond_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "carrier_name": DEFAULTS["CARRIER_NAME"],
        "bond_number": DEFAULTS["BOND_NUMBER"],
        "coverage_cents": TEST_DEFAULTS["BOND_COVERAGE_CENTS"],
        "effective_date": TEST_DEFAULTS["BOND_EFFECTIVE_DATE"],
        "expiry_date": TEST_DEFAULTS["BOND_EXPIRY_DATE"],
    }
    payload.update(overrides)
    return payload


def create_account_payload(client_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "client_id": client_id,
        "institution_name": DEFAULTS["INSTITUTION_NAME"],
        "account_label": DEFAULTS["ACCOUNT_LABEL"],
        "account_type": "CHECKING",
        "opening_balance_cents": TEST_DEFAULTS["OPENING_BALANCE_CENTS"],
    }
    payload.update(overrides)
    return payload


def account_adjustment_payload(
    adjustment_type: str, amount_cents: int, value_date: str, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "adjustment_type": adjustment_type,
        "amount_cents": amount_cents,
        "value_date": value_date,
    }
    payload.update(overrides)
    return payload


def fraud_posture_payload(to_posture: str, reason: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_posture": to_posture, "reason": reason}
    payload.update(overrides)
    return payload


def create_payee_payload(client_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "client_id": client_id,
        "payee_name": DEFAULTS["PAYEE_NAME"],
        "payee_type": "RECURRING_BILLER",
        "remittance_reference": DEFAULTS["REMITTANCE_REFERENCE"],
    }
    payload.update(overrides)
    return payload


def create_budget_category_payload(client_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "client_id": client_id,
        "category_name": DEFAULTS["CATEGORY_NAME"],
        "budget_month": "2026-06",
        "allocation_cents": TEST_DEFAULTS["ALLOCATION_CENTS"],
    }
    payload.update(overrides)
    return payload


def budget_override_payload(added_cents: int, reason: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"added_cents": added_cents, "reason": reason}
    payload.update(overrides)
    return payload


def create_payment_payload(
    account_id: str,
    payee_id: str,
    authorization_id: str,
    budget_category_id: str,
    amount_cents: int,
    expected_account_version: int,
    channel: str = "ACH",
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "account_id": account_id,
        "payee_id": payee_id,
        "authorization_id": authorization_id,
        "budget_category_id": budget_category_id,
        "amount_cents": amount_cents,
        "channel": channel,
        "expected_account_version": expected_account_version,
    }
    payload.update(overrides)
    return payload


def approval_decision_payload(decision: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


def revise_payment_payload(amount_cents: int, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def settlement_event_payload(event: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"event": event}
    payload.update(overrides)
    return payload


def create_dispute_payload(
    payment_id: str, disputed_amount_cents: int, reason_code: str = "UNAUTHORIZED", **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "payment_id": payment_id,
        "reason_code": reason_code,
        "disputed_amount_cents": disputed_amount_cents,
    }
    payload.update(overrides)
    return payload


def resolve_dispute_payload(outcome: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    payload.update(overrides)
    return payload


def create_reconciliation_period_payload(
    account_id: str, period_month: str = "2026-06", **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"account_id": account_id, "period_month": period_month}
    payload.update(overrides)
    return payload


def import_statement_line_payload(
    external_ref: str, amount_cents: int, line_date: str, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "external_ref": external_ref,
        "amount_cents": amount_cents,
        "line_date": line_date,
    }
    payload.update(overrides)
    return payload


def period_status_payload(to_status: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_status": to_status}
    payload.update(overrides)
    return payload


def statement_line_disposition_payload(
    action: str, expected_period_version: int, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "action": action,
        "expected_period_version": expected_period_version,
    }
    payload.update(overrides)
    return payload


def create_fraud_alert_payload(
    account_id: str, payment_id: str, reason_code: str = "UNRECOGNIZED_PAYEE", **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "account_id": account_id,
        "payment_id": payment_id,
        "reason_code": reason_code,
    }
    payload.update(overrides)
    return payload


def fraud_alert_disposition_payload(action: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload


def create_benefit_application_payload(
    client_id: str,
    authorization_id: str,
    program: str = "MEDICAID",
    asserted_monthly_income_cents: int = 120000,
    resource_items: Optional[List[Dict[str, Any]]] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "client_id": client_id,
        "authorization_id": authorization_id,
        "program": program,
        "asserted_monthly_income_cents": asserted_monthly_income_cents,
        "resource_items": (
            resource_items
            if resource_items is not None
            else [{"item_type": "CASH", "value_cents": 100000}]
        ),
    }
    payload.update(overrides)
    return payload


def benefit_application_status_payload(action: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload


def record_decision_payload(
    outcome: str, decision_date: str, account_id: str, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "outcome": outcome,
        "decision_date": decision_date,
        "account_id": account_id,
    }
    payload.update(overrides)
    return payload


def create_family_recipient_payload(
    client_id: str, authorization_id: str, **overrides
) -> Dict[str, Any]:
    payload = {
        "client_id": client_id,
        "authorization_id": authorization_id,
        "full_name": DEFAULTS["RECIPIENT_NAME"],
        "contact_email": DEFAULTS["RECIPIENT_EMAIL"],
        "relationship": "CHILD",
    }
    payload.update(overrides)
    return payload


def consent_payload(permitted_categories: List[str], **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"permitted_categories": list(permitted_categories)}
    payload.update(overrides)
    return payload


def create_family_report_payload(
    recipient_id: str, report_month: str, expected_recipient_version: int, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "recipient_id": recipient_id,
        "report_month": report_month,
        "expected_recipient_version": expected_recipient_version,
    }
    payload.update(overrides)
    return payload


def create_coordination_request_payload(
    client_id: str,
    assigned_member_user_id: str,
    tier: str = "ROUTINE",
    subject: str = "Arrange a home safety assessment",
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "client_id": client_id,
        "subject": subject,
        "tier": tier,
        "assigned_member_user_id": assigned_member_user_id,
    }
    payload.update(overrides)
    return payload


def coordination_disposition_payload(action: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload


def clock_payload(to_iso8601: str) -> Dict[str, Any]:
    return {"to_iso8601": to_iso8601}
