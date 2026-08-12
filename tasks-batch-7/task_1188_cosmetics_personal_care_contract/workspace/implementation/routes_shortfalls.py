"""ShortfallCase endpoints: get/list/commit/escalate."""
from flask import Blueprint, g, request

from core import (body, check_enum, err, get_required, list_page,
                  require_roles, success, touch)
from services import (D, cancel_order_cascade, fulfillable_units, must_get,
                      release_allocation, serialize_shortfall)
from store import db, parse_dt

bp = Blueprint("shortfalls", __name__)

SHORTFALL_ROLES = ("ProductionPlanner", "CustomerRep", "PlantDirector")


def check_shortfall_confidentiality(shortfall):
    if g.user_role == "CustomerRep":
        order = db.orders.get(shortfall["production_order_id"])
        if order is None or order["customer_id"] != g.user_id:
            err("ERR_CONFIDENTIALITY_VIOLATION", 403,
                "CustomerRep may only access their own orders' shortfalls")


@bp.get("/cosmfg/shortfalls/<sid>")
@require_roles(*SHORTFALL_ROLES)
def get_shortfall(sid):
    s = must_get(db.shortfalls, sid, "ShortfallCase")
    check_shortfall_confidentiality(s)
    return success(serialize_shortfall(s))


@bp.get("/cosmfg/shortfalls")
@require_roles(*SHORTFALL_ROLES)
def list_shortfalls():
    items = list(db.shortfalls.values())
    if g.user_role == "CustomerRep":
        items = [s for s in items
                 if (db.orders.get(s["production_order_id"]) or {}).get("customer_id")
                 == g.user_id]
    order_id = request.args.get("production_order_id")
    if order_id is not None:
        items = [s for s in items if s["production_order_id"] == order_id]
    component_id = request.args.get("component_id")
    if component_id is not None:
        items = [s for s in items if s["component_id"] == component_id]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return list_page(items, serialize_shortfall)


@bp.post("/cosmfg/shortfalls/<sid>/commit")
@require_roles("CustomerRep")
def commit_shortfall(sid):
    s = must_get(db.shortfalls, sid, "ShortfallCase")
    check_shortfall_confidentiality(s)
    if s["status"] != "OPEN":
        err("ERR_INVALID_STATE", 409, "Only an OPEN shortfall may be committed")
    b = body()
    committed = get_required(b, "committed_by_date")
    if parse_dt(committed) is None:
        err("ERR_VALIDATION", 400, "committed_by_date must be an ISO-8601 datetime")
    s["committed_by_date"] = committed
    s["status"] = "COMMITMENT_RECEIVED"
    touch(s)
    return success(serialize_shortfall(s))


@bp.post("/cosmfg/shortfalls/<sid>/escalate")
@require_roles("ProductionPlanner")
def escalate_shortfall(sid):
    s = must_get(db.shortfalls, sid, "ShortfallCase")
    if s["status"] not in ("OPEN", "COMMITMENT_RECEIVED"):
        err("ERR_INVALID_STATE", 409,
            "Only an OPEN or COMMITMENT_RECEIVED shortfall may be escalated")
    b = body()
    resolution = check_enum(get_required(b, "resolution"),
                            {"REDUCE_ORDER", "CANCEL_ORDER"}, "resolution")
    s["resolution"] = resolution
    s["status"] = "ESCALATED"
    touch(s)
    order = db.orders.get(s["production_order_id"])
    if order is not None and order["status"] not in ("COMPLETED", "CANCELLED"):
        if resolution == "CANCEL_ORDER":
            cancel_order_cascade(order)
        else:
            # REDUCE_ORDER: shrink to fulfillable_units_conservative and release
            # excess reservations newest-first per required component.
            cons, _opt = fulfillable_units(order)
            new_units = min(cons, order["requested_units"])
            delta = order["requested_units"] - new_units
            order["requested_units"] = new_units
            order["forfeited_units"] = order["forfeited_units"] + delta
            touch(order)
            formula = db.formulas.get(order["formula_id"])
            reqs = formula["required_components"] if formula else []
            for entry in reqs:
                comp = db.components.get(entry.get("component_id") or "")
                if comp is None:
                    continue
                cap = D(order["requested_units"]) * D(entry["units_per_product"])
                allocs = [a for a in db.allocations.values()
                          if a["production_order_id"] == order["id"]
                          and a["status"] == "RESERVED"
                          and (db.lots.get(a["lot_id"]) or {}).get("component_id")
                          == comp["id"]]
                # Newest-first: created_at DESC (sequence order descending)
                allocs.sort(key=lambda a: a["_seq"], reverse=True)
                reserved_total = sum((D(a["quantity"]) for a in allocs), D(0))
                for a in allocs:
                    if reserved_total <= cap:
                        break
                    release_allocation(a)
                    reserved_total -= D(a["quantity"])
    return success(serialize_shortfall(s))
