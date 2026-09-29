"""Request-body builders.

Each builder returns a valid payload for one endpoint and accepts keyword
overrides. Passing ``Ellipsis`` (``...``) as an override value removes the key
from the payload entirely, which is how a test exercises a missing required
field. Field names are transcribed from the workflow narratives of PRD section 3.
"""

from typing import Any, Dict

from .constants import (
    CA_CONFIG,
    SEED_BOND_ISSUER,
    SEED_DELEGATE_NAME,
    SEED_LICENSEE_EIN,
    SEED_LICENSEE_NAME,
    SEED_MONTHLY_CAP_CENTS,
    SEED_NARRATIVE,
    SEED_NET_WORTH_CENTS,
    SEED_NET_WORTH_STATEMENT_DATE,
)


def _apply(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Merge overrides into a payload; an ``...`` value deletes the key."""
    for key, value in overrides.items():
        if value is Ellipsis:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


# ---------------------------------------------------------------------------
# Clock and reference data
# ---------------------------------------------------------------------------


def clock_payload(to_iso8601: str, **overrides: Any) -> Dict[str, Any]:
    return _apply({"to_iso8601": to_iso8601}, overrides)


def jurisdiction_payload(**overrides: Any) -> Dict[str, Any]:
    return _apply(dict(CA_CONFIG), overrides)


def licensee_payload(**overrides: Any) -> Dict[str, Any]:
    return _apply(
        {
            "legal_name": SEED_LICENSEE_NAME,
            "ein": SEED_LICENSEE_EIN,
            "reported_tangible_net_worth_cents": SEED_NET_WORTH_CENTS,
            "net_worth_statement_date": SEED_NET_WORTH_STATEMENT_DATE,
        },
        overrides,
    )


def financials_payload(**overrides: Any) -> Dict[str, Any]:
    return _apply(
        {
            "reported_tangible_net_worth_cents": SEED_NET_WORTH_CENTS,
            "net_worth_statement_date": SEED_NET_WORTH_STATEMENT_DATE,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Control chain
# ---------------------------------------------------------------------------


def control_person_payload(licensee_id: str, **overrides: Any) -> Dict[str, Any]:
    return _apply(
        {
            "licensee_id": licensee_id,
            "full_name": "Rowan Vega",
            "role_title": "PASSIVE_INVESTOR",
            "direct_ownership_bps": 1000,
        },
        overrides,
    )


def background_check_payload(outcome: str, **overrides: Any) -> Dict[str, Any]:
    return _apply({"outcome": outcome}, overrides)


def change_of_control_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    return _apply({"decision": decision}, overrides)


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------


def application_payload(
    licensee_id: str, jurisdiction_id: str, **overrides: Any
) -> Dict[str, Any]:
    return _apply(
        {
            "licensee_id": licensee_id,
            "jurisdiction_id": jurisdiction_id,
            "license_class": "MONEY_TRANSMISSION",
            "projected_annual_volume_cents": 500_000_000,
            "new_product_narrative": SEED_NARRATIVE,
        },
        overrides,
    )


def review_action_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    return _apply({"action": action}, overrides)


def resubmit_payload(projected_annual_volume_cents: int, **overrides: Any) -> Dict[str, Any]:
    return _apply(
        {"projected_annual_volume_cents": projected_annual_volume_cents}, overrides
    )


# ---------------------------------------------------------------------------
# Licences, bonds, obligations, renewals and surrender
# ---------------------------------------------------------------------------


def bond_payload(amount_cents: int, **overrides: Any) -> Dict[str, Any]:
    return _apply(
        {
            "amount_cents": amount_cents,
            "bond_issuer": SEED_BOND_ISSUER,
            "effective_date": "2026-08-01T00:00:00Z",
        },
        overrides,
    )


def bond_cancellation_payload(
    bond_cancellation_effective_date: str, **overrides: Any
) -> Dict[str, Any]:
    return _apply(
        {"bond_cancellation_effective_date": bond_cancellation_effective_date}, overrides
    )


def obligations_payload(delta_cents: int, **overrides: Any) -> Dict[str, Any]:
    return _apply(
        {"delta_cents": delta_cents, "memo": "Customer transmission balance movement."},
        overrides,
    )


def renewal_payload(
    renewal_year: int, payment_amount_cents: int, **overrides: Any
) -> Dict[str, Any]:
    return _apply(
        {"renewal_year": renewal_year, "payment_amount_cents": payment_amount_cents},
        overrides,
    )


def surrender_request_payload(
    expected_state_license_version: int, **overrides: Any
) -> Dict[str, Any]:
    return _apply(
        {
            "effective_date": "2026-12-31T00:00:00Z",
            "wind_down_narrative": "Customer balances transferred and agents released.",
            "expected_state_license_version": expected_state_license_version,
        },
        overrides,
    )


def surrender_decision_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    return _apply({"decision": decision}, overrides)


# ---------------------------------------------------------------------------
# Call reports
# ---------------------------------------------------------------------------


def call_report_payload(
    state_license_id: str,
    period_label: str,
    transmission_volume_cents: int,
    transaction_count: int,
    **overrides: Any,
) -> Dict[str, Any]:
    return _apply(
        {
            "state_license_id": state_license_id,
            "period_label": period_label,
            "transmission_volume_cents": transmission_volume_cents,
            "transaction_count": transaction_count,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Delegates and authorizations
# ---------------------------------------------------------------------------


def delegate_payload(licensee_id: str, **overrides: Any) -> Dict[str, Any]:
    return _apply(
        {
            "licensee_id": licensee_id,
            "legal_name": SEED_DELEGATE_NAME,
            "delegate_type": "AUTHORIZED_DELEGATE",
        },
        overrides,
    )


def oversight_review_payload(
    training_score: int, aml_test_score: int, recordkeeping_score: int, **overrides: Any
) -> Dict[str, Any]:
    return _apply(
        {
            "training_score": training_score,
            "aml_test_score": aml_test_score,
            "recordkeeping_score": recordkeeping_score,
        },
        overrides,
    )


def delegate_authorization_payload(
    delegate_id: str,
    state_license_id: str,
    effective_date: str,
    expiry_date: str,
    **overrides: Any,
) -> Dict[str, Any]:
    return _apply(
        {
            "delegate_id": delegate_id,
            "state_license_id": state_license_id,
            "effective_date": effective_date,
            "expiry_date": expiry_date,
            "monthly_volume_cap_cents": SEED_MONTHLY_CAP_CENTS,
        },
        overrides,
    )


def terminate_authorization_payload(**overrides: Any) -> Dict[str, Any]:
    return _apply({"reason": "Agent contract ended."}, overrides)


# ---------------------------------------------------------------------------
# Holdings and coverage tests
# ---------------------------------------------------------------------------


def investment_holding_payload(
    licensee_id: str,
    asset_class: str,
    counterparty_name: str,
    book_value_cents: int,
    market_value_cents: int,
    **overrides: Any,
) -> Dict[str, Any]:
    return _apply(
        {
            "licensee_id": licensee_id,
            "asset_class": asset_class,
            "counterparty_name": counterparty_name,
            "book_value_cents": book_value_cents,
            "market_value_cents": market_value_cents,
        },
        overrides,
    )


def investment_test_payload(
    licensee_id: str,
    method: str,
    expected_licensee_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    return _apply(
        {
            "licensee_id": licensee_id,
            "coverage_period_start": "2026-07-01T00:00:00Z",
            "coverage_period_end": "2026-07-31T00:00:00Z",
            "method": method,
            "expected_licensee_version": expected_licensee_version,
        },
        overrides,
    )


def certify_payload(**overrides: Any) -> Dict[str, Any]:
    return _apply({"attestation_note": "Coverage figures reviewed and attested."}, overrides)


# ---------------------------------------------------------------------------
# Examinations, information requests and enforcement
# ---------------------------------------------------------------------------


def exam_payload(
    licensee_id: str,
    lead_jurisdiction_id: str,
    fieldwork_start: str,
    fieldwork_end: str,
    **overrides: Any,
) -> Dict[str, Any]:
    return _apply(
        {
            "licensee_id": licensee_id,
            "lead_jurisdiction_id": lead_jurisdiction_id,
            "participating_jurisdiction_ids": [lead_jurisdiction_id],
            "fieldwork_start": fieldwork_start,
            "fieldwork_end": fieldwork_end,
        },
        overrides,
    )


def exam_status_payload(to_status: str, **overrides: Any) -> Dict[str, Any]:
    return _apply({"to_status": to_status}, overrides)


def information_request_payload(
    exam_id: str, jurisdiction_id: str, **overrides: Any
) -> Dict[str, Any]:
    return _apply(
        {
            "exam_id": exam_id,
            "jurisdiction_id": jurisdiction_id,
            "subject": "Transmission ledger extracts for the field period.",
            "requested_item_count": 3,
        },
        overrides,
    )


def information_response_payload(submitted_item_count: int, **overrides: Any) -> Dict[str, Any]:
    return _apply(
        {
            "submitted_item_count": submitted_item_count,
            "narrative": "Ledger extracts and reconciliations attached.",
        },
        overrides,
    )


def disposition_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    return _apply({"decision": decision}, overrides)


def enforcement_payload(
    state_license_id: str, jurisdiction_id: str, **overrides: Any
) -> Dict[str, Any]:
    return _apply(
        {
            "state_license_id": state_license_id,
            "jurisdiction_id": jurisdiction_id,
            "basis": "EXAM_FINDING",
            "penalty_cents": 250_000,
            "remediation_deadline_at": "2026-12-01T00:00:00Z",
        },
        overrides,
    )


def enforcement_response_payload(response: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"response": response}
    if response == "CONSENT_ORDER":
        payload["remediation_plan_narrative"] = "Controls rebuilt under a dated plan."
    return _apply(payload, overrides)


def enforcement_resolution_payload(outcome: str, **overrides: Any) -> Dict[str, Any]:
    return _apply({"outcome": outcome}, overrides)
