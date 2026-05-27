"""Entity serialization to JSON-friendly dicts (datetimes -> ISO strings)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from common import iso_format


def _ts(v: Optional[datetime]) -> Optional[str]:
    if v is None:
        return None
    return iso_format(v)


def view_decedent(d: dict) -> dict:
    return {
        "id": d["id"],
        "full_legal_name": d["full_legal_name"],
        "date_of_birth": _ts(d["date_of_birth"]),
        "date_of_death": _ts(d.get("date_of_death")),
        "domicile_state_code": d["domicile_state_code"],
        "ssn_last4": d["ssn_last4"],
        "created_at": _ts(d["created_at"]),
        "updated_at": _ts(d["updated_at"]),
        "version": d["version"],
    }


def view_estate(e: dict) -> dict:
    return {
        "id": e["id"],
        "decedent_id": e["decedent_id"],
        "status": e["status"],
        "gross_estate_value_cents": e["gross_estate_value_cents"],
        "net_taxable_estate_cents": e["net_taxable_estate_cents"],
        "inventory_snapshot_gross_cents": e.get("inventory_snapshot_gross_cents"),
        "executor_user_id": e.get("executor_user_id"),
        "probate_filed_at": _ts(e.get("probate_filed_at")),
        "probate_opened_at": _ts(e.get("probate_opened_at")),
        "closed_at": _ts(e.get("closed_at")),
        "created_at": _ts(e["created_at"]),
        "updated_at": _ts(e["updated_at"]),
        "version": e["version"],
    }


def view_asset(a: dict) -> dict:
    return {
        "id": a["id"],
        "estate_id": a["estate_id"],
        "category": a["category"],
        "description": a["description"],
        "appraised_value_cents": a["appraised_value_cents"],
        "status": a["status"],
        "beneficiary_designation_id": a.get("beneficiary_designation_id"),
        "created_at": _ts(a["created_at"]),
        "updated_at": _ts(a["updated_at"]),
        "version": a["version"],
    }


def view_designation(b: dict) -> dict:
    return {
        "id": b["id"],
        "estate_id": b["estate_id"],
        "beneficiary_full_name": b["beneficiary_full_name"],
        "relationship": b["relationship"],
        "share_basis_points": b["share_basis_points"],
        "status": b["status"],
        "contingent_of_designation_id": b.get("contingent_of_designation_id"),
        "created_at": _ts(b["created_at"]),
        "updated_at": _ts(b["updated_at"]),
        "version": b["version"],
    }


def view_executor(x: dict) -> dict:
    return {
        "id": x["id"],
        "estate_id": x["estate_id"],
        "full_legal_name": x["full_legal_name"],
        "role_type": x["role_type"],
        "status": x["status"],
        "is_also_beneficiary": x["is_also_beneficiary"],
        "created_at": _ts(x["created_at"]),
        "updated_at": _ts(x["updated_at"]),
        "version": x["version"],
    }


def view_poa(p: dict) -> dict:
    return {
        "id": p["id"],
        "decedent_id": p["decedent_id"],
        "agent_full_name": p["agent_full_name"],
        "scope": p["scope"],
        "status": p["status"],
        "effective_at": _ts(p.get("effective_at")),
        "effective_until": _ts(p.get("effective_until")),
        "created_at": _ts(p["created_at"]),
        "updated_at": _ts(p["updated_at"]),
        "version": p["version"],
    }


def view_directive(d: dict) -> dict:
    return {
        "id": d["id"],
        "decedent_id": d["decedent_id"],
        "directive_type": d["directive_type"],
        "status": d["status"],
        "physician_attester_user_id": d.get("physician_attester_user_id"),
        "hipaa_authorized_recipients": list(d.get("hipaa_authorized_recipients") or []),
        "created_at": _ts(d["created_at"]),
        "updated_at": _ts(d["updated_at"]),
        "version": d["version"],
    }


def view_guardianship(g: dict) -> dict:
    return {
        "id": g["id"],
        "estate_id": g["estate_id"],
        "ward_full_name": g["ward_full_name"],
        "ward_date_of_birth": _ts(g["ward_date_of_birth"]),
        "guardian_full_name": g["guardian_full_name"],
        "status": g["status"],
        "created_at": _ts(g["created_at"]),
        "updated_at": _ts(g["updated_at"]),
        "version": g["version"],
    }


def view_claim(c: dict) -> dict:
    return {
        "id": c["id"],
        "estate_id": c["estate_id"],
        "creditor_name": c["creditor_name"],
        "amount_cents": c["amount_cents"],
        "claim_class": c["claim_class"],
        "filed_at": _ts(c["filed_at"]),
        "paid_amount_cents": c["paid_amount_cents"],
        "status": c["status"],
        "created_at": _ts(c["created_at"]),
        "updated_at": _ts(c["updated_at"]),
        "version": c["version"],
    }


def view_order(o: dict) -> dict:
    return {
        "id": o["id"],
        "estate_id": o["estate_id"],
        "order_type": o["order_type"],
        "judge_user_id": o["judge_user_id"],
        "status": o["status"],
        "entered_at": _ts(o.get("entered_at")),
        "created_at": _ts(o["created_at"]),
        "updated_at": _ts(o["updated_at"]),
        "version": o["version"],
    }
