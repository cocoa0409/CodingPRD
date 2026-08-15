"""Substitution proposal endpoints."""
from flask import Blueprint, request

import clock
import db
import services as svc
from errors import (
    ApiError, ERR_INVALID_STATE, ERR_INSUFFICIENT_STOCK, ERR_VALIDATION,
    not_found, forbidden,
)
from middleware import require_roles, check_facility_ownership
from response import success_object, success_list

bp = Blueprint("substitution_proposals", __name__)

READ_ROLES = ("DistributorAdmin", "FacilityManager")


def _pagination():
    try:
        limit = int(request.args.get("limit", "10"))
        offset = int(request.args.get("offset", "0"))
    except ValueError:
        raise ApiError(ERR_VALIDATION, "limit/offset must be integers", 400)
    if limit < 1 or limit > 100 or offset < 0:
        raise ApiError(ERR_VALIDATION, "limit must be 1..100, offset >= 0", 400)
    return limit, offset


def get_proposal_or_404(proposal_id):
    p = db.substitution_proposals.get(proposal_id)
    if p is None:
        raise not_found("Substitution proposal not found")
    return p


def _proposal_facility_id(prop):
    line = db.order_lines.get(prop["order_line_id"])
    if line is None:
        return None
    order = db.orders.get(line["order_id"])
    if order is None:
        return None
    return order["facility_id"]


@bp.get("/jansan/substitution-proposals/<proposal_id>")
def get_proposal(proposal_id):
    user_id, role = require_roles(*READ_ROLES)
    p = get_proposal_or_404(proposal_id)
    fid = _proposal_facility_id(p)
    if fid is not None:
        check_facility_ownership(user_id, role, fid)
    return success_object(dict(p))


@bp.get("/jansan/substitution-proposals")
def list_proposals():
    user_id, role = require_roles(*READ_ROLES)
    order_line_id = request.args.get("order_line_id")
    original_product_id = request.args.get("original_product_id")
    proposed_product_id = request.args.get("proposed_product_id")
    status = request.args.get("status")
    limit, offset = _pagination()
    items = list(db.substitution_proposals.values())
    if role == "FacilityManager":
        items = [p for p in items if _proposal_facility_id(p) == user_id]
    if order_line_id:
        items = [p for p in items if p["order_line_id"] == order_line_id]
    if original_product_id:
        items = [p for p in items if p["original_product_id"] == original_product_id]
    if proposed_product_id:
        items = [p for p in items if p["proposed_product_id"] == proposed_product_id]
    if status:
        items = [p for p in items if p["status"] == status]
    items.sort(key=lambda p: clock.parse_iso(p["created_at"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([dict(p) for p in page], limit, offset, total)


@bp.post("/jansan/substitution-proposals/<proposal_id>/accept")
def accept_proposal(proposal_id):
    user_id, role = require_roles("FacilityManager")
    prop = get_proposal_or_404(proposal_id)
    fid = _proposal_facility_id(prop)
    if fid is not None:
        check_facility_ownership(user_id, role, fid)
    # state (priority 7)
    if prop["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, "Proposal is not PENDING", 409)
    line = db.order_lines.get(prop["order_line_id"])
    if line is None or line["status"] != "SUBSTITUTION_PENDING":
        raise ApiError(ERR_INVALID_STATE, "Order line is not SUBSTITUTION_PENDING", 409)
    proposed = db.products.get(prop["proposed_product_id"])
    if proposed is None:
        raise not_found("Proposed product not found")
    # stock sufficiency (priority 10)
    if proposed["qty_on_hand"] < line["qty"]:
        raise ApiError(ERR_INSUFFICIENT_STOCK, "Insufficient stock for proposed product", 409)
    order = db.orders.get(line["order_id"])
    facility = db.facilities.get(order["facility_id"]) if order else None

    # swap + reprice + allocate
    old_price = line["unit_price_cents"]
    new_price = svc.effective_unit_price(facility, proposed, clock.now()) if facility else proposed["base_price_cents"]
    line["product_id"] = proposed["id"]
    line["unit_price_cents"] = new_price
    line["line_total_cents"] = svc.compute_line_total(line)
    line["status"] = "ALLOCATED"
    proposed["qty_on_hand"] -= line["qty"]
    proposed["qty_allocated"] += line["qty"]
    svc.touch(line)
    prop["price_delta_cents"] = (new_price - old_price) * line["qty"]
    prop["status"] = "ACCEPTED"
    svc.touch(prop)
    if order:
        svc.auto_transition_order(order)
    return success_object(dict(prop))


@bp.post("/jansan/substitution-proposals/<proposal_id>/decline")
def decline_proposal(proposal_id):
    user_id, role = require_roles("FacilityManager")
    prop = get_proposal_or_404(proposal_id)
    fid = _proposal_facility_id(prop)
    if fid is not None:
        check_facility_ownership(user_id, role, fid)
    if prop["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, "Proposal is not PENDING", 409)
    line = db.order_lines.get(prop["order_line_id"])
    order = db.orders.get(line["order_id"]) if line else None
    if line is not None and line["status"] == "SUBSTITUTION_PENDING":
        line["status"] = "CANCELLED"
        svc.touch(line)
    prop["status"] = "DECLINED"
    svc.touch(prop)
    if order:
        svc.auto_transition_order(order)
    return success_object(dict(prop))
