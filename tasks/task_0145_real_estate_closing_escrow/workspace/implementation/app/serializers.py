"""Serialization helpers turning internal entity dicts into wire-format JSON."""
from __future__ import annotations

from typing import Any, Dict

from app.util import to_money_float


def _money(value: Any) -> float:
    if value is None:
        return 0.00
    return to_money_float(value)


def serialize_party(p: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": p["id"],
        "full_name": p["full_name"],
        "party_kind": p["party_kind"],
        "contact_email": p["contact_email"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_property(p: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": p["id"],
        "street_address": p["street_address"],
        "parcel_id": p["parcel_id"],
        "hoa_annual_dues": _money(p["hoa_annual_dues"]),
        "tax_annual": _money(p["tax_annual"]),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_escrow_file(f: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": f["id"],
        "property_id": f["property_id"],
        "buyer_party_id": f["buyer_party_id"],
        "seller_party_id": f["seller_party_id"],
        "lender_party_id": f.get("lender_party_id"),
        "qi_party_id": f.get("qi_party_id"),
        "purchase_price": _money(f["purchase_price"]),
        "loan_amount": _money(f.get("loan_amount", 0)),
        "closing_date_planned": f["closing_date_planned"],
        "is_1031_exchange": bool(f.get("is_1031_exchange", False)),
        "status": f["status"],
        "cancel_reason": f.get("cancel_reason"),
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def serialize_emd(e: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": e["id"],
        "escrow_file_id": e["escrow_file_id"],
        "amount": _money(e["amount"]),
        "forfeited_amount": _money(e.get("forfeited_amount", 0)),
        "refunded_amount": _money(e.get("refunded_amount", 0)),
        "split_buyer_share": _money(e.get("split_buyer_share", 0)),
        "split_seller_share": _money(e.get("split_seller_share", 0)),
        "status": e["status"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def serialize_title_search(t: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": t["id"],
        "escrow_file_id": t["escrow_file_id"],
        "chain_of_title_clean": t.get("chain_of_title_clean"),
        "open_liens_total": _money(t.get("open_liens_total", 0)),
        "encumbrance_count": int(t.get("encumbrance_count", 0) or 0),
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def serialize_title_policy(p: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": p["id"],
        "escrow_file_id": p["escrow_file_id"],
        "policy_kind": p["policy_kind"],
        "insured_amount": _money(p["insured_amount"]),
        "simultaneous_issue": bool(p.get("simultaneous_issue", False)),
        "premium": _money(p["premium"]),
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_ccr(c: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": c["id"],
        "escrow_file_id": c["escrow_file_id"],
        "ccr_document_hash": c["ccr_document_hash"],
        "buyer_acknowledged_at": c["buyer_acknowledged_at"],
        "material_restrictions": list(c.get("material_restrictions", [])),
        "created_at": c["created_at"],
    }


def serialize_cd(c: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": c["id"],
        "escrow_file_id": c["escrow_file_id"],
        "version_number": int(c.get("version_number", 1)),
        "cash_to_close": _money(c.get("cash_to_close", 0)),
        "total_loan_costs": _money(c.get("total_loan_costs", 0)),
        "seller_credits": _money(c.get("seller_credits", 0)),
        "prorated_tax_credit": _money(c.get("prorated_tax_credit", 0)),
        "prorated_hoa_credit": _money(c.get("prorated_hoa_credit", 0)),
        "seller_days_owned": int(c.get("seller_days_owned", 0)),
        "issued_at": c.get("issued_at"),
        "earliest_funding_at": c.get("earliest_funding_at"),
        "buyer_acknowledged_at": c.get("buyer_acknowledged_at"),
        "status": c["status"],
        "triggering_change_kind": c.get("triggering_change_kind", "NONE"),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_wire(w: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": w["id"],
        "escrow_file_id": w["escrow_file_id"],
        "beneficiary_kind": w["beneficiary_kind"],
        "beneficiary_party_id": w["beneficiary_party_id"],
        "routing_number": w["routing_number"],
        "account_number_last4": w["account_number_last4"],
        "confirmation_callback_at": w.get("confirmation_callback_at"),
        "confirmed_by_user_id": w.get("confirmed_by_user_id"),
        "callback_channel": w.get("callback_channel"),
        "status": w["status"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


def serialize_disbursement(d: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": d["id"],
        "escrow_file_id": d["escrow_file_id"],
        "wire_instruction_id": d["wire_instruction_id"],
        "amount": _money(d["amount"]),
        "approved_by_user_id": d.get("approved_by_user_id"),
        "status": d["status"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def serialize_exchange(x: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": x["id"],
        "escrow_file_id": x["escrow_file_id"],
        "relinquished_basis": _money(x["relinquished_basis"]),
        "relinquished_sale_price": _money(x["relinquished_sale_price"]),
        "cash_boot_received": _money(x.get("cash_boot_received", 0)),
        "mortgage_relief": _money(x.get("mortgage_relief", 0)),
        "realized_gain": _money(x["realized_gain"]),
        "recognized_gain": _money(x["recognized_gain"]),
        "deferred_gain": _money(x["deferred_gain"]),
        "identification_deadline_at": x["identification_deadline_at"],
        "exchange_deadline_at": x["exchange_deadline_at"],
        "status": x["status"],
        "created_at": x["created_at"],
        "updated_at": x["updated_at"],
        "version": x["version"],
    }


def serialize_audit(a: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": a["id"],
        "escrow_file_id": a["escrow_file_id"],
        "subject_kind": a["subject_kind"],
        "subject_id": a["subject_id"],
        "actor_user_id": a["actor_user_id"],
        "actor_role": a["actor_role"],
        "action": a["action"],
        "payload_hash": a["payload_hash"],
        "created_at": a["created_at"],
    }
