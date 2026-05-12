"""Supplier endpoints (PRD §3.1)."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from db import db, parse_iso, stamp_create, stamp_update, serialize, serialize_list, order_by_created_then_seq
from errors import err
from middleware import enforce_role, require_roles
from pagination import paginate, parse_limit_offset
from response import success_array, success_object
from services.lookups import find_supplier
from validate import get_json_body, require_fields, require_list, require_string

bp = Blueprint("suppliers", __name__)


@bp.post("/suppliers")
@require_roles("Buyer")
def register_supplier():
    body = get_json_body()
    require_fields(body, [
        "legal_name", "tax_id", "qualification_categories",
        "qualification_expires_at", "bank_account_id",
    ])
    legal_name = require_string(body["legal_name"], "legal_name")
    tax_id = require_string(body["tax_id"], "tax_id")
    if any(s.get("legal_name") == legal_name for s in db.suppliers.values()):
        raise err("ERR_VALIDATION", "legal_name already exists.")
    if any(s.get("tax_id") == tax_id for s in db.suppliers.values()):
        raise err("ERR_VALIDATION", "tax_id already exists.")
    cats = require_list(body["qualification_categories"], "qualification_categories", allow_empty=False)
    for c in cats:
        if not isinstance(c, str) or not c:
            raise err("ERR_VALIDATION", "qualification_categories items must be non-empty strings.")
    qexp = require_string(body["qualification_expires_at"], "qualification_expires_at")
    try:
        parse_iso(qexp)
    except Exception:
        raise err("ERR_VALIDATION", "qualification_expires_at must be ISO 8601.")
    bank = require_string(body["bank_account_id"], "bank_account_id")

    row = {
        "legal_name": legal_name,
        "tax_id": tax_id,
        "qualification_status": "PROVISIONAL",
        "qualification_categories": list(cats),
        "qualification_expires_at": qexp,
        "bank_account_id": bank,
        "rating_avg": 0,
    }
    stamp_create(row, common=True)
    db.suppliers[row["id"]] = row
    return jsonify(success_object(serialize(row))), 201


@bp.post("/suppliers/<rid>/qualify")
@require_roles("LegalApprover")
def qualify_supplier(rid: str):
    row = find_supplier(rid)
    enforce_role()
    if row.get("qualification_status") not in ("PROVISIONAL",):
        raise err("ERR_INVALID_STATE", "Supplier is not in PROVISIONAL status.")
    row["qualification_status"] = "QUALIFIED"
    stamp_update(row)
    return jsonify(success_object(serialize(row))), 200


@bp.get("/suppliers/<rid>")
@require_roles("Buyer", "FinanceApprover", "LegalApprover", "GeneralManager")
def get_supplier(rid: str):
    row = find_supplier(rid)
    enforce_role()
    return jsonify(success_object(serialize(row))), 200


@bp.get("/suppliers")
@require_roles("Buyer", "FinanceApprover", "LegalApprover")
def list_suppliers():
    limit, offset = parse_limit_offset()
    qs = request.args.get("qualification_status")
    cat = request.args.get("category")
    rows = list(db.suppliers.values())
    if qs is not None:
        rows = [r for r in rows if r.get("qualification_status") == qs]
    if cat is not None:
        rows = [r for r in rows if cat in (r.get("qualification_categories") or [])]
    rows = order_by_created_then_seq(rows)
    page, total = paginate(rows, limit, offset)
    return jsonify(success_array(serialize_list(page), limit, offset, total)), 200
