"""Serialise internal entity dicts to JSON-safe response payloads."""
from __future__ import annotations

from decimal import Decimal

from utils import iso_now, money_float


def _ts(value):
    if value is None:
        return None
    return iso_now(value)


def _money(value):
    """Always emit money as a 2dp float (PRD §2.7)."""
    return money_float(value) if value is not None else 0.00


def trust_view(t: dict) -> dict:
    return {
        "id": t["id"],
        "name": t["name"],
        "trust_type": t["trust_type"],
        "grantor_tax_status": t["grantor_tax_status"],
        "has_grantor_powers": t["has_grantor_powers"],
        "grantor_user_id": t["grantor_user_id"],
        "situs_state": t["situs_state"],
        "inception_date": _ts(t["inception_date"]),
        "status": t["status"],
        "principal_balance": _money(t["principal_balance"]),
        "income_balance": _money(t["income_balance"]),
        "gst_exemption_used": _money(t["gst_exemption_used"]),
        "current_tax_year_id": t["current_tax_year_id"],
        "created_at": _ts(t["created_at"]),
        "updated_at": _ts(t["updated_at"]),
        "version": t["version"],
    }


def trustee_view(t: dict) -> dict:
    return {
        "id": t["id"],
        "trust_id": t["trust_id"],
        "user_id": t["user_id"],
        "full_name": t["full_name"],
        "is_primary": t["is_primary"],
        "status": t["status"],
        "created_at": _ts(t["created_at"]),
        "updated_at": _ts(t["updated_at"]),
        "version": t["version"],
    }


def beneficiary_view(b: dict) -> dict:
    return {
        "id": b["id"],
        "trust_id": b["trust_id"],
        "full_name": b["full_name"],
        "relation_class": b["relation_class"],
        "is_skip_person": b["is_skip_person"],
        "beneficiary_class": b["beneficiary_class"],
        "distribution_tier": b["distribution_tier"],
        "status": b["status"],
        "birth_date": _ts(b["birth_date"]),
        "created_at": _ts(b["created_at"]),
        "updated_at": _ts(b["updated_at"]),
        "version": b["version"],
    }


def asset_view(a: dict) -> dict:
    return {
        "id": a["id"],
        "trust_id": a["trust_id"],
        "description": a["description"],
        "asset_class": a["asset_class"],
        "book_value": _money(a["book_value"]),
        "classification": a["classification"],
        "status": a["status"],
        "created_at": _ts(a["created_at"]),
        "updated_at": _ts(a["updated_at"]),
        "version": a["version"],
    }


def transaction_view(tx: dict) -> dict:
    # Append-only: only id + created_at as common fields (PRD §2.4).
    return {
        "id": tx["id"],
        "trust_id": tx["trust_id"],
        "tax_year_id": tx["tax_year_id"],
        "txn_type": tx["txn_type"],
        "amount": _money(tx["amount"]),
        "transaction_date": _ts(tx["transaction_date"]),
        "principal_or_income": tx["principal_or_income"],
        "description": tx["description"],
        "created_at": _ts(tx["created_at"]),
    }


def distribution_view(d: dict) -> dict:
    return {
        "id": d["id"],
        "trust_id": d["trust_id"],
        "beneficiary_id": d["beneficiary_id"],
        "tax_year_id": d["tax_year_id"],
        "scheduled_date": _ts(d["scheduled_date"]),
        "amount_principal": _money(d["amount_principal"]),
        "amount_income": _money(d["amount_income"]),
        "distribution_type": d["distribution_type"],
        "status": d["status"],
        "proposed_by_user_id": d["proposed_by_user_id"],
        "approved_by_user_id": d["approved_by_user_id"],
        "gst_taxable": d["gst_taxable"],
        "gst_tax_amount": _money(d["gst_tax_amount"]),
        "created_at": _ts(d["created_at"]),
        "updated_at": _ts(d["updated_at"]),
        "version": d["version"],
    }


def tax_year_view(ty: dict) -> dict:
    return {
        "id": ty["id"],
        "trust_id": ty["trust_id"],
        "calendar_year": ty["calendar_year"],
        "start_date": _ts(ty["start_date"]),
        "end_date": _ts(ty["end_date"]),
        "status": ty["status"],
        "dni": _money(ty["dni"]),
        "trust_taxable_income": _money(ty["trust_taxable_income"]),
        "trust_income_tax": _money(ty["trust_income_tax"]),
        "closed_at": _ts(ty["closed_at"]),
        "created_at": _ts(ty["created_at"]),
        "updated_at": _ts(ty["updated_at"]),
        "version": ty["version"],
    }


def k1_view(k: dict) -> dict:
    return {
        "id": k["id"],
        "tax_year_id": k["tax_year_id"],
        "trust_id": k["trust_id"],
        "beneficiary_id": k["beneficiary_id"],
        "ordinary_income_share": _money(k["ordinary_income_share"]),
        "interest_income_share": _money(k["interest_income_share"]),
        "dividend_income_share": _money(k["dividend_income_share"]),
        "capital_gain_share": _money(k["capital_gain_share"]),
        "total_distributed": _money(k["total_distributed"]),
        "status": k["status"],
        "snapshot_distribution_version_sum": k["snapshot_distribution_version_sum"],
        "issued_at": _ts(k["issued_at"]),
        "created_at": _ts(k["created_at"]),
        "updated_at": _ts(k["updated_at"]),
        "version": k["version"],
    }
