"""Warranty / recall claims (PRD 3.12)."""

from flask import Blueprint, request

import errors
import calculations as calc
from common import get_body, stamp_new, serialize, touch, paginate, as_str, as_enum
from db import db
from lookups import get_warranty_claim, get_unit, get_repair_order
from middleware import get_user_context, require_role
from response import ok, ok_list

bp = Blueprint("warranty", __name__)

KINDS = {"WARRANTY", "RECALL"}


@bp.route("/warranty-claims", methods=["POST"])
def create_claim():
    _, role = get_user_context()
    require_role(role, {"ServiceAdvisor", "DealerPrincipal"})
    body = get_body()
    # existence in declared order: unit_id, then optional repair_order_id
    unit_id = as_str(body, "unit_id")
    get_unit(unit_id)
    repair_order_id = body.get("repair_order_id")
    if repair_order_id is not None:
        if not isinstance(repair_order_id, str):
            errors.err(errors.ERR_INVALID_REQUEST, "repair_order_id must be a string")
        get_repair_order(repair_order_id)
    kind = as_enum(body, "kind", KINDS)

    rec = stamp_new({
        "unit_id": unit_id,
        "repair_order_id": repair_order_id,
        "kind": kind,
        "claim_amount_cents": 0,
        "status": "SUBMITTED",
    })
    rec["claim_amount_cents"] = calc.warranty_claim_amount(rec)
    db.warranty_claims[rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.route("/warranty-claims", methods=["GET"])
def list_claims():
    _, role = get_user_context()
    require_role(role, {"ServiceAdvisor", "DealerPrincipal"})
    f = request.args
    records = []
    for c in db.warranty_claims.values():
        if f.get("unit_id") is not None and c["unit_id"] != f.get("unit_id"):
            continue
        if f.get("repair_order_id") is not None and c.get("repair_order_id") != f.get("repair_order_id"):
            continue
        if f.get("status") is not None and c["status"] != f.get("status"):
            continue
        records.append(c)
    items, limit, offset, total = paginate(records)
    return ok_list(items, limit, offset, total)


@bp.route("/warranty-claims/<wid>", methods=["GET"])
def get_claim_route(wid):
    _, role = get_user_context()
    require_role(role, {"ServiceAdvisor", "DealerPrincipal"})
    rec = get_warranty_claim(wid)
    return ok(serialize(rec), 200)


@bp.route("/warranty-claims/<wid>/approve", methods=["POST"])
def approve_claim(wid):
    _, role = get_user_context()
    require_role(role, {"DealerPrincipal"})
    claim = get_warranty_claim(wid)
    if claim["status"] != "SUBMITTED":
        errors.err(errors.ERR_INVALID_STATE, "Claim is not SUBMITTED")
    # cross-entity: unit DELIVERED
    unit = db.units.get(claim["unit_id"])
    if unit is None or unit["status"] != "DELIVERED":
        errors.err(errors.ERR_UNIT_NOT_DELIVERED, "Unit is not DELIVERED")
    claim["claim_amount_cents"] = calc.warranty_claim_amount(claim)
    claim["status"] = "APPROVED"
    touch(claim)
    return ok(serialize(claim), 200)


@bp.route("/warranty-claims/<wid>/reject", methods=["POST"])
def reject_claim(wid):
    _, role = get_user_context()
    require_role(role, {"DealerPrincipal"})
    claim = get_warranty_claim(wid)
    if claim["status"] != "SUBMITTED":
        errors.err(errors.ERR_INVALID_STATE, "Claim is not SUBMITTED")
    claim["status"] = "REJECTED"
    touch(claim)
    return ok(serialize(claim), 200)


@bp.route("/warranty-claims/<wid>/pay", methods=["POST"])
def pay_claim(wid):
    _, role = get_user_context()
    require_role(role, {"DealerPrincipal"})
    claim = get_warranty_claim(wid)
    if claim["status"] != "APPROVED":
        errors.err(errors.ERR_INVALID_STATE, "Claim is not APPROVED")
    claim["status"] = "PAID"
    touch(claim)
    # settle the linked warranty RO if WORK_COMPLETE + UNBILLED
    ro_id = claim.get("repair_order_id")
    if ro_id:
        ro = db.repair_orders.get(ro_id)
        if ro is not None and ro["billing_status"] == "UNBILLED" and ro["work_status"] == "WORK_COMPLETE":
            ro["billing_status"] = "PAID"
            touch(ro)
    return ok(serialize(claim), 200)
