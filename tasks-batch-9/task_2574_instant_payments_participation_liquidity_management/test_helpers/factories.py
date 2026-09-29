"""Payload factories.

Each factory returns a complete, valid request body for one endpoint, with the
fields the PRD marks as required always present and optional fields omitted
unless a caller supplies them. Tests mutate the returned dict to build the one
invalid or boundary variant they are interested in.
"""

from typing import Any, Dict, Optional

from . import constants as K
from .types import Json


def _prune(payload: Json) -> Json:
    """Drop keys whose value is the `_OMIT` sentinel, keeping explicit nulls."""
    return {k: v for k, v in payload.items() if v is not _OMIT}


class _Omit:
    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return "<omit>"


_OMIT = _Omit()


# ------------------------------------------------------------------ clock
def clock_payload(current_utc: str) -> Json:
    return {"current_utc": current_utc}


# ------------------------------------------------------------------ participant
def participant_payload(
    legal_name: str = "Alpha National Bank",
    routing_number: str = K.ROUTING_ALPHA,
    settlement_agent_reference: str = "SA-ALPHA-01",
    participation_model: Any = _OMIT,
) -> Json:
    return _prune(
        {
            "legal_name": legal_name,
            "routing_number": routing_number,
            "settlement_agent_reference": settlement_agent_reference,
            "participation_model": participation_model,
        }
    )


def attestation_payload(
    attestation_document_reference: str = "ATT-ALPHA-2026-08",
    operational_readiness_confirmed: bool = True,
) -> Json:
    return {
        "attestation_document_reference": attestation_document_reference,
        "operational_readiness_confirmed": operational_readiness_confirmed,
    }


def certification_window_payload(certification_test_suite_version: str = "CERT-2026.2") -> Json:
    return {"certification_test_suite_version": certification_test_suite_version}


def certification_result_payload(outcome: str = "PASS") -> Json:
    return {"outcome": outcome}


def activation_payload(go_live_business_date: str = K.BUSINESS_DATE_2026_08_03) -> Json:
    return {"go_live_business_date": go_live_business_date}


def status_change_payload(target_status: str, suspension_reason: Any = _OMIT) -> Json:
    return _prune({"target_status": target_status, "suspension_reason": suspension_reason})


def participation_model_payload(participation_model: str) -> Json:
    return {"participation_model": participation_model}


# ------------------------------------------------------------- position account
def position_account_payload(
    participant_id: str,
    opening_balance_cents: int = 1_200_000_000,
    warning_threshold_cents: int = 1_100_000_000,
    critical_threshold_cents: int = 1_000_000_000,
    floor_cents: int = 200_000_000,
) -> Json:
    return {
        "participant_id": participant_id,
        "opening_balance_cents": opening_balance_cents,
        "warning_threshold_cents": warning_threshold_cents,
        "critical_threshold_cents": critical_threshold_cents,
        "floor_cents": floor_cents,
    }


def ledger_adjustment_payload(
    entry_type: str,
    magnitude_cents: int,
    reference: Any = _OMIT,
) -> Json:
    return _prune(
        {
            "entry_type": entry_type,
            "magnitude_cents": magnitude_cents,
            "reference": reference,
        }
    )


def alert_acknowledgement_payload(remediation_plan: str = "Correspondent funding requested for same-day value.") -> Json:
    return {"remediation_plan": remediation_plan}


# ------------------------------------------------------------- segment policy
def segment_policy_payload(
    participant_id: str,
    expected_participant_version: int,
    segment: str = "CORPORATE",
    per_transaction_limit_cents: int = 250_000_000,
    daily_aggregate_limit_cents: int = 500_000_000,
    rolling_window_count_limit: int = 5,
    rolling_window_amount_limit_cents: int = 400_000_000,
    effective_from: str = K.CLOCK_2026_08_01,
    effective_to: Any = _OMIT,
    supersede_open_ended: Any = _OMIT,
) -> Json:
    return _prune(
        {
            "participant_id": participant_id,
            "segment": segment,
            "per_transaction_limit_cents": per_transaction_limit_cents,
            "daily_aggregate_limit_cents": daily_aggregate_limit_cents,
            "rolling_window_count_limit": rolling_window_count_limit,
            "rolling_window_amount_limit_cents": rolling_window_amount_limit_cents,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "supersede_open_ended": supersede_open_ended,
            "expected_participant_version": expected_participant_version,
        }
    )


# ------------------------------------------------------------- customer account
def customer_account_payload(
    participant_id: str,
    account_reference: str = "CUST-ALPHA-0001",
    segment: str = "CORPORATE",
    fraud_risk_baseline: int = 20,
) -> Json:
    return {
        "participant_id": participant_id,
        "segment": segment,
        "account_reference": account_reference,
        "fraud_risk_baseline": fraud_risk_baseline,
    }


# ------------------------------------------------------------- credit transfer
def credit_transfer_payload(
    originator_participant_id: str,
    customer_account_id: str,
    amount_cents: int,
    expected_position_account_version: int,
    receiver_routing_number: str = K.ROUTING_BETA,
    remittance_reference: Any = _OMIT,
    rfp_id: Any = _OMIT,
) -> Json:
    return _prune(
        {
            "originator_participant_id": originator_participant_id,
            "customer_account_id": customer_account_id,
            "receiver_routing_number": receiver_routing_number,
            "amount_cents": amount_cents,
            "remittance_reference": remittance_reference,
            "rfp_id": rfp_id,
            "expected_position_account_version": expected_position_account_version,
        }
    )


def diversion_payload(fallback_rail: str) -> Json:
    return {"fallback_rail": fallback_rail}


# ------------------------------------------------------------- fraud review
def fraud_decision_payload(decision: str, decision_rationale: Any = _OMIT) -> Json:
    return _prune({"decision": decision, "decision_rationale": decision_rationale})


# ------------------------------------------------------------- request for payment
def request_for_payment_payload(
    requestor_participant_id: str,
    debtor_customer_account_id: str,
    amount_cents: int,
    expiry_at: str,
    memo: Any = _OMIT,
) -> Json:
    return _prune(
        {
            "requestor_participant_id": requestor_participant_id,
            "debtor_customer_account_id": debtor_customer_account_id,
            "amount_cents": amount_cents,
            "expiry_at": expiry_at,
            "memo": memo,
        }
    )


def rfp_response_payload(response: str, decline_reason_code: Any = _OMIT) -> Json:
    return _prune({"response": response, "decline_reason_code": decline_reason_code})


def rfp_amendment_payload(amount_cents: int, memo: Any = _OMIT) -> Json:
    return _prune({"amount_cents": amount_cents, "memo": memo})


# ------------------------------------------------------------- return request
def return_request_payload(
    credit_transfer_id: str,
    requested_by_participant_id: str,
    reason_code: str = "DUPLICATE_PAYMENT",
    returned_amount_cents: Any = _OMIT,
    narrative: Any = _OMIT,
) -> Json:
    return _prune(
        {
            "credit_transfer_id": credit_transfer_id,
            "requested_by_participant_id": requested_by_participant_id,
            "reason_code": reason_code,
            "returned_amount_cents": returned_amount_cents,
            "narrative": narrative,
        }
    )


def return_decline_payload(decline_reason_code: str) -> Json:
    return {"decline_reason_code": decline_reason_code}


# ------------------------------------------------------------- settlement cycle
def settlement_cycle_payload(business_date: str = K.BUSINESS_DATE_2026_08_03) -> Json:
    return {"business_date": business_date}


# ------------------------------------------------------------- reconciliation run
def reconciliation_run_payload(
    settlement_cycle_id: str,
    participant_id: str,
    core_deposit_total_cents: int,
    variant: str = "FINAL",
) -> Json:
    return {
        "settlement_cycle_id": settlement_cycle_id,
        "participant_id": participant_id,
        "variant": variant,
        "core_deposit_total_cents": core_deposit_total_cents,
    }


# ------------------------------------------------------------- outage event
def outage_event_payload(
    started_at: str,
    scope: str = "PARTICIPANT",
    severity: str = "FULL_OUTAGE",
    fallback_rail: str = "FALLBACK_ACH",
    participant_id: Any = _OMIT,
    ended_at: Any = _OMIT,
) -> Json:
    return _prune(
        {
            "scope": scope,
            "severity": severity,
            "fallback_rail": fallback_rail,
            "started_at": started_at,
            "ended_at": ended_at,
            "participant_id": participant_id,
        }
    )


def outage_resolution_payload(ended_at: str) -> Json:
    return {"ended_at": ended_at}


OMIT: Any = _OMIT
