"""Resource serialisers — emit dicts that match the field set declared in
SCAFFOLD §1.1 entities. Status enums include FORFEITED / VOIDED / EXPIRED /
REVERSED per PRD §2.4 (currently reserved values).
"""
from __future__ import annotations

from clock import format_iso


def _ts(x):
    return format_iso(x) if x is not None else None


def serialize_purchase_agreement(a: dict) -> dict:
    return {
        "id": a["id"],
        "created_at": _ts(a["created_at"]),
        "updated_at": _ts(a["updated_at"]),
        "version": a["version"],
        "buyer_name": a["buyer_name"],
        "seller_name": a["seller_name"],
        "property_address": a["property_address"],
        "purchase_price_cents": a["purchase_price_cents"],
        "earnest_money_required_cents": a["earnest_money_required_cents"],
        "scheduled_closing_date": _ts(a["scheduled_closing_date"]),
        "exchange_account_id": a.get("exchange_account_id"),
        "status": a["status"],
        "earnest_money_received_cents": a["earnest_money_received_cents"],
        "terminated_reason": a.get("terminated_reason"),
    }


def serialize_escrow_account(e: dict) -> dict:
    return {
        "id": e["id"],
        "created_at": _ts(e["created_at"]),
        "updated_at": _ts(e["updated_at"]),
        "version": e["version"],
        "agreement_id": e["agreement_id"],
        "escrow_officer_id": e["escrow_officer_id"],
        "balance_cents": e["balance_cents"],
        "status": e["status"],
    }


def serialize_earnest_money_deposit(d: dict) -> dict:
    return {
        "id": d["id"],
        "created_at": _ts(d["created_at"]),
        "updated_at": _ts(d["updated_at"]),
        "version": d["version"],
        "escrow_account_id": d["escrow_account_id"],
        "amount_cents": d["amount_cents"],
        "depositor_role": d["depositor_role"],
        "confirmation_reference": d.get("confirmation_reference"),
        "status": d["status"],
    }


def serialize_title_search(t: dict) -> dict:
    return {
        "id": t["id"],
        "created_at": _ts(t["created_at"]),
        "updated_at": _ts(t["updated_at"]),
        "version": t["version"],
        "agreement_id": t["agreement_id"],
        "defects": t.get("defects", []),
        "status": t["status"],
        "has_material_defect": t["has_material_defect"],
    }


def serialize_title_insurance_policy(p: dict) -> dict:
    return {
        "id": p["id"],
        "created_at": _ts(p["created_at"]),
        "updated_at": _ts(p["updated_at"]),
        "version": p["version"],
        "title_search_id": p["title_search_id"],
        "coverage_amount_cents": p["coverage_amount_cents"],
        "premium_cents": p["premium_cents"],
        "status": p["status"],
    }


def serialize_ccr_review(c: dict) -> dict:
    # Append-only: id + created_at + payload, no updated_at, no version.
    return {
        "id": c["id"],
        "created_at": _ts(c["created_at"]),
        "agreement_id": c["agreement_id"],
        "hoa_name": c.get("hoa_name"),
        "restrictions_summary": c["restrictions_summary"],
        "buyer_acknowledged": c["buyer_acknowledged"],
    }


def serialize_closing_disclosure(cd: dict) -> dict:
    return {
        "id": cd["id"],
        "created_at": _ts(cd["created_at"]),
        "updated_at": _ts(cd["updated_at"]),
        "version": cd["version"],
        "agreement_id": cd["agreement_id"],
        "issued_at": _ts(cd.get("issued_at")),
        "cd_apr_bps": cd["cd_apr_bps"],
        "cd_total_loan_amount_cents": cd["cd_total_loan_amount_cents"],
        "cd_monthly_payment_cents": cd["cd_monthly_payment_cents"],
        "cd_product_type": cd["cd_product_type"],
        "cd_prepayment_penalty": cd["cd_prepayment_penalty"],
        "status": cd["status"],
        "earliest_consummation_at": _ts(cd.get("earliest_consummation_at")),
        "acknowledged_at": _ts(cd.get("acknowledged_at")),
    }


def serialize_wire_instruction(w: dict) -> dict:
    return {
        "id": w["id"],
        "created_at": _ts(w["created_at"]),
        "updated_at": _ts(w["updated_at"]),
        "version": w["version"],
        "agreement_id": w["agreement_id"],
        "party": w["party"],
        "beneficiary_bank_name": w["beneficiary_bank_name"],
        "beneficiary_account_last4": w["beneficiary_account_last4"],
        "routing_number": w["routing_number"],
        "voice_callback_completed": w["voice_callback_completed"],
        "callback_verified_at": _ts(w.get("callback_verified_at")),
        "callback_verifier_id": w.get("callback_verifier_id"),
        "status": w["status"],
    }


def serialize_disbursement(d: dict) -> dict:
    return {
        "id": d["id"],
        "created_at": _ts(d["created_at"]),
        "updated_at": _ts(d["updated_at"]),
        "version": d["version"],
        "escrow_account_id": d["escrow_account_id"],
        "wire_instruction_id": d["wire_instruction_id"],
        "purpose": d["purpose"],
        "amount_cents": d["amount_cents"],
        "status": d["status"],
    }


def serialize_exchange_account(x: dict) -> dict:
    return {
        "id": x["id"],
        "created_at": _ts(x["created_at"]),
        "updated_at": _ts(x["updated_at"]),
        "version": x["version"],
        "taxpayer_name": x["taxpayer_name"],
        "qualified_intermediary_name": x["qualified_intermediary_name"],
        "relinquished_closing_date": _ts(x["relinquished_closing_date"]),
        "identification_deadline": _ts(x["identification_deadline"]),
        "exchange_deadline": _ts(x["exchange_deadline"]),
        "replacement_property_identified": x["replacement_property_identified"],
        "identified_at": _ts(x.get("identified_at")),
        "status": x["status"],
    }


def serialize_user(u: dict) -> dict:
    return {
        "id": u["id"],
        "created_at": _ts(u["created_at"]),
        "role": u["role"],
        "full_name": u["full_name"],
    }
