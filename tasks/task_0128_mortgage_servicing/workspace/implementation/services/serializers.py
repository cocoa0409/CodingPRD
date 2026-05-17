"""Convert internal dicts into wire-format dicts (ISO strings, etc.)."""
from __future__ import annotations

from datetime import datetime

from utils import iso_now


def _ts(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return iso_now(v)
    return v


def borrower_view(b: dict) -> dict:
    return {
        "id": b["id"],
        "full_name": b["full_name"],
        "email": b["email"],
        "hardship_attested_at": _ts(b.get("hardship_attested_at")),
        "created_at": _ts(b["created_at"]),
        "updated_at": _ts(b["updated_at"]),
        "version": b["version"],
    }


def loan_view(l: dict) -> dict:
    return {
        "id": l["id"],
        "borrower_id": l["borrower_id"],
        "origination_date": _ts(l["origination_date"]),
        "original_principal_cents": l["original_principal_cents"],
        "original_appraised_value_cents": l["original_appraised_value_cents"],
        "interest_rate_bps": l["interest_rate_bps"],
        "term_months": l["term_months"],
        "scheduled_payment_cents": l["scheduled_payment_cents"],
        "principal_balance_cents": l["principal_balance_cents"],
        "escrow_balance_cents": l["escrow_balance_cents"],
        "monthly_escrow_payment_cents": l["monthly_escrow_payment_cents"],
        "pmi_monthly_cents": l["pmi_monthly_cents"],
        "pmi_status": l["pmi_status"],
        "next_due_date": _ts(l["next_due_date"]),
        "posture": l["posture"],
        "delinquency_days": l["delinquency_days"],
        "created_at": _ts(l["created_at"]),
        "updated_at": _ts(l["updated_at"]),
        "version": l["version"],
    }


def payment_view(p: dict) -> dict:
    return {
        "id": p["id"],
        "loan_id": p["loan_id"],
        "received_date": _ts(p["received_date"]),
        "amount_cents": p["amount_cents"],
        "allocation_principal_cents": p["allocation_principal_cents"],
        "allocation_interest_cents": p["allocation_interest_cents"],
        "allocation_escrow_cents": p["allocation_escrow_cents"],
        "allocation_late_fee_cents": p["allocation_late_fee_cents"],
        "allocation_suspense_cents": p["allocation_suspense_cents"],
        "status": p["status"],
        "reversed_at": _ts(p.get("reversed_at")),
        "created_at": _ts(p["created_at"]),
        "updated_at": _ts(p["updated_at"]),
        "version": p["version"],
    }


def escrow_analysis_view(e: dict) -> dict:
    return {
        "id": e["id"],
        "loan_id": e["loan_id"],
        "analysis_date": _ts(e["analysis_date"]),
        "status": e["status"],
        "projected_disbursements_cents": e["projected_disbursements_cents"],
        "required_cushion_cents": e["required_cushion_cents"],
        "starting_balance_cents": e["starting_balance_cents"],
        "shortage_cents": e["shortage_cents"],
        "surplus_cents": e["surplus_cents"],
        "new_monthly_escrow_cents": e["new_monthly_escrow_cents"],
        "finalized_at": _ts(e.get("finalized_at")),
        "created_at": _ts(e["created_at"]),
    }


def disbursement_view(d: dict) -> dict:
    return {
        "id": d["id"],
        "loan_id": d["loan_id"],
        "type": d["type"],
        "scheduled_date": _ts(d["scheduled_date"]),
        "amount_cents": d["amount_cents"],
        "status": d["status"],
        "paid_at": _ts(d.get("paid_at")),
        "failure_reason": d.get("failure_reason"),
        "created_at": _ts(d["created_at"]),
        "updated_at": _ts(d["updated_at"]),
        "version": d["version"],
    }


def forbearance_view(f: dict) -> dict:
    return {
        "id": f["id"],
        "loan_id": f["loan_id"],
        "start_date": _ts(f["start_date"]),
        "months": f["months"],
        "end_date": _ts(f["end_date"]),
        "total_paused_cents": f["total_paused_cents"],
        "repayment_method": f["repayment_method"],
        "status": f["status"],
        "cure_balance_cents": f["cure_balance_cents"],
        "created_at": _ts(f["created_at"]),
        "updated_at": _ts(f["updated_at"]),
        "version": f["version"],
    }


def pmi_request_view(p: dict) -> dict:
    return {
        "id": p["id"],
        "loan_id": p["loan_id"],
        "trigger": p["trigger"],
        "current_appraised_value_cents": p.get("current_appraised_value_cents"),
        "evaluated_ltv_bps": p["evaluated_ltv_bps"],
        "decision": p["decision"],
        "denial_reason": p.get("denial_reason"),
        "created_at": _ts(p["created_at"]),
        "updated_at": _ts(p["updated_at"]),
        "version": p["version"],
    }


def foreclosure_view(c: dict) -> dict:
    return {
        "id": c["id"],
        "loan_id": c["loan_id"],
        "opened_at": _ts(c.get("opened_at")),
        "status": c["status"],
        "noi_sent_at": _ts(c.get("noi_sent_at")),
        "filed_at": _ts(c.get("filed_at")),
        "auction_date": _ts(c.get("auction_date")),
        "reinstatement_quote_cents": c["reinstatement_quote_cents"],
        "foreclosure_costs_cents": c["foreclosure_costs_cents"],
        "created_at": _ts(c["created_at"]),
        "updated_at": _ts(c["updated_at"]),
        "version": c["version"],
    }


def mediation_view(m: dict) -> dict:
    return {
        "id": m["id"],
        "foreclosure_case_id": m["foreclosure_case_id"],
        "opened_at": _ts(m.get("opened_at")),
        "status": m["status"],
        "offered_new_rate_bps": m.get("offered_new_rate_bps"),
        "offered_term_extension_months": m.get("offered_term_extension_months"),
        "offered_principal_forbearance_cents": m["offered_principal_forbearance_cents"],
        "target_payment_cents": m.get("target_payment_cents"),
        "rejection_reason": m.get("rejection_reason"),
        "created_at": _ts(m["created_at"]),
        "updated_at": _ts(m["updated_at"]),
        "version": m["version"],
    }
