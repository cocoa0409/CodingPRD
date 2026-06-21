"""Entity serializers — shape the JSON `data` payload for each resource.

Computed fields are derived inline (from the ledger / related records) at
serialization time, per PRD 2.4 (balances are never stored as standing totals).
"""

from db import store
from services import ledger


def custodial_party(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
        "full_name": rec["full_name"],
        "state_code": rec["state_code"],
        "assistance_status": rec["assistance_status"],
        "payee_status": rec["payee_status"],
    }


def noncustodial_party(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
        "full_name": rec["full_name"],
        "ssn_last4": rec["ssn_last4"],
        "supports_second_family": rec["supports_second_family"],
        "total_current_support_cents": total_current_support_cents(rec["id"]),
    }


def total_current_support_cents(ncp_id):
    """Sum current_support_cents over this obligor's ACTIVE/MODIFIED orders."""
    total = 0
    for o in store.support_orders.values():
        if o["noncustodial_party_id"] != ncp_id:
            continue
        if o["obligation_status"] in ("ACTIVE", "MODIFIED"):
            total += o["current_support_cents"]
    return total


def employer(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
        "legal_name": rec["legal_name"],
        "fein": rec["fein"],
        "remittance_method": rec["remittance_method"],
    }


def support_order(rec):
    oid = rec["id"]
    return {
        "id": oid,
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
        "custodial_party_id": rec["custodial_party_id"],
        "noncustodial_party_id": rec["noncustodial_party_id"],
        "current_support_cents": rec["current_support_cents"],
        "frequency": rec["frequency"],
        "interest_rate_bps": rec["interest_rate_bps"],
        "arrears_distribution_rule": rec["arrears_distribution_rule"],
        "assigned_arrears_cents": rec["assigned_arrears_cents"],
        "obligation_status": rec["obligation_status"],
        "enforcement_status": rec["enforcement_status"],
        "current_support_due_cents": ledger.current_support_due_cents(oid),
        "arrears_principal_cents": ledger.arrears_principal_cents(oid),
        "interest_balance_cents": ledger.interest_balance_cents(oid),
        "net_disbursed_to_family_cents": ledger.net_disbursed_to_family_cents(oid),
        "last_interest_accrual_at": rec["last_interest_accrual_at"],
    }


def income_withholding_order(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
        "support_order_id": rec["support_order_id"],
        "employer_id": rec["employer_id"],
        "ordered_amount_cents": rec["ordered_amount_cents"],
        "effective_start_at": rec["effective_start_at"],
        "effective_end_at": rec["effective_end_at"],
        "status": rec["status"],
    }


def remittance(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
        "employer_id": rec["employer_id"],
        "noncustodial_party_id": rec["noncustodial_party_id"],
        "disposable_earnings_cents": rec["disposable_earnings_cents"],
        "gross_remitted_cents": rec["gross_remitted_cents"],
        "ccpa_cap_cents": rec["ccpa_cap_cents"],
        "distributable_cents": rec["distributable_cents"],
        "status": rec["status"],
    }


def allocation(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
        "remittance_id": rec["remittance_id"],
        "support_order_id": rec["support_order_id"],
        "current_support_applied_cents": rec["current_support_applied_cents"],
        "interest_applied_cents": rec["interest_applied_cents"],
        "principal_applied_cents": rec["principal_applied_cents"],
        "total_applied_cents": rec["total_applied_cents"],
    }


def ledger_entry(rec):
    # LedgerEntry is append-only: id + created_at only, no updated_at / version.
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "support_order_id": rec["support_order_id"],
        "entry_type": rec["entry_type"],
        "bucket": rec["bucket"],
        "amount_cents": rec["amount_cents"],
        "source_ref": rec["source_ref"],
        "effective_at": rec["effective_at"],
    }


def disbursement(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
        "support_order_id": rec["support_order_id"],
        "custodial_party_id": rec["custodial_party_id"],
        "allocation_id": rec["allocation_id"],
        "method": rec["method"],
        "family_amount_cents": rec["family_amount_cents"],
        "state_retained_cents": rec["state_retained_cents"],
        "status": rec["status"],
    }


def modification(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
        "support_order_id": rec["support_order_id"],
        "proposed_current_support_cents": rec["proposed_current_support_cents"],
        "coverage_start_at": rec["coverage_start_at"],
        "coverage_end_at": rec["coverage_end_at"],
        "status": rec["status"],
    }


def enforcement_action(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
        "support_order_id": rec["support_order_id"],
        "action_type": rec["action_type"],
        "certified_arrears_cents": rec["certified_arrears_cents"],
        "status": rec["status"],
    }
