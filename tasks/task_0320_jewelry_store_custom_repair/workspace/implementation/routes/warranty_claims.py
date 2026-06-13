"""Warranty claims and the spawned repair (PRD §3.8)."""
from flask import Blueprint, request

import db
from errors import ApiError
from middleware import get_caller, require_role, parse_pagination, paginate
from response import success
from services import serialize
from services.common import get_body, require_str, resolve_fk, resolve_path, require_own_version
from routes.repair_tickets import create_repair_ticket_record

bp = Blueprint("warranty_claims", __name__)


def item_has_finalized_appraisal(item_id):
    for a in db.appraisals.values():
        if a["inventory_item_id"] == item_id and a["status"] == "FINALIZED":
            return True
    return False


@bp.route("/warranty-claims", methods=["POST"])
def create_warranty_claim():
    _, role = get_caller()
    require_role(role, {"SalesAssociate", "StoreManager", "Customer"})
    body = get_body()
    inventory_item_id = require_str(body, "inventory_item_id")
    resolve_fk(db.inventory_items, inventory_item_id)
    customer_id = require_str(body, "customer_id")
    resolve_fk(db.customers, customer_id)
    defect_description = require_str(body, "defect_description")
    rec = db.new_record()
    rec.update({
        "inventory_item_id": inventory_item_id, "customer_id": customer_id,
        "defect_description": defect_description, "spawned_repair_ticket_id": None,
        "status": "SUBMITTED",
    })
    db.warranty_claims[rec["id"]] = rec
    return success(serialize.warranty_claim(rec), status=201)


@bp.route("/warranty-claims", methods=["GET"])
def list_warranty_claims():
    _, role = get_caller()
    require_role(role, {"SalesAssociate", "StoreManager", "Customer"})
    limit, offset = parse_pagination()
    f_item = request.args.get("inventory_item_id")
    f_customer = request.args.get("customer_id")
    f_ticket = request.args.get("spawned_repair_ticket_id")
    records = []
    for c in db.warranty_claims.values():
        if f_item is not None and c["inventory_item_id"] != f_item:
            continue
        if f_customer is not None and c["customer_id"] != f_customer:
            continue
        if f_ticket is not None and c.get("spawned_repair_ticket_id") != f_ticket:
            continue
        records.append(c)
    page, meta = paginate(records, limit, offset)
    return success([serialize.warranty_claim(r) for r in page], status=200, pagination=meta)


@bp.route("/warranty-claims/<cid>", methods=["GET"])
def get_warranty_claim(cid):
    _, role = get_caller()
    require_role(role, {"SalesAssociate", "StoreManager", "Customer"})
    rec = resolve_path(db.warranty_claims, cid)
    return success(serialize.warranty_claim(rec), status=200)


@bp.route("/warranty-claims/<cid>/approve", methods=["POST"])
def approve_claim(cid):
    _, role = get_caller()
    require_role(role, {"StoreManager"})
    rec = resolve_path(db.warranty_claims, cid)
    body = get_body()
    if rec["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Claim is not SUBMITTED")
    # Coverage guard: item must have a FINALIZED appraisal.
    if not item_has_finalized_appraisal(rec["inventory_item_id"]):
        raise ApiError("ERR_NO_COVERAGE", "No finalized appraisal on the covered item")
    require_own_version(rec, body)
    # Spawn a WARRANTY repair ticket.
    ticket = create_repair_ticket_record(
        customer_id=rec["customer_id"], inventory_item_id=rec["inventory_item_id"],
        repair_kind="WARRANTY", rush=False, promised_at=None, warranty_claim_id=rec["id"],
        parts_cents=0, labor_cents=0,
    )
    rec["spawned_repair_ticket_id"] = ticket["id"]
    rec["status"] = "APPROVED"
    db.touch(rec)
    return success(serialize.warranty_claim(rec), status=200)


@bp.route("/warranty-claims/<cid>/reject", methods=["POST"])
def reject_claim(cid):
    _, role = get_caller()
    require_role(role, {"StoreManager"})
    rec = resolve_path(db.warranty_claims, cid)
    body = get_body()
    if rec["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Claim is not SUBMITTED")
    require_own_version(rec, body)
    rec["status"] = "REJECTED"
    db.touch(rec)
    return success(serialize.warranty_claim(rec), status=200)
