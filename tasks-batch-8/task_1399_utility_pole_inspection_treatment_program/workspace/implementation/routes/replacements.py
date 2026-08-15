from flask import Blueprint, request

import db
from calc import escalated_cost, priority_score
from errors import ApiError
from middleware import authenticate, require_role, locked
from response import ok, ok_list
from serializers import ser_replacement
from validators import (body, req_field, as_str, as_int, pagination,
                        apply_filters)

bp = Blueprint("replacements", __name__)


def _get_order(oid):
    o = db.replacements.get(oid)
    if o is None:
        raise ApiError("ERR_ORDER_NOT_FOUND", 404,
                       "replacement order id does not resolve")
    return o


@bp.post("/pole-program/replacement-work-orders")
@locked
def create_replacement():
    uid, role = authenticate()
    require_role(role, "ProgramManager")
    d = body()
    pole_id = as_str(req_field(d, "pole_id"), "pole_id")
    estimated = as_int(req_field(d, "estimated_cost_cents"),
                       "estimated_cost_cents", 1)
    pole = db.poles.get(pole_id)
    if pole is None:
        raise ApiError("ERR_POLE_NOT_FOUND", 404, "pole_id does not resolve")
    if pole["status"] == "REPLACED":
        raise ApiError("ERR_POLE_REPLACED", 409,
                       "Operation targets a pole whose status == REPLACED")
    rec = db.new_record()
    rec.update(pole_id=pole_id, cycle_id=None, budget_id=None,
               estimated_cost_cents=estimated, actual_cost_cents=None,
               deferral_count=0,
               escalated_cost_cents=escalated_cost(estimated, 0),
               priority_score=priority_score(pole, 0), status="QUEUED",
               funded_at=None)
    db.replacements[rec["id"]] = rec
    return ok(ser_replacement(rec), 201)


@bp.get("/pole-program/replacement-work-orders")
def list_replacements():
    authenticate()
    limit, offset = pagination()
    items = apply_filters(db.replacements.values(), [
        ("pole_id", request.args.get("pole_id")),
        ("budget_id", request.args.get("budget_id")),
        ("cycle_id", request.args.get("cycle_id")),
        ("status", request.args.get("status")),
    ])
    page = items[offset:offset + limit]
    return ok_list([ser_replacement(o) for o in page], len(items), limit, offset)


@bp.get("/pole-program/replacement-work-orders/<oid>")
def get_replacement(oid):
    authenticate()
    return ok(ser_replacement(_get_order(oid)), 200)


@bp.post("/pole-program/replacement-work-orders/<oid>/fund")
@locked
def fund_replacement(oid):
    uid, role = authenticate()
    require_role(role, "ProgramManager")
    d = body()
    budget_id = as_str(req_field(d, "budget_id"), "budget_id")
    expected = as_int(req_field(d, "expected_budget_version"),
                      "expected_budget_version")
    order = _get_order(oid)
    budget = db.budgets.get(budget_id)
    if budget is None:
        raise ApiError("ERR_BUDGET_NOT_FOUND", 404, "budget_id does not resolve")
    if order["status"] != "QUEUED":
        raise ApiError("ERR_ORDER_NOT_QUEUED", 409,
                       "fund requires order.status == QUEUED")
    if expected != budget["version"]:
        raise ApiError("ERR_STALE_BUDGET_VERSION", 412,
                       "expected_budget_version != ProgramBudget.version")
    available = (budget["total_cents"] - budget["committed_cents"]
                 - budget["spent_cents"])
    if order["escalated_cost_cents"] > available:
        raise ApiError("ERR_BUDGET_EXCEEDED", 422,
                       "escalated_cost_cents > budget.available_cents")
    order["status"] = "FUNDED"
    order["budget_id"] = budget["id"]
    order["funded_at"] = db.clock_now()
    budget["committed_cents"] += order["escalated_cost_cents"]
    db.touch(budget)
    db.touch(order)
    return ok(ser_replacement(order), 200)


@bp.post("/pole-program/replacement-work-orders/<oid>/defund")
@locked
def defund_replacement(oid):
    uid, role = authenticate()
    require_role(role, "ProgramManager")
    order = _get_order(oid)
    if order["status"] != "FUNDED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "defund requires order.status == FUNDED")
    budget = db.budgets.get(order["budget_id"])
    if budget is not None:
        budget["committed_cents"] -= order["escalated_cost_cents"]
        db.touch(budget)
    order["status"] = "QUEUED"
    order["budget_id"] = None
    order["funded_at"] = None
    db.touch(order)
    return ok(ser_replacement(order), 200)


@bp.post("/pole-program/replacement-work-orders/<oid>/defer")
@locked
def defer_replacement(oid):
    uid, role = authenticate()
    require_role(role, "ProgramManager")
    order = _get_order(oid)
    if order["status"] != "QUEUED":
        raise ApiError("ERR_ORDER_NOT_QUEUED", 409,
                       "defer requires order.status == QUEUED")
    order["deferral_count"] += 1
    order["escalated_cost_cents"] = escalated_cost(
        order["estimated_cost_cents"], order["deferral_count"])
    order["status"] = "DEFERRED"
    db.touch(order)
    return ok(ser_replacement(order), 200)


@bp.post("/pole-program/replacement-work-orders/<oid>/complete")
@locked
def complete_replacement(oid):
    uid, role = authenticate()
    require_role(role, "Contractor")
    d = body()
    actual = as_int(req_field(d, "actual_cost_cents"), "actual_cost_cents", 1)
    order = _get_order(oid)
    if order["status"] != "FUNDED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "complete requires order.status == FUNDED")
    budget = db.budgets.get(order["budget_id"])
    if budget is not None:
        budget["committed_cents"] -= order["escalated_cost_cents"]
        budget["spent_cents"] += actual
        db.touch(budget)
    order["actual_cost_cents"] = actual
    order["status"] = "COMPLETED"
    db.touch(order)
    pole = db.poles.get(order["pole_id"])
    if pole is not None:
        pole["status"] = "REPLACED"
        db.touch(pole)
    return ok(ser_replacement(order), 200)
