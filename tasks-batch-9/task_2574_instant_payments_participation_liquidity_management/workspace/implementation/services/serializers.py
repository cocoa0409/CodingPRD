"""Entity to JSON projections. Internal bookkeeping keys are never emitted."""

from db import db
from timeutils import iso
from services import liquidity


def participant(row):
    return {
        "id": row["id"],
        "legal_name": row["legal_name"],
        "routing_number": row["routing_number"],
        "settlement_agent_reference": row["settlement_agent_reference"],
        "participation_model": row["participation_model"],
        "enrollment_status": row["enrollment_status"],
        "operational_posture": row["operational_posture"],
        "attestation_document_reference": row["attestation_document_reference"],
        "certification_test_suite_version": row["certification_test_suite_version"],
        "certification_round": row["certification_round"],
        "go_live_business_date": row["go_live_business_date"],
        "suspension_reason": row["suspension_reason"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def position_account(row):
    balance = liquidity.current_balance(row)
    reserved = liquidity.reserved(row)
    return {
        "id": row["id"],
        "participant_id": row["participant_id"],
        "opening_balance_cents": row["opening_balance_cents"],
        "current_balance_cents": balance,
        "reserved_cents": reserved,
        "available_cents": balance - reserved,
        "warning_threshold_cents": row["warning_threshold_cents"],
        "critical_threshold_cents": row["critical_threshold_cents"],
        "floor_cents": row["floor_cents"],
        "alert_tier": row["alert_tier"],
        "last_ledger_sequence_no": row["last_ledger_sequence_no"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def ledger_entry(row):
    return {
        "id": row["id"],
        "account_id": row["account_id"],
        "related_transfer_id": row["related_transfer_id"],
        "entry_type": row["entry_type"],
        "amount_cents": row["amount_cents"],
        "balance_after_cents": row["balance_after_cents"],
        "business_date": row["business_date"],
        "sequence_no": row["sequence_no"],
        "reference": row["reference"],
        "created_at": iso(row["created_at"]),
    }


def liquidity_alert(row):
    return {
        "id": row["id"],
        "account_id": row["account_id"],
        "tier": row["tier"],
        "threshold_cents": row["threshold_cents"],
        "observed_balance_cents": row["observed_balance_cents"],
        "status": row["status"],
        "acknowledged_by_user_id": row["acknowledged_by_user_id"],
        "remediation_plan": row["remediation_plan"],
        "escalated_at": iso(row["escalated_at"]),
        "cleared_at": iso(row["cleared_at"]),
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def segment_policy(row):
    return {
        "id": row["id"],
        "participant_id": row["participant_id"],
        "segment": row["segment"],
        "per_transaction_limit_cents": row["per_transaction_limit_cents"],
        "daily_aggregate_limit_cents": row["daily_aggregate_limit_cents"],
        "rolling_window_count_limit": row["rolling_window_count_limit"],
        "rolling_window_amount_limit_cents": row["rolling_window_amount_limit_cents"],
        "effective_from": iso(row["effective_from"]),
        "effective_to": iso(row["effective_to"]),
        "superseded_at": iso(row["superseded_at"]),
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def customer_account(row):
    from services import limits
    return {
        "id": row["id"],
        "participant_id": row["participant_id"],
        "segment": row["segment"],
        "account_reference": row["account_reference"],
        "fraud_risk_baseline": row["fraud_risk_baseline"],
        "status": row["status"],
        "daily_sent_amount_cents": limits.daily_sent_amount(row["id"]),
        "restricted_at": iso(row["restricted_at"]),
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def credit_transfer(row):
    return {
        "id": row["id"],
        "originator_participant_id": row["originator_participant_id"],
        "customer_account_id": row["customer_account_id"],
        "segment_policy_id": row["segment_policy_id"],
        "rfp_id": row["rfp_id"],
        "compensating_for_transfer_id": row["compensating_for_transfer_id"],
        "receiver_routing_number": row["receiver_routing_number"],
        "amount_cents": row["amount_cents"],
        "direction": row["direction"],
        "rail": row["rail"],
        "clearing_status": row["clearing_status"],
        "exception_status": row["exception_status"],
        "fraud_score": row["fraud_score"],
        "fraud_reason_codes": list(row["fraud_reason_codes"]),
        "initiated_by_user_id": row["initiated_by_user_id"],
        "settlement_business_date": row["settlement_business_date"],
        "accepted_at": iso(row["accepted_at"]),
        "irrevocable_at": iso(row["irrevocable_at"]),
        "settled_at": iso(row["settled_at"]),
        "queued_at": iso(row["queued_at"]),
        "remittance_reference": row["remittance_reference"],
        "rejection_reason_code": row["rejection_reason_code"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def request_for_payment(row):
    return {
        "id": row["id"],
        "requestor_participant_id": row["requestor_participant_id"],
        "debtor_customer_account_id": row["debtor_customer_account_id"],
        "amount_cents": row["amount_cents"],
        "expiry_at": iso(row["expiry_at"]),
        "memo": row["memo"],
        "status": row["status"],
        "delivered_at": iso(row["delivered_at"]),
        "response_deadline_at": iso(row["response_deadline_at"]),
        "amendment_round": row["amendment_round"],
        "last_response": row["last_response"],
        "decline_reason_code": row["decline_reason_code"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def fraud_review(row):
    return {
        "id": row["id"],
        "credit_transfer_id": row["credit_transfer_id"],
        "score_at_origination": row["score_at_origination"],
        "final_fraud_score": row["final_fraud_score"],
        "queue_priority": row["queue_priority"],
        "status": row["status"],
        "assigned_reviewer_user_id": row["assigned_reviewer_user_id"],
        "sla_deadline_at": iso(row["sla_deadline_at"]),
        "decision_rationale": row["decision_rationale"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def return_request(row):
    return {
        "id": row["id"],
        "credit_transfer_id": row["credit_transfer_id"],
        "requested_by_participant_id": row["requested_by_participant_id"],
        "honored_transfer_id": row["honored_transfer_id"],
        "reason_code": row["reason_code"],
        "original_amount_cents": row["original_amount_cents"],
        "returned_amount_cents": row["returned_amount_cents"],
        "status": row["status"],
        "response_deadline_at": iso(row["response_deadline_at"]),
        "narrative": row["narrative"],
        "decline_reason_code": row["decline_reason_code"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def settlement_cycle(row):
    settled_count = 0
    for transfer in db.credit_transfers.values():
        if (transfer["direction"] == "OUTBOUND"
                and transfer["clearing_status"] == "SETTLED"
                and transfer["settlement_business_date"] == row["business_date"]):
            settled_count += 1
    return {
        "id": row["id"],
        "business_date": row["business_date"],
        "status": row["status"],
        "cutoff_at": iso(row["cutoff_at"]),
        "assessed_fee_total_cents": row["assessed_fee_total_cents"],
        "settled_transfer_count": settled_count,
        "closed_at": iso(row["closed_at"]),
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def reconciliation_run(row):
    return {
        "id": row["id"],
        "settlement_cycle_id": row["settlement_cycle_id"],
        "participant_id": row["participant_id"],
        "variant": row["variant"],
        "revision": row["revision"],
        "core_deposit_total_cents": row["core_deposit_total_cents"],
        "rail_net_position_cents": row["rail_net_position_cents"],
        "variance_cents": row["variance_cents"],
        "outcome": row["outcome"],
        "included_transfer_count": row["included_transfer_count"],
        "fee_component_cents": row["fee_component_cents"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def outage_event(row):
    return {
        "id": row["id"],
        "participant_id": row["participant_id"],
        "scope": row["scope"],
        "severity": row["severity"],
        "fallback_rail": row["fallback_rail"],
        "status": row["status"],
        "started_at": iso(row["started_at"]),
        "ended_at": iso(row["ended_at"]),
        "diverted_transfer_count": row["diverted_transfer_count"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def projection(payload):
    out = dict(payload)
    out["horizon_end"] = iso(payload["horizon_end"])
    return out
