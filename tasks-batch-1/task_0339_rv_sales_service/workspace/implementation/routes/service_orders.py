"""Service order routes: lifecycle, completion settlement, cancellation (PRD 3.7)."""

from flask import Blueprint, request

import db
import errors
import calculations as calc
from common import (body, new_entity, touch, require_int, require_number,
                    require_bool, paginate, get_or_404, find_dealership)
from middleware import get_auth, require_role
from response import ok, created, ok_list
from services import recompute_part, recompute_open_recall_count

bp = Blueprint("service_orders", __name__)


@bp.post("/service-orders")
def create_so():
    user_id, role = get_auth()
    require_role(role, {"ServiceAdvisor", "DealerManager"})
    data = body()
    did = data.get("dealership_id")
    find_dealership(did)
    unit = get_or_404("units", data.get("unit_id"))
    customer = get_or_404("customers", data.get("customer_id"))

    is_warranty = require_bool(data, "is_warranty", default=False)
    plan = None
    if is_warranty:
        plan_id = data.get("warranty_plan_id")
        if plan_id is None:
            errors.err("ERR_WARRANTY_UNIT_MISMATCH",
                       "warranty_plan_id is required for a warranty order.")
        plan = get_or_404("warranty_plans", plan_id)
        if plan["unit_id"] != unit["id"]:
            errors.err("ERR_WARRANTY_UNIT_MISMATCH",
                       "Warranty plan does not cover this unit.")

    labor_hours = require_number(data, "labor_hours", exclusive_min=0)
    labor_rate = require_int(data, "labor_rate_cents", minimum=0)

    rec = new_entity({
        "dealership_id": did,
        "unit_id": unit["id"],
        "customer_id": customer["id"],
        "advisor_user_id": user_id,
        "is_warranty": is_warranty,
        "warranty_plan_id": plan["id"] if plan else None,
        "labor_hours": labor_hours,
        "labor_rate_cents": labor_rate,
        "parts_subtotal_cents": 0,
        "total_cents": 0,
        "covered_cents": 0,
        "status": "OPEN",
    })
    db.store["service_orders"][rec["id"]] = rec
    return created(rec)


@bp.get("/service-orders")
def list_so():
    _, role = get_auth()
    require_role(role, {"DealerManager", "ServiceAdvisor"})
    items = list(db.store["service_orders"].values())
    a = request.args
    for field in ("dealership_id", "unit_id", "customer_id", "warranty_plan_id", "status"):
        val = a.get(field)
        if val is not None:
            items = [s for s in items if s.get(field) == val]
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@bp.get("/service-orders/<so_id>")
def get_so(so_id):
    user_id, role = get_auth()
    require_role(role, {"DealerManager", "ServiceAdvisor", "Customer"})
    rec = get_or_404("service_orders", so_id)
    if role == "Customer" and rec["customer_id"] != user_id:
        errors.err("ERR_SERVICE_ORDER_NOT_FOUND", "Service order not found.")
    return ok(rec)


@bp.post("/service-orders/<so_id>/start")
def start_so(so_id):
    _, role = get_auth()
    require_role(role, {"ServiceAdvisor"})
    so = get_or_404("service_orders", so_id)
    if so["status"] != "OPEN":
        errors.err("ERR_SO_BAD_STATE", "Service order is not OPEN.")
    so["status"] = "IN_PROGRESS"
    touch(so)
    return ok(so)


@bp.post("/service-orders/<so_id>/await-parts")
def await_parts(so_id):
    _, role = get_auth()
    require_role(role, {"ServiceAdvisor"})
    so = get_or_404("service_orders", so_id)
    if so["status"] != "IN_PROGRESS":
        errors.err("ERR_SO_BAD_STATE", "Service order is not IN_PROGRESS.")
    so["status"] = "AWAITING_PARTS"
    touch(so)
    return ok(so)


@bp.post("/service-orders/<so_id>/resume")
def resume_so(so_id):
    _, role = get_auth()
    require_role(role, {"ServiceAdvisor"})
    so = get_or_404("service_orders", so_id)
    if so["status"] != "AWAITING_PARTS":
        errors.err("ERR_SO_BAD_STATE", "Service order is not AWAITING_PARTS.")
    so["status"] = "IN_PROGRESS"
    touch(so)
    return ok(so)


def _reserved_for(so_id):
    return [r for r in db.store["part_reservations"].values()
            if r["service_order_id"] == so_id and r["status"] == "RESERVED"]


@bp.post("/service-orders/<so_id>/complete")
def complete_so(so_id):
    _, role = get_auth()
    require_role(role, {"ServiceAdvisor"})
    so = get_or_404("service_orders", so_id)
    data = body()

    if so["status"] != "IN_PROGRESS":
        errors.err("ERR_SO_BAD_STATE", "Service order is not IN_PROGRESS.")

    reservations = _reserved_for(so_id)
    labor_cents = calc.labor_cents(so["labor_hours"], so["labor_rate_cents"])
    parts_subtotal = sum(r["quantity"] * r["unit_price_cents"] for r in reservations)
    gross_cents = labor_cents + parts_subtotal

    plan = None
    if so["is_warranty"]:
        plan = db.store["warranty_plans"][so["warranty_plan_id"]]
        remaining_cap = plan["coverage_cap_cents"] - plan["consumed_cents"]
        coverable = calc.warranty_coverable(gross_cents, plan)
        # Warranty cap headroom check (priority 12).
        if coverable > remaining_cap:
            errors.err("ERR_WARRANTY_CAP_EXCEEDED",
                       "Warranty coverage exceeds remaining plan cap.")

    covered, total = calc.service_totals(gross_cents, so["is_warranty"], plan)

    # Commit state + computed totals.
    so["parts_subtotal_cents"] = parts_subtotal
    so["covered_cents"] = covered
    so["total_cents"] = total
    so["status"] = "COMPLETED"
    touch(so)

    # Cascade: fulfill reservations and draw down stock.
    for res in reservations:
        res["status"] = "FULFILLED"
        touch(res)
        part = db.store["part_items"][res["part_item_id"]]
        part["qty_on_hand"] -= res["quantity"]
        recompute_part(part)
        touch(part)

    # Cascade: consume warranty headroom; auto-EXHAUST at cap.
    if so["is_warranty"]:
        plan["consumed_cents"] += covered
        if plan["consumed_cents"] >= plan["coverage_cap_cents"]:
            plan["status"] = "EXHAUSTED"
        touch(plan)

    # Cascade: clear a remediated recall remedy.
    remediates = data.get("remediates_campaign_id")
    if remediates is not None:
        unit = db.store["units"][so["unit_id"]]
        for remedy in db.store["recall_remedies"].values():
            if (remedy["recall_campaign_id"] == remediates
                    and remedy["unit_id"] == unit["id"]
                    and remedy["status"] == "PENDING"):
                remedy["status"] = "CLEARED"
                touch(remedy)
        recompute_open_recall_count(unit)
        touch(unit)

    return ok(so)


@bp.post("/service-orders/<so_id>/cancel")
def cancel_so(so_id):
    _, role = get_auth()
    require_role(role, {"ServiceAdvisor", "DealerManager"})
    so = get_or_404("service_orders", so_id)
    if so["status"] in ("COMPLETED", "CANCELLED"):
        errors.err("ERR_SO_TERMINAL", "Service order is already terminal.")
    so["status"] = "CANCELLED"
    touch(so)

    # Cascade: release reserved parts back to stock.
    for res in _reserved_for(so_id):
        res["status"] = "RELEASED"
        touch(res)
        part = db.store["part_items"][res["part_item_id"]]
        recompute_part(part)
        touch(part)

    # Cascade: cancel SCHEDULED/CHECKED_IN appointments for this order.
    for appt in db.store["appointments"].values():
        if (appt["service_order_id"] == so_id
                and appt["status"] in ("SCHEDULED", "CHECKED_IN")):
            appt["status"] = "CANCELLED"
            touch(appt)

    return ok(so)
