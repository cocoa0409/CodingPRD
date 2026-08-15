"""Serializers mapping internal records to API representations (PRD §2.4).

Primary resources carry id/created_at/updated_at/version. AccountTransaction
is the deliberate exception: append-only, exposing only id and created_at.
Derived account figures are attached at read time.
"""

import db
from services.account import derived_totals


def account_view(a):
    total_held, available = derived_totals(a["id"])
    return {
        "id": a["id"],
        "account_number": a["account_number"],
        "primary_owner_name": a["primary_owner_name"],
        "owner_tax_id": a["owner_tax_id"],
        "ownership_type": a["ownership_type"],
        "pod_beneficiary_name": a["pod_beneficiary_name"],
        "product_code": a["product_code"],
        "rate_bps": a["rate_bps"],
        "lifecycle_status": a["lifecycle_status"],
        "restriction_status": a["restriction_status"],
        "balance_cents": a["balance_cents"],
        "total_held_cents": total_held,
        "available_balance_cents": available,
        "accrual_start_date": a["accrual_start_date"],
        "accrued_interest_cents": a["accrued_interest_cents"],
        "last_customer_activity_date": a["last_customer_activity_date"],
        "dormant_since_date": a["dormant_since_date"],
        "fees_assessed_count": a["fees_assessed_count"],
        "statement_suppression": a["statement_suppression"],
        "closure_payout_cents": a["closure_payout_cents"],
        "closure_payout_destination": a["closure_payout_destination"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def transaction_view(t):
    return {
        "id": t["id"],
        "account_id": t["account_id"],
        "txn_type": t["txn_type"],
        "amount_cents": t["amount_cents"],
        "customer_initiated": t["customer_initiated"],
        "posted_date": t["posted_date"],
        "balance_after_cents": t["balance_after_cents"],
        "created_at": t["created_at"],
    }


def signer_view(s):
    return {
        "id": s["id"],
        "account_id": s["account_id"],
        "full_name": s["full_name"],
        "tax_id": s["tax_id"],
        "signer_role": s["signer_role"],
        "signature_card_reference": s["signature_card_reference"],
        "status": s["status"],
        "removed_reason": s["removed_reason"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def document_view(d):
    return {
        "id": d["id"],
        "account_id": d["account_id"],
        "doc_type": d["doc_type"],
        "reference_number": d["reference_number"],
        "status": d["status"],
        "reviewed_by_user_id": d["reviewed_by_user_id"],
        "review_note": d["review_note"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def title_change_view(r):
    return {
        "id": r["id"],
        "account_id": r["account_id"],
        "current_ownership_type": r["current_ownership_type"],
        "requested_ownership_type": r["requested_ownership_type"],
        "pod_beneficiary_name": r["pod_beneficiary_name"],
        "required_doc_types": list(r["required_doc_types"]),
        "status": r["status"],
        "created_by_user_id": r["created_by_user_id"],
        "decided_by_user_id": r["decided_by_user_id"],
        "decision_reason": r["decision_reason"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def deceased_case_view(c):
    return {
        "id": c["id"],
        "account_id": c["account_id"],
        "decedent_name": c["decedent_name"],
        "date_of_death": c["date_of_death"],
        "reported_by": c["reported_by"],
        "status": c["status"],
        "balance_at_death_cents": c["balance_at_death_cents"],
        "accrued_interest_at_death_cents": c["accrued_interest_at_death_cents"],
        "release_variant": c["release_variant"],
        "release_amount_cents": c["release_amount_cents"],
        "estate_representative_name": c["estate_representative_name"],
        "initiated_by_user_id": c["initiated_by_user_id"],
        "approved_by_user_id": c["approved_by_user_id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def garnishment_view(g):
    return {
        "id": g["id"],
        "account_id": g["account_id"],
        "order_type": g["order_type"],
        "creditor_name": g["creditor_name"],
        "amount_cents": g["amount_cents"],
        "served_date": g["served_date"],
        "answer_deadline_date": g["answer_deadline_date"],
        "exemption_method": g["exemption_method"],
        "held_amount_cents": g["held_amount_cents"],
        "exempt_amount_cents": g["exempt_amount_cents"],
        "collectible_cents": g["collectible_cents"],
        "remitted_amount_cents": g["remitted_amount_cents"],
        "released_amount_cents": g["released_amount_cents"],
        "received_by_user_id": g["received_by_user_id"],
        "resolved_by_user_id": g["resolved_by_user_id"],
        "status": g["status"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


def statement_cycle_view(c):
    return {
        "id": c["id"],
        "account_id": c["account_id"],
        "cycle_start": c["cycle_start"],
        "cycle_end": c["cycle_end"],
        "status": c["status"],
        "suppression_reason": c["suppression_reason"],
        "produced_date": c["produced_date"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def conversion_view(c):
    return {
        "id": c["id"],
        "account_id": c["account_id"],
        "from_product_code": c["from_product_code"],
        "to_product_code": c["to_product_code"],
        "new_rate_bps": c["new_rate_bps"],
        "effective_date": c["effective_date"],
        "accrued_interest_settled_cents": c["accrued_interest_settled_cents"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }
