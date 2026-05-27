"""GarnishmentOrder + GarnishmentDeduction endpoints."""
from flask import Blueprint, request

import db
import response
from errors import (
    APIError,
    ERR_NOT_FOUND,
    ERR_FK_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_GARNISHMENT_EXCEEDS_CCPA,
    ERR_GARNISHMENT_AGGREGATE_CAP,
    ERR_INVALID_REQUEST,
)
from middleware import require_roles
from services import serialize, pagination, lookups
from services import validation as V
from services.calculations import (
    CCPA_MAX_BASIS_POINTS_WITH_CHILD_SUPPORT,
)


bp = Blueprint("garnishments", __name__)


PRIORITY_RANK_BY_TYPE = {
    "CHILD_SUPPORT": 1,
    "IRS_LEVY": 2,
    "STUDENT_LOAN": 3,
    "CREDITOR": 4,
}


@bp.post("/garnishment-orders")
@require_roles("ComplianceOfficer")
def create_order():
    body = V.require_dict(request.get_json(silent=True) or {})
    employee_id = V.require_str(body, "employee_id")
    order_type = V.require_enum(body, "order_type", V.GARNISHMENT_ORDER_TYPES)
    weekly_cap = V.require_int(body, "weekly_cap_cents")
    original_balance = V.require_int(body, "original_balance_cents")
    served_on = V.require_str(body, "served_on")

    if weekly_cap < 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "weekly_cap_cents must be non-negative")
    if original_balance < 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "original_balance_cents must be non-negative")

    # Priority 4 — FK existence
    employee = db.employees.get(employee_id)
    if employee is None:
        raise APIError(ERR_FK_NOT_FOUND, 404, "employee_id not found")

    # Priority 8 — single-order CCPA ceiling (CHILD_SUPPORT only)
    if order_type == "CHILD_SUPPORT":
        recent = lookups.most_recent_paid_paycheck_for(employee_id)
        if recent is not None:
            cap = (recent["gross_wages_cents"]
                   * CCPA_MAX_BASIS_POINTS_WITH_CHILD_SUPPORT) // 10000
            if weekly_cap > cap:
                raise APIError(ERR_GARNISHMENT_EXCEEDS_CCPA, 422,
                               "CHILD_SUPPORT weekly cap exceeds CCPA 50% of most recent PAID gross")

    # Priority 12 — aggregate-capacity check across ACTIVE orders for this employee
    recent = lookups.most_recent_paid_paycheck_for(employee_id)
    if recent is not None:
        # The aggregate cap is the CCPA-derived capacity. We compute it using the
        # 50% basis when this new order is CHILD_SUPPORT (or any active CHILD_SUPPORT
        # exists for the employee), otherwise 25%.
        any_cs = (order_type == "CHILD_SUPPORT"
                  or any(g["employee_id"] == employee_id
                         and g["status"] == "ACTIVE"
                         and g["order_type"] == "CHILD_SUPPORT"
                         for g in db.garnishment_orders.values()))
        bp_limit = 5000 if any_cs else 2500
        capacity = (recent["gross_wages_cents"] * bp_limit) // 10000
        active_sum = sum(
            g["weekly_cap_cents"] for g in db.garnishment_orders.values()
            if g["employee_id"] == employee_id and g["status"] == "ACTIVE"
        )
        if active_sum + weekly_cap > capacity:
            raise APIError(ERR_GARNISHMENT_AGGREGATE_CAP, 422,
                           "aggregate active weekly caps exceed CCPA capacity")

    g = {
        "id": db.new_id(),
        "employee_id": employee_id,
        "order_type": order_type,
        "priority_rank": PRIORITY_RANK_BY_TYPE[order_type],
        "weekly_cap_cents": weekly_cap,
        "original_balance_cents": original_balance,
        "balance_remaining_cents": original_balance,
        "status": "ACTIVE",
        "served_on": served_on,
    }
    db.stamp_common(g)
    db.garnishment_orders[g["id"]] = g
    return response.success_object(serialize.garnishment_order(g), status=201)


@bp.post("/garnishment-orders/<gid>/suspend")
@require_roles("ComplianceOfficer")
def suspend_order(gid):
    g = db.garnishment_orders.get(gid)
    if not g:
        raise APIError(ERR_NOT_FOUND, 404, "GarnishmentOrder not found")
    if g["status"] != "ACTIVE":
        raise APIError(ERR_INVALID_STATE, 409, "GarnishmentOrder is not ACTIVE")
    g["status"] = "SUSPENDED"
    db.bump(g)
    return response.success_object(serialize.garnishment_order(g))


@bp.post("/garnishment-orders/<gid>/reactivate")
@require_roles("ComplianceOfficer")
def reactivate_order(gid):
    g = db.garnishment_orders.get(gid)
    if not g:
        raise APIError(ERR_NOT_FOUND, 404, "GarnishmentOrder not found")
    if g["status"] != "SUSPENDED":
        raise APIError(ERR_INVALID_STATE, 409, "GarnishmentOrder is not SUSPENDED")
    g["status"] = "ACTIVE"
    db.bump(g)
    return response.success_object(serialize.garnishment_order(g))


@bp.post("/garnishment-orders/<gid>/release")
@require_roles("ComplianceOfficer")
def release_order(gid):
    g = db.garnishment_orders.get(gid)
    if not g:
        raise APIError(ERR_NOT_FOUND, 404, "GarnishmentOrder not found")
    if g["status"] not in ("ACTIVE", "SATISFIED", "SUSPENDED"):
        raise APIError(ERR_INVALID_STATE, 409, "GarnishmentOrder is in terminal state")
    g["status"] = "RELEASED"
    db.bump(g)
    return response.success_object(serialize.garnishment_order(g))


@bp.get("/garnishment-orders/<gid>")
@require_roles("PayrollPreparer", "PayrollApprover", "ComplianceOfficer", "PlatformAdmin", "HRClerk")
def get_order(gid):
    g = db.garnishment_orders.get(gid)
    if not g:
        raise APIError(ERR_NOT_FOUND, 404, "GarnishmentOrder not found")
    return response.success_object(serialize.garnishment_order(g))


@bp.get("/garnishment-orders")
@require_roles("PayrollPreparer", "PayrollApprover", "ComplianceOfficer", "PlatformAdmin", "HRClerk")
def list_orders():
    limit, offset = pagination.parse_limit_offset()
    employee_id = V.opt_str(request.args, "employee_id")
    status = V.opt_enum(request.args, "status", V.GARNISHMENT_ORDER_STATUSES)
    order_type = V.opt_enum(request.args, "order_type", V.GARNISHMENT_ORDER_TYPES)
    items = list(db.garnishment_orders.values())
    if employee_id:
        items = [g for g in items if g["employee_id"] == employee_id]
    if status:
        items = [g for g in items if g["status"] == status]
    if order_type:
        items = [g for g in items if g["order_type"] == order_type]
    page, total = pagination.slice_sorted(items, limit, offset)
    return response.success_array(
        [serialize.garnishment_order(x) for x in page],
        limit=limit, offset=offset, total_count=total,
    )


@bp.get("/garnishment-deductions/<did>")
@require_roles("PayrollPreparer", "PayrollApprover", "ComplianceOfficer", "PlatformAdmin", "HRClerk")
def get_deduction(did):
    d = db.garnishment_deductions.get(did)
    if not d:
        raise APIError(ERR_NOT_FOUND, 404, "GarnishmentDeduction not found")
    return response.success_object(serialize.garnishment_deduction(d))


@bp.get("/garnishment-deductions")
@require_roles("PayrollPreparer", "PayrollApprover", "ComplianceOfficer", "PlatformAdmin", "HRClerk")
def list_deductions():
    limit, offset = pagination.parse_limit_offset()
    order_id = V.opt_str(request.args, "garnishment_order_id")
    paycheck_id = V.opt_str(request.args, "paycheck_id")
    items = list(db.garnishment_deductions.values())
    if order_id:
        items = [d for d in items if d["garnishment_order_id"] == order_id]
    if paycheck_id:
        items = [d for d in items if d["paycheck_id"] == paycheck_id]
    page, total = pagination.slice_sorted(items, limit, offset)
    return response.success_array(
        [serialize.garnishment_deduction(x) for x in page],
        limit=limit, offset=offset, total_count=total,
    )
