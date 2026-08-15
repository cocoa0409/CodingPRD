"""Repair orders and milestones (incl. the DELAY_REPORTED three-hop cascade)."""
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import api_error, bad_request
from middleware import ALL_ROLES, require_roles
from response import ok, paginate
from services import (bump, check_body_fk, create_communication_log, get_claim,
                      new_entity, need_date, need_enum, need_int, opt_str,
                      require_claim_open, sorted_by_creation, view)
from util import RETURN_GRACE_DAYS

bp = Blueprint("repair", __name__)


def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def get_order(order_id):
    o = db.repair_orders.get(order_id)
    if o is None:
        raise api_error("ERR_REPAIR_ORDER_NOT_FOUND", 404,
                        "repair order not found: %s" % order_id)
    return o


@bp.post("/repair-orders")
def create_repair_order():
    caller = require_roles(["RepairShop"])
    b = body()
    # rung 4: body FK existence
    check_body_fk(b, "claim_id", db.claims, "ERR_CLAIM_NOT_FOUND")
    # shape
    claim_id = b.get("claim_id")
    if not isinstance(claim_id, str) or not claim_id:
        raise bad_request("claim_id is required")
    estimated_completion = need_date(b, "estimated_completion_date")
    labor_hours = need_int(b, "labor_hours_estimate")
    if labor_hours <= 0:
        raise bad_request("labor_hours_estimate must be greater than zero")
    claim = get_claim(claim_id)
    # rung 6
    require_claim_open(claim)
    e = new_entity()
    e.update({
        "claim_id": claim_id,
        "shop_id": caller.id,  # recorded from X-User-ID, never from the payload
        "estimated_completion_date": estimated_completion,
        "actual_completion_date": None,
        "labor_hours_estimate": labor_hours,
        "status": "ESTIMATE_SUBMITTED",
    })
    db.repair_orders[e["id"]] = e
    return ok(view(e), status=201)


@bp.get("/repair-orders")
def list_repair_orders():
    require_roles(ALL_ROLES)
    items = list(db.repair_orders.values())
    shop_filter = request.args.get("shop_id")
    if shop_filter is not None:
        items = [o for o in items if o["shop_id"] == shop_filter]
    page, meta = paginate(sorted_by_creation(items), request.args)
    return ok([view(o) for o in page], response_type="array", pagination=meta)


@bp.get("/repair-orders/<oid>")
def get_repair_order(oid):
    require_roles(ALL_ROLES)
    return ok(view(get_order(oid)))


@bp.post("/repair-orders/<oid>/approve")
def approve_repair_order(oid):
    require_roles(["ClaimsAdjuster"])
    order = get_order(oid)
    claim = get_claim(order["claim_id"])
    require_claim_open(claim)
    if order["status"] != "ESTIMATE_SUBMITTED":
        raise api_error("ERR_REPAIR_ORDER_INVALID_STATE", 409,
                        "repair order is not ESTIMATE_SUBMITTED")
    order["status"] = "APPROVED"
    bump(order)
    return ok(view(order))


@bp.post("/repair-orders/<oid>/start")
def start_repair_order(oid):
    caller = require_roles(["RepairShop"])
    order = get_order(oid)
    # rung 5: entity-backed ownership
    if order["shop_id"] != caller.id:
        raise api_error("ERR_NOT_RESOURCE_OWNER", 403, "caller shop does not own this order")
    claim = get_claim(order["claim_id"])
    require_claim_open(claim)
    if order["status"] != "APPROVED":
        raise api_error("ERR_REPAIR_ORDER_INVALID_STATE", 409,
                        "repair order is not APPROVED")
    order["status"] = "IN_PROGRESS"
    bump(order)
    return ok(view(order))


@bp.post("/repair-orders/<oid>/complete")
def complete_repair_order(oid):
    caller = require_roles(["RepairShop"])
    order = get_order(oid)
    if order["shop_id"] != caller.id:
        raise api_error("ERR_NOT_RESOURCE_OWNER", 403, "caller shop does not own this order")
    claim = get_claim(order["claim_id"])
    require_claim_open(claim)
    if order["status"] != "IN_PROGRESS":
        raise api_error("ERR_REPAIR_ORDER_INVALID_STATE", 409,
                        "repair order is not IN_PROGRESS")
    order["status"] = "COMPLETED"
    order["actual_completion_date"] = db.clock_date()
    bump(order)
    # Refresh the overstay projection for live reservations on this order;
    # no recovery case is opened until the vehicle is actually returned.
    grace_end = order["actual_completion_date"] + timedelta(days=RETURN_GRACE_DAYS)
    for r in db.reservations.values():
        if r["repair_order_id"] == order["id"] and r["status"] in ("ACTIVE", "EXTENSION_REVIEW"):
            r["unnecessary_days"] = max(0, (r["authorized_return_date"] - grace_end).days)
            bump(r)
    return ok(view(order))


@bp.post("/repair-orders/<oid>/milestones")
def create_milestone(oid):
    caller = require_roles(["RepairShop"])
    order = get_order(oid)
    b = body()
    # shape
    milestone_type = need_enum(b, "milestone_type",
                               ("REPAIR_STARTED", "PARTS_DELAYED", "DELAY_REPORTED", "REPAIR_COMPLETED"))
    new_estimated = None
    if milestone_type == "DELAY_REPORTED":
        if b.get("new_estimated_completion_date") is None:
            raise bad_request("DELAY_REPORTED requires new_estimated_completion_date")
        new_estimated = need_date(b, "new_estimated_completion_date")
    elif b.get("new_estimated_completion_date") is not None:
        new_estimated = need_date(b, "new_estimated_completion_date")
    note = opt_str(b, "note")
    # rung 5: ownership
    if order["shop_id"] != caller.id:
        raise api_error("ERR_NOT_RESOURCE_OWNER", 403, "caller shop does not own this order")
    claim = get_claim(order["claim_id"])
    # rung 6
    require_claim_open(claim)
    # rung 8
    if order["status"] != "IN_PROGRESS":
        raise api_error("ERR_REPAIR_ORDER_INVALID_STATE", 409,
                        "milestones may only be reported on an IN_PROGRESS order")
    # rung 10: delay must move the estimate strictly later
    if milestone_type == "DELAY_REPORTED" and new_estimated <= order["estimated_completion_date"]:
        raise api_error("ERR_INVALID_DELAY", 400,
                        "new_estimated_completion_date must be strictly later than the current estimate")
    e = new_entity(common_fields=False)
    e.update({
        "repair_order_id": order["id"],
        "milestone_type": milestone_type,
        "reported_at": db.clock_now(),
        "new_estimated_completion_date": new_estimated,
        "note": note,
    })
    db.milestones[e["id"]] = e
    if milestone_type == "DELAY_REPORTED":
        # hop 1: advance the order's estimate
        order["estimated_completion_date"] = new_estimated
        bump(order)
        # hop 2: the ACTIVE reservation on this order goes into EXTENSION_REVIEW
        for r in db.reservations.values():
            if r["repair_order_id"] == order["id"] and r["status"] == "ACTIVE":
                r["status"] = "EXTENSION_REVIEW"
                bump(r)
        # hop 3: auto-created customer communication on the claim
        create_communication_log(order["claim_id"], "EMAIL", "EXPECTATION_SET",
                                 "Repair timeline slipped; rental expectations updated.")
        bump(claim)
    return ok(view(e), status=201)


@bp.get("/repair-orders/<oid>/milestones")
def list_milestones(oid):
    require_roles(ALL_ROLES)
    get_order(oid)
    items = [m for m in db.milestones.values() if m["repair_order_id"] == oid]
    page, meta = paginate(sorted_by_creation(items), request.args)
    return ok([view(m) for m in page], response_type="array", pagination=meta)
