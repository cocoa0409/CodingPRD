"""EquipmentUnit endpoints and lifecycle (PRD §3.1, §3.7)."""
from flask import Blueprint, request

import db
from db import touch
from errors import err
from middleware import get_user_context, require_role
from response import object_response, array_response
from services.helpers import (get_json_body, lookup, require_fields,
                              require_int, require_enum, paginate,
                              sorted_by_created)
from services.serialize import public, public_list
from services.domain import recompute_credit_balance

bp = Blueprint("equipment", __name__)

KIND = {"MODEM", "ROUTER", "GATEWAY"}


@bp.route("/equipment-units", methods=["POST"])
def create_equipment_unit():
    _uid, role = get_user_context()
    require_role(role, {"ProvisioningAgent", "NetworkOps"})
    body = get_json_body()
    require_fields(body, ["kind", "serial", "lease_fee_cents_per_cycle"])
    kind = require_enum(body, "kind", KIND)
    if not isinstance(body["serial"], str) or body["serial"] == "":
        err("ERR_INVALID_REQUEST", "serial must be a non-empty string.")
    lease_fee = require_int(body, "lease_fee_cents_per_cycle")
    for u in db.equipment_units.values():
        if u["serial"] == body["serial"]:
            err("ERR_DUPLICATE_SERIAL", "EquipmentUnit serial already in use.")
    rec = db.make_record({
        "account_id": None,
        "kind": kind,
        "serial": body["serial"],
        "lease_fee_cents_per_cycle": lease_fee,
        "status": "IN_INVENTORY",
        "leased_at_iso": None,
    }, versioned=db.VERSIONED)
    db.equipment_units[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.route("/equipment-units/<rid>", methods=["GET"])
def get_equipment_unit(rid):
    _uid, role = get_user_context()
    require_role(role, {"Customer", "ProvisioningAgent", "NetworkOps"})
    rec = lookup(db.equipment_units, rid)
    return object_response(public(rec), 200)


@bp.route("/equipment-units", methods=["GET"])
def list_equipment_units():
    _uid, role = get_user_context()
    require_role(role, {"Customer", "ProvisioningAgent", "NetworkOps"})
    recs = list(db.equipment_units.values())
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    if account_id is not None:
        recs = [r for r in recs if r["account_id"] == account_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    recs = sorted_by_created(recs)
    window, limit, offset, total, has_more = paginate(recs)
    return array_response(public_list(window), limit, offset, total, has_more, 200)


@bp.route("/equipment-units/<rid>/confirm-return", methods=["POST"])
def confirm_return(rid):
    _uid, role = get_user_context()
    require_role(role, {"ProvisioningAgent"})
    get_json_body()
    rec = lookup(db.equipment_units, rid)
    if rec["status"] != "RETURN_PENDING":
        err("ERR_INVALID_STATE", "Unit must be RETURN_PENDING to confirm return.")
    rec["status"] = "RETURNED"
    rec["account_id"] = None
    touch(rec)
    return object_response(public(rec), 200)


@bp.route("/equipment-units/<rid>/restock", methods=["POST"])
def restock(rid):
    _uid, role = get_user_context()
    require_role(role, {"ProvisioningAgent"})
    get_json_body()
    rec = lookup(db.equipment_units, rid)
    if rec["status"] != "RETURNED":
        err("ERR_INVALID_STATE", "Unit must be RETURNED to restock.")
    rec["status"] = "IN_INVENTORY"
    rec["leased_at_iso"] = None
    touch(rec)
    return object_response(public(rec), 200)


@bp.route("/equipment-units/<rid>/mark-lost", methods=["POST"])
def mark_lost(rid):
    _uid, role = get_user_context()
    require_role(role, {"ProvisioningAgent"})
    get_json_body()
    rec = lookup(db.equipment_units, rid)
    if rec["status"] != "RETURN_PENDING":
        err("ERR_INVALID_STATE", "Unit must be RETURN_PENDING to mark lost.")
    # Reverse the LEASE_PRORATE credit for this unit (negate to net 0) (§3.7).
    affected_accounts = set()
    for c in db.account_credits.values():
        if c["source_type"] == "LEASE_PRORATE" and c["source_id"] == rec["id"]:
            c["amount_cents"] = 0
            affected_accounts.add(c["account_id"])
    rec["status"] = "LOST"
    touch(rec)
    for acct_id in affected_accounts:
        recompute_credit_balance(acct_id)
    return object_response(public(rec), 200)
