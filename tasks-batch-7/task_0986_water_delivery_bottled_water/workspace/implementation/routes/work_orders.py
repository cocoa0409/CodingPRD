"""WorkOrder endpoints."""
from flask import Blueprint, g, request

import errors
import services
from db import db
from middleware import (body_json, check_transition, f_date, f_enum, f_int,
                        f_str, require_owner, require_roles)
from response import list_response, ok_object
from routes.routes_stops import create_stop_record
from services import base_record, bump, ser_work_order

bp = Blueprint("work_orders", __name__)

WO_KINDS = {"DELIVERY", "COOLER_INSTALL", "COOLER_RETURN", "PICKUP_ONLY",
            "EXCHANGE_ONLY"}
WO_TERMINAL = ("COMPLETED", "CANCELLED", "REJECTED")


def _get_wo(wid):
    w = db.work_orders.get(wid)
    if w is None:
        raise errors.not_found("work order not found")
    return w


@bp.post("/work-orders")
@require_roles("CustomerSelf", "Dispatcher")
def create_work_order():
    d = body_json()
    customer_id = f_str(d, "customer_id")
    order_kind = f_enum(d, "order_kind", WO_KINDS)
    requested_date = f_date(d, "requested_date")  # malformed -> 422
    quantity_bottles = f_int(d, "quantity_bottles", min_value=0)
    if db.customers.get(customer_id) is None:
        raise errors.invalid_reference("customer_id does not resolve")
    require_owner(customer_id)
    rec = base_record()
    rec.update({
        "customer_id": customer_id,
        "order_kind": order_kind,
        "requested_date": d["requested_date"],
        "quantity_bottles": quantity_bottles,
        "order_status": "PENDING",
        "linked_stop_id": None,
        "linked_rental_id": None,
    })
    with db.lock:
        db.work_orders[rec["id"]] = rec
    return ok_object(ser_work_order(rec), 201)


@bp.get("/work-orders")
@require_roles("OpsAdmin", "Dispatcher", "Driver")
def list_work_orders():
    items = list(db.work_orders.values())
    for param, field in (("customer_id", "customer_id"),
                         ("order_status", "order_status"),
                         ("order_kind", "order_kind"),
                         ("linked_stop_id", "linked_stop_id"),
                         ("linked_rental_id", "linked_rental_id")):
        v = request.args.get(param)
        if v is not None:
            items = [w for w in items if w.get(field) == v]
    return list_response(items, ser_work_order)


@bp.get("/work-orders/<wid>")
@require_roles("OpsAdmin", "Dispatcher", "Driver", "CustomerSelf")
def get_work_order(wid):
    w = _get_wo(wid)
    require_owner(w["customer_id"])
    return ok_object(ser_work_order(w))


@bp.post("/work-orders/<wid>/schedule")
@require_roles("Dispatcher")
def schedule_work_order(wid):
    w = _get_wo(wid)
    check_transition(w, "order_status", ("PENDING",), WO_TERMINAL,
                     "WorkOrder")
    customer = db.customers.get(w["customer_id"])
    if customer is None or customer["account_status"] != "ACTIVE":
        raise errors.invalid_state("customer is not ACTIVE")
    kind = w["order_kind"]
    with db.lock:
        if kind in ("DELIVERY", "EXCHANGE_ONLY", "PICKUP_ONLY"):
            # Find a matching route: same zone, requested date, still open.
            route = None
            for r in db.routes.values():
                if (r["zone_id"] == customer["delivery_zone_id"]
                        and r["service_date"] == w["requested_date"]
                        and r["route_status"] in ("DRAFT", "PUBLISHED")):
                    if route is None or (r["created_at"], r["seq"]) < (
                            route["created_at"], route["seq"]):
                        route = r
            if route is None:
                raise errors.invalid_reference(
                    "no DRAFT/PUBLISHED route exists on requested_date in "
                    "the customer's zone")
            planned = w["quantity_bottles"] if kind != "PICKUP_ONLY" else 0
            empties = (w["quantity_bottles"] if kind == "PICKUP_ONLY"
                       else planned)
            if (services.committed_bottles(route["id"]) + planned
                    > route["truck_capacity_bottles"]):
                raise errors.ApiError(
                    errors.ERR_ROUTE_CAPACITY_EXCEEDED, 422,
                    "scheduling this work order would exceed truck capacity")
            seqs = [s["sequence_index"] for s in db.stops.values()
                    if s["route_id"] == route["id"]]
            next_seq = (max(seqs) + 1) if seqs else 1
            stop = create_stop_record(route, w["customer_id"], next_seq,
                                      planned, planned_empties=empties)
            w["linked_stop_id"] = stop["id"]
        elif kind == "COOLER_INSTALL":
            rental = db.rentals.get(w.get("linked_rental_id") or "")
            if rental is None or rental["rental_status"] != "PENDING_INSTALL":
                raise errors.invalid_state(
                    "linked cooler rental is not PENDING_INSTALL")
        elif kind == "COOLER_RETURN":
            rental = db.rentals.get(w.get("linked_rental_id") or "")
            if rental is None or rental["rental_status"] != "RETURN_REQUESTED":
                raise errors.invalid_state(
                    "linked cooler rental is not RETURN_REQUESTED")
        w["order_status"] = "SCHEDULED"
        bump(w)
    return ok_object(ser_work_order(w))


@bp.post("/work-orders/<wid>/cancel")
@require_roles("CustomerSelf", "Dispatcher")
def cancel_work_order(wid):
    w = _get_wo(wid)
    check_transition(w, "order_status", ("PENDING", "SCHEDULED"), WO_TERMINAL,
                     "WorkOrder")
    require_owner(w["customer_id"])
    with db.lock:
        stop = db.stops.get(w.get("linked_stop_id") or "")
        if stop is not None and stop["stop_status"] == "PLANNED":
            stop["stop_status"] = "CANCELLED"
            bump(stop)
            route = db.routes.get(stop["route_id"])
            if route is not None:
                bump(route)
        w["order_status"] = "CANCELLED"
        bump(w)
    return ok_object(ser_work_order(w))


@bp.post("/work-orders/<wid>/reject")
@require_roles("Dispatcher")
def reject_work_order(wid):
    w = _get_wo(wid)
    check_transition(w, "order_status", ("PENDING",), WO_TERMINAL,
                     "WorkOrder")
    with db.lock:
        w["order_status"] = "REJECTED"
        bump(w)
    return ok_object(ser_work_order(w))
