"""Pediatrician referrals (PRD §3.11)."""
from flask import Blueprint, request

import db
from errors import err, ERR_CONSULT_NOT_COMPLETED, ERR_REFERRAL_NOT_OPEN
from middleware import get_auth, require_roles
from response import object_response, array_response
from services.common import (
    init_full, touch, serialize, get_body,
    require_str, require_enum, paginate,
)
from services.lookups import get_or_404, get_fk_or_404

bp = Blueprint("referrals", __name__)

REASONS = {"WEIGHT_CONCERN", "TONGUE_TIE", "JAUNDICE", "OTHER"}
READ_ROLES = {"PracticeAdmin", "BillingSpecialist", "Consultant", "Client"}


@bp.post("/pediatrician-referrals")
def create_referral():
    # PRD §3.11 / §4: Consultant only.
    _, role = get_auth()
    require_roles(role, {"Consultant"})
    body = get_body()
    consult_id = require_str(body, "consult_id")
    # FK existence.
    consult = get_fk_or_404(db.consults, consult_id)
    # Well-formedness.
    reason = require_enum(body, "reason", REASONS)
    pediatrician_name = require_str(body, "pediatrician_name")
    # Parent consult must be COMPLETED (PRD §3.11).
    if consult["status"] != "COMPLETED":
        raise err(ERR_CONSULT_NOT_COMPLETED, "Parent consult is not COMPLETED")

    record = {
        "consult_id": consult_id,
        "client_id": consult["client_id"],  # copied from consult
        "reason": reason,
        "pediatrician_name": pediatrician_name,
        "status": "OPEN",
    }
    init_full(record)
    db.pediatrician_referrals[record["id"]] = record
    return object_response(serialize(record), 201)


@bp.get("/pediatrician-referrals/<rid>")
def get_referral(rid):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    record = get_or_404(db.pediatrician_referrals, rid)
    return object_response(serialize(record), 200)


@bp.get("/pediatrician-referrals")
def list_referrals():
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    consult_id = request.args.get("consult_id")
    client_id = request.args.get("client_id")
    records = []
    for r in db.pediatrician_referrals.values():
        if consult_id is not None and r["consult_id"] != consult_id:
            continue
        if client_id is not None and r["client_id"] != client_id:
            continue
        records.append(r)
    items, limit, offset, total = paginate(records)
    return array_response(items, limit, offset, total, 200)


@bp.post("/pediatrician-referrals/<rid>/acknowledge")
def acknowledge_referral(rid):
    _, role = get_auth()
    require_roles(role, {"Consultant"})
    ref = get_or_404(db.pediatrician_referrals, rid)
    if ref["status"] != "OPEN":
        raise err(ERR_REFERRAL_NOT_OPEN, "Referral is not OPEN")
    ref["status"] = "ACKNOWLEDGED"
    touch(ref)
    return object_response(serialize(ref), 200)


@bp.post("/pediatrician-referrals/<rid>/cancel")
def cancel_referral(rid):
    _, role = get_auth()
    require_roles(role, {"Consultant"})
    ref = get_or_404(db.pediatrician_referrals, rid)
    if ref["status"] != "OPEN":
        raise err(ERR_REFERRAL_NOT_OPEN, "Referral is not OPEN")
    ref["status"] = "CANCELLED"
    touch(ref)
    return object_response(serialize(ref), 200)
