"""WorkOrder routes + nested TreeAsset routes, plus assess/complete/cancel."""
from flask import Blueprint, request

import calculations
import db
import errors
import lookups
import response
from errors import ApiError
from helpers import (as_bool, as_number, as_string, get_json_body, parse_pagination)
from middleware import ALL_ROLES, require_roles
from services import (compute_tree_hazard, recompute_work_order_hazard,
                      trees_of_wo)

bp = Blueprint("work_orders", __name__)

TERMINAL_WO = ("COMPLETED", "CANCELLED")


# ---------------------------------------------------------------------------
# WorkOrder CRUD
# ---------------------------------------------------------------------------
@bp.post("/work-orders")
@require_roles("Dispatcher", "Client")
def create_work_order():
    body = get_json_body()
    service_area_id = as_string(body, "service_area_id")
    lookups.get_service_area(service_area_id)
    client_user_id = as_string(body, "client_user_id")
    site_address = as_string(body, "site_address")
    if "pricing_mode" not in body or body["pricing_mode"] is None:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "Missing required field: pricing_mode.")
    pricing_mode = body["pricing_mode"]
    if pricing_mode not in ("PER_JOB", "HOURLY"):
        raise ApiError(errors.ERR_INVALID_ENUM, 400, f"Illegal pricing_mode: {pricing_mode!r}.")
    is_emergency = as_bool(body, "is_emergency", default=False)

    obj = db.stamp_new({
        "service_area_id": service_area_id,
        "client_user_id": client_user_id,
        "site_address": site_address,
        "pricing_mode": pricing_mode,
        "is_emergency": is_emergency,
        "hazard_level": "LOW",
        "requires_permit": False,
        "accepted_estimate_id": None,
        "labor_cost_accrued_cents": 0,
        "disposal_cost_accrued_cents": 0,
        "final_invoice_cents": 0,
        "status": "DRAFT",
    })
    db.work_orders[obj["id"]] = obj
    return response.success(db.public(obj), 201)


@bp.get("/work-orders")
@require_roles(*ALL_ROLES)
def list_work_orders():
    limit, offset = parse_pagination()
    items = db.sort_by_created(db.work_orders.values())
    sa = request.args.get("service_area_id")
    cu = request.args.get("client_user_id")
    ae = request.args.get("accepted_estimate_id")
    if sa is not None:
        items = [w for w in items if w["service_area_id"] == sa]
    if cu is not None:
        items = [w for w in items if w["client_user_id"] == cu]
    if ae is not None:
        items = [w for w in items if w["accepted_estimate_id"] == ae]
    total = len(items)
    page = [db.public(o) for o in items[offset:offset + limit]]
    return response.paginated(page, limit, offset, total)


@bp.get("/work-orders/<wid>")
@require_roles(*ALL_ROLES)
def get_work_order(wid):
    obj = lookups.get_work_order(wid)
    return response.success(db.public(obj), 200)


# ---------------------------------------------------------------------------
# WorkOrder transitions
# ---------------------------------------------------------------------------
@bp.post("/work-orders/<wid>/assess")
@require_roles("Arborist")
def assess(wid):
    wo = lookups.get_work_order(wid)
    if wo["status"] in TERMINAL_WO:
        raise ApiError(errors.ERR_WORK_ORDER_TERMINAL, 409, "Work order is terminal.")
    if wo["status"] != "DRAFT":
        raise ApiError(errors.ERR_INVALID_STATE_TRANSITION, 409,
                       "Assess only allowed from DRAFT.")
    if not trees_of_wo(wid):
        raise ApiError(errors.ERR_NO_TREES_ASSESSED, 409,
                       "Work order has no trees to assess.")
    recompute_work_order_hazard(wo)
    wo["status"] = "ASSESSED"
    db.touch(wo)
    return response.success(db.public(wo), 200)


@bp.post("/work-orders/<wid>/complete")
@require_roles("Dispatcher")
def complete(wid):
    wo = lookups.get_work_order(wid)
    if wo["status"] in TERMINAL_WO:
        raise ApiError(errors.ERR_WORK_ORDER_TERMINAL, 409, "Work order is terminal.")
    if wo["status"] != "SCHEDULED":
        raise ApiError(errors.ERR_INVALID_STATE_TRANSITION, 409,
                       "Complete only allowed from SCHEDULED.")
    # Open bookings / disposal guards.
    for b in db.bookings.values():
        if b["work_order_id"] == wid and b["status"] == "RESERVED":
            raise ApiError(errors.ERR_OPEN_BOOKINGS, 409,
                           "A reserved booking remains.")
    for t in db.disposal_tickets.values():
        if t["work_order_id"] == wid and t["status"] == "RECORDED":
            raise ApiError(errors.ERR_OPEN_DISPOSAL, 409,
                           "A recorded disposal ticket remains.")

    accepted_total = None
    if wo["accepted_estimate_id"]:
        est = db.estimates.get(wo["accepted_estimate_id"])
        if est:
            accepted_total = est["total_cents"]
    wo["final_invoice_cents"] = calculations.final_invoice(
        pricing_mode=wo["pricing_mode"],
        accepted_estimate_total=accepted_total,
        hazard_level=wo["hazard_level"],
        labor_cost_accrued_cents=wo["labor_cost_accrued_cents"],
        disposal_cost_accrued_cents=wo["disposal_cost_accrued_cents"],
    )
    wo["status"] = "COMPLETED"
    db.touch(wo)
    return response.success(db.public(wo), 200)


@bp.post("/work-orders/<wid>/cancel")
@require_roles("Dispatcher")
def cancel(wid):
    wo = lookups.get_work_order(wid)
    if wo["status"] in TERMINAL_WO:
        raise ApiError(errors.ERR_WORK_ORDER_TERMINAL, 409, "Work order is terminal.")

    # Cascade: release reserved bookings, void recorded tickets, supersede
    # DRAFT/ISSUED estimates. Each child gets its own touch (version + timestamp).
    for b in db.bookings.values():
        if b["work_order_id"] == wid and b["status"] == "RESERVED":
            b["status"] = "RELEASED"
            db.touch(b)
    for t in db.disposal_tickets.values():
        if t["work_order_id"] == wid and t["status"] == "RECORDED":
            t["status"] = "VOIDED"
            db.touch(t)
    for e in db.estimates.values():
        if e["work_order_id"] == wid and e["status"] in ("DRAFT", "ISSUED"):
            e["status"] = "SUPERSEDED"
            db.touch(e)

    wo["final_invoice_cents"] = 0
    wo["status"] = "CANCELLED"
    db.touch(wo)
    return response.success(db.public(wo), 200)


# ---------------------------------------------------------------------------
# TreeAsset (nested under work order)
# ---------------------------------------------------------------------------
@bp.post("/work-orders/<wid>/trees")
@require_roles("Arborist", "Dispatcher")
def add_tree(wid):
    wo = lookups.get_work_order(wid)
    body = get_json_body()
    species = as_string(body, "species")
    dbh = as_number(body, "dbh_inches")
    if dbh <= 0:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "dbh_inches must be > 0.")
    is_protected = as_bool(body, "is_protected", default=False)
    is_heritage = as_bool(body, "is_heritage", default=False)
    near_utility_line = as_bool(body, "near_utility_line", default=False)
    lean = as_number(body, "lean_degrees", required=False, default=0)
    if lean < 0:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "lean_degrees must be >= 0.")
    has_decay = as_bool(body, "has_visible_decay", default=False)

    # Trees may only be added while the work order is DRAFT.
    if wo["status"] in TERMINAL_WO:
        raise ApiError(errors.ERR_WORK_ORDER_TERMINAL, 409, "Work order is terminal.")
    if wo["status"] != "DRAFT":
        raise ApiError(errors.ERR_INVALID_STATE_TRANSITION, 409,
                       "Trees may only be added while the work order is DRAFT.")

    obj = db.stamp_new({
        "work_order_id": wid,
        "species": species,
        "dbh_inches": dbh,
        "is_protected": is_protected,
        "is_heritage": is_heritage,
        "near_utility_line": near_utility_line,
        "lean_degrees": lean,
        "has_visible_decay": has_decay,
        "hazard_score": 0,
        "hazard_tier": "LOW",
    })
    compute_tree_hazard(obj)  # per-tree score computed on add while DRAFT
    db.trees[obj["id"]] = obj
    return response.success(db.public(obj), 201)


@bp.get("/work-orders/<wid>/trees")
@require_roles(*ALL_ROLES)
def list_trees(wid):
    lookups.get_work_order(wid)
    limit, offset = parse_pagination()
    items = db.sort_by_created([t for t in db.trees.values() if t["work_order_id"] == wid])
    total = len(items)
    page = [db.public(o) for o in items[offset:offset + limit]]
    return response.paginated(page, limit, offset, total)


@bp.get("/work-orders/<wid>/trees/<tid>")
@require_roles(*ALL_ROLES)
def get_tree(wid, tid):
    lookups.get_work_order(wid)
    obj = lookups.get_tree_on_wo(wid, tid)
    return response.success(db.public(obj), 200)
