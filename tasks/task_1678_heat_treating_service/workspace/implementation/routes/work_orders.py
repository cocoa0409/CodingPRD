"""WorkOrder endpoints: intake (rush lane), ship, cancel, list/get."""
from datetime import timedelta

from flask import Blueprint

import db
import validation as v
from db import store, new_id, new_common, touch
from errors import ApiError
from middleware import ANY_ROLES, check_ownership, get_context, require_roles
from response import Paginator, created, ok
from services import domain

bp = Blueprint("work_orders", __name__)


@bp.post("/work-orders")
def create_work_order():
    get_context()
    require_roles(["CustomerServiceRep"])
    body = v.get_body()

    # tier 4: body FK existence (evaluated before temporal/constraint/fiscal tiers)
    customer = recipe = None
    if v.present(body, "customer_id"):
        customer = v.resolve_fk(store.customers, body.get("customer_id"), "ERR_CUSTOMER_NOT_FOUND")
    if v.present(body, "recipe_id"):
        recipe = v.resolve_fk(store.recipes, body.get("recipe_id"), "ERR_RECIPE_NOT_FOUND")

    # tier 8 (temporal): RUSH guarantee window >= 4 hours
    lane_raw = body.get("service_lane", "STANDARD")
    hours_raw = body.get("guaranteed_turnaround_hours")
    if lane_raw == "RUSH" and v.is_int(hours_raw) and hours_raw < 4:
        raise ApiError("ERR_INVALID_GUARANTEE_WINDOW", 422,
                       "RUSH guaranteed_turnaround_hours must be >= 4")

    # tier 9 (constraint): required fields, enum validity, RUSH guarantee presence
    if customer is None:
        v.req_string(body, "customer_id")  # raises ERR_INVALID_REQUEST
    if recipe is None:
        v.req_string(body, "recipe_id")  # raises ERR_INVALID_REQUEST
    part_quantity = v.req_int(body, "part_quantity")
    received_weight_lb = v.req_number(body, "received_weight_lb")
    declared_value_cents = v.req_int(body, "declared_value_cents")
    processing_charge_cents = v.req_int(body, "processing_charge_cents")
    service_lane = v.opt_enum(body, "service_lane", domain.SERVICE_LANES, default="STANDARD")
    guaranteed_turnaround_hours = v.opt_int(body, "guaranteed_turnaround_hours", default=None)
    if service_lane == "RUSH" and guaranteed_turnaround_hours is None:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "guaranteed_turnaround_hours is required when service_lane is RUSH")

    # tier 10 (fiscal): credit standing
    if customer["credit_hold"]:
        raise ApiError("ERR_CUSTOMER_CREDIT_HOLD", 402,
                       "Customer account is on credit hold")

    now = db.clock()
    is_rush = service_lane == "RUSH"
    order = {
        "id": new_id(),
        "customer_id": customer["id"],
        "recipe_id": recipe["id"],
        "part_quantity": part_quantity,
        "received_weight_lb": received_weight_lb,
        "declared_value_cents": declared_value_cents,
        "processing_charge_cents": processing_charge_cents,
        "service_lane": service_lane,
        "guaranteed_turnaround_hours": guaranteed_turnaround_hours if is_rush else None,
        "received_at": now,
        "promised_due_at": (now + timedelta(hours=guaranteed_turnaround_hours)) if is_rush else None,
        "shipped_at": None,
        "turnaround_breached": False,
        "rush_surcharge_quoted_cents": (domain.rush_quote(processing_charge_cents,
                                                          guaranteed_turnaround_hours)
                                        if is_rush else 0),
        "rush_surcharge_final_cents": None,
        "energy_surcharge_cents": None,
        "retreat_count": 0,
        "processing_status": "RECEIVED",
        "quality_status": "PENDING_TEST",
    }
    new_common(order)
    store.work_orders[order["id"]] = order
    return created(order)


@bp.get("/work-orders")
def list_work_orders():
    get_context()
    require_roles(ANY_ROLES)
    pg = Paginator()
    rows = list(store.work_orders.values())
    rows = pg.filter(rows, "customer_id")
    rows = pg.filter(rows, "recipe_id")
    rows = pg.filter(rows, "processing_status")
    rows = pg.filter(rows, "service_lane")
    return ok(pg(rows), rtype="array", pagination=pg)


@bp.get("/work-orders/<work_order_id>")
def get_work_order(work_order_id):
    get_context()
    require_roles(ANY_ROLES)
    order = v.resolve_path(store.work_orders, work_order_id, "ERR_WORK_ORDER_NOT_FOUND")
    check_ownership(order["customer_id"])
    return ok(order)


@bp.post("/work-orders/<work_order_id>/ship")
def ship_work_order(work_order_id):
    get_context()
    require_roles(["CustomerServiceRep"])
    order = v.resolve_path(store.work_orders, work_order_id, "ERR_WORK_ORDER_NOT_FOUND")
    # tier 5: state machine gate — PROCESSED with quality PASSED or WAIVED
    if order["processing_status"] != "PROCESSED" or order["quality_status"] not in ("PASSED", "WAIVED"):
        raise ApiError("ERR_WORK_ORDER_NOT_SHIPPABLE", 409,
                       "Ship requires PROCESSED with quality_status in {PASSED, WAIVED}")
    shipped_at = db.clock()
    order["shipped_at"] = shipped_at
    # calculations.turnaround_breach_assessment: strictly later than promised is a breach;
    # shipping exactly at promised_due_at meets the guarantee.
    if order["service_lane"] == "RUSH":
        breached = shipped_at > order["promised_due_at"]
        order["turnaround_breached"] = breached
        order["rush_surcharge_final_cents"] = 0 if breached else order["rush_surcharge_quoted_cents"]
    else:
        order["turnaround_breached"] = False
        order["rush_surcharge_final_cents"] = 0
    order["processing_status"] = "SHIPPED"
    touch(order)
    return ok(order)


@bp.post("/work-orders/<work_order_id>/cancel")
def cancel_work_order(work_order_id):
    get_context()
    require_roles(["CustomerServiceRep"])
    order = v.resolve_path(store.work_orders, work_order_id, "ERR_WORK_ORDER_NOT_FOUND")
    # tier 5: cancel requires RECEIVED or SCHEDULED
    if order["processing_status"] not in ("RECEIVED", "SCHEDULED"):
        raise ApiError("ERR_WORK_ORDER_NOT_CANCELLABLE", 409,
                       "Cancel requires processing_status in {RECEIVED, SCHEDULED}")
    if order["processing_status"] == "SCHEDULED":
        # Cascade: flip the ACTIVE assignment, recompute the load's weight, bump its version.
        for a in store.load_assignments.values():
            if a["work_order_id"] == order["id"] and a["status"] == "ACTIVE":
                a["status"] = "REMOVED"
                touch(a)
                load = store.load_batches.get(a["load_batch_id"])
                if load is not None:
                    domain.recompute_load_weight(load)
                    touch(load)
                break
    order["processing_status"] = "CANCELLED"
    touch(order)
    return ok(order)
