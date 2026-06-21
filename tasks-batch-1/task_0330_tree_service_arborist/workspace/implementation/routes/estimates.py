"""Estimate routes (nested under work order) + LineItem routes (flat) +
issue/accept/decline transitions."""
from flask import Blueprint, g, request

import calculations
import db
import errors
import lookups
import response
from errors import ApiError
from helpers import (as_number, as_string, get_json_body, parse_pagination)
from middleware import ALL_ROLES, require_roles
from services import line_items_of_estimate, recompute_estimate

bp = Blueprint("estimates", __name__)


# ---------------------------------------------------------------------------
# Estimate (nested under work order)
# ---------------------------------------------------------------------------
@bp.post("/work-orders/<wid>/estimates")
@require_roles("Arborist")
def create_estimate(wid):
    wo = lookups.get_work_order(wid)
    if wo["status"] in ("COMPLETED", "CANCELLED"):
        raise ApiError(errors.ERR_WORK_ORDER_TERMINAL, 409, "Work order is terminal.")
    # Estimate may be drafted while ASSESSED or QUOTED.
    if wo["status"] not in ("ASSESSED", "QUOTED"):
        raise ApiError(errors.ERR_INVALID_STATE_TRANSITION, 409,
                       "Estimate requires the work order to be ASSESSED or QUOTED.")
    obj = db.stamp_new({
        "work_order_id": wid,
        "pricing_mode": wo["pricing_mode"],
        "line_items_subtotal_cents": 0,
        "hazard_surcharge_cents": 0,
        "heritage_surcharge_cents": 0,
        "utility_surcharge_cents": 0,
        "emergency_multiplier_applied": False,
        "total_cents": 0,
        "status": "DRAFT",
    })
    db.estimates[obj["id"]] = obj
    return response.success(db.public(obj), 201)


@bp.get("/work-orders/<wid>/estimates")
@require_roles(*ALL_ROLES)
def list_estimates(wid):
    lookups.get_work_order(wid)
    limit, offset = parse_pagination()
    items = db.sort_by_created([e for e in db.estimates.values() if e["work_order_id"] == wid])
    total = len(items)
    page = [db.public(o) for o in items[offset:offset + limit]]
    return response.paginated(page, limit, offset, total)


@bp.get("/work-orders/<wid>/estimates/<eid>")
@require_roles(*ALL_ROLES)
def get_estimate(wid, eid):
    lookups.get_work_order(wid)
    obj = lookups.get_estimate_on_wo(wid, eid)
    return response.success(db.public(obj), 200)


@bp.post("/work-orders/<wid>/estimates/<eid>/issue")
@require_roles("Arborist")
def issue_estimate(wid, eid):
    wo = lookups.get_work_order(wid)
    est = lookups.get_estimate_on_wo(wid, eid)
    if est["status"] != "DRAFT":
        raise ApiError(errors.ERR_ESTIMATE_NOT_DRAFT, 409, "Estimate is not in DRAFT.")
    if not line_items_of_estimate(eid):
        raise ApiError(errors.ERR_ESTIMATE_EMPTY, 409, "Estimate has no line items.")

    recompute_estimate(est)
    est["status"] = "ISSUED"
    db.touch(est)

    # First issue advances ASSESSED -> QUOTED and bumps WorkOrder.version.
    if wo["status"] == "ASSESSED":
        wo["status"] = "QUOTED"
        db.touch(wo)
    return response.success(db.public(est), 200)


@bp.post("/work-orders/<wid>/estimates/<eid>/accept")
@require_roles("Client")
def accept_estimate(wid, eid):
    wo = lookups.get_work_order(wid)
    est = lookups.get_estimate_on_wo(wid, eid)

    # State legality first (priority 7): estimate must be ISSUED.
    if est["status"] != "ISSUED":
        raise ApiError(errors.ERR_ESTIMATE_NOT_ISSUED, 409, "Estimate is not in ISSUED.")

    # Permit gate (priority 10) BEFORE ownership (priority 11).
    if wo["requires_permit"]:
        has_approved = any(p for p in db.permits.values()
                           if p["work_order_id"] == wid and p["status"] == "APPROVED")
        if not has_approved:
            raise ApiError(errors.ERR_PERMIT_REQUIRED, 422,
                           "An approved permit is required before acceptance.")

    # Ownership (priority 11).
    if g.user_id != wo["client_user_id"]:
        raise ApiError(errors.ERR_NOT_RESOURCE_OWNER, 403,
                       "Acting client does not own this work order.")

    est["status"] = "ACCEPTED"
    db.touch(est)
    wo["accepted_estimate_id"] = est["id"]

    # Supersede sibling ISSUED estimates.
    for other in db.estimates.values():
        if other["id"] != eid and other["work_order_id"] == wid and other["status"] == "ISSUED":
            other["status"] = "SUPERSEDED"
            db.touch(other)

    wo["status"] = "SCHEDULED"
    db.touch(wo)
    return response.success(db.public(est), 200)


@bp.post("/work-orders/<wid>/estimates/<eid>/decline")
@require_roles("Client")
def decline_estimate(wid, eid):
    wo = lookups.get_work_order(wid)
    est = lookups.get_estimate_on_wo(wid, eid)

    if est["status"] != "ISSUED":
        raise ApiError(errors.ERR_ESTIMATE_NOT_ISSUED, 409, "Estimate is not in ISSUED.")
    if g.user_id != wo["client_user_id"]:
        raise ApiError(errors.ERR_NOT_RESOURCE_OWNER, 403,
                       "Acting client does not own this work order.")

    est["status"] = "DECLINED"
    db.touch(est)
    return response.success(db.public(est), 200)


# ---------------------------------------------------------------------------
# LineItem (flat collection, estimate_id in body)
# ---------------------------------------------------------------------------
@bp.post("/line-items")
@require_roles("Arborist")
def create_line_item():
    body = get_json_body()
    estimate_id = as_string(body, "estimate_id")
    est = lookups.get_estimate(estimate_id)  # FK existence (404)

    if "service_type" not in body or body["service_type"] is None:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "Missing required field: service_type.")
    service_type = body["service_type"]
    if service_type not in ("REMOVAL", "STUMP_GRINDING", "HAUL_OFF", "UTILITY_CLEARANCE"):
        raise ApiError(errors.ERR_INVALID_ENUM, 400, f"Illegal service_type: {service_type!r}.")

    quantity = as_number(body, "quantity")
    if quantity <= 0:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "quantity must be > 0.")

    tree_asset_id = body.get("tree_asset_id")
    tree = None
    if tree_asset_id is not None:
        if not isinstance(tree_asset_id, str):
            raise ApiError(errors.ERR_INVALID_REQUEST, 400, "tree_asset_id must be a string.")
        tree = lookups.get_tree(tree_asset_id)  # FK existence (404)

    # REMOVAL / STUMP_GRINDING require a tree reference.
    if service_type in ("REMOVAL", "STUMP_GRINDING") and tree is None:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400,
                       f"{service_type} requires tree_asset_id.")

    # State (priority 7): line items only on DRAFT estimates.
    if est["status"] != "DRAFT":
        raise ApiError(errors.ERR_ESTIMATE_NOT_DRAFT, 409, "Estimate is not in DRAFT.")

    unit_cost = calculations.line_item_unit_cost(
        service_type, tree["dbh_inches"] if tree else None)
    extended = calculations.line_item_extended_cost(unit_cost, quantity)

    obj = db.stamp_new({
        "estimate_id": estimate_id,
        "tree_asset_id": tree_asset_id,
        "service_type": service_type,
        "quantity": quantity,
        "unit_cost_cents": unit_cost,
        "extended_cost_cents": extended,
    })
    db.line_items[obj["id"]] = obj

    # Recompute parent estimate totals while DRAFT.
    recompute_estimate(est)
    return response.success(db.public(obj), 201)


@bp.get("/line-items")
@require_roles(*ALL_ROLES)
def list_line_items():
    limit, offset = parse_pagination()
    items = db.sort_by_created(db.line_items.values())
    eid = request.args.get("estimate_id")
    tid = request.args.get("tree_asset_id")
    if eid is not None:
        items = [li for li in items if li["estimate_id"] == eid]
    if tid is not None:
        items = [li for li in items if li["tree_asset_id"] == tid]
    total = len(items)
    page = [db.public(o) for o in items[offset:offset + limit]]
    return response.paginated(page, limit, offset, total)


@bp.get("/line-items/<lid>")
@require_roles(*ALL_ROLES)
def get_line_item(lid):
    obj = db.line_items.get(lid)
    if obj is None:
        raise ApiError(errors.ERR_ESTIMATE_NOT_FOUND, 404, "Line item not found.")
    return response.success(db.public(obj), 200)
