"""Equipment delivery and patient transport logistics (PRD 3.7)."""

from datetime import timedelta

from flask import Blueprint

import calc
import cascade
import derive
from envelope import created, filter_eq, list_response, ok
from errors import ApiError
from store import base_row, db, ordered, parse_dt, touch
from validate import (CALLER_CANCEL_REASONS, ITEM_CODES, ORDER_TYPES, actor,
                      body, opt_enum, opt_int, opt_str, present, req_dt,
                      req_enum, req_int, require_roles)

bp = Blueprint("logistics", __name__)

BUFFER = timedelta(minutes=calc.TURNAROUND_BUFFER_MINUTES)


def _placed_referral(episode):
    for referral in derive.referrals_of(episode["id"]):
        if referral["status"] == "PLACED":
            return referral
    return None


@bp.post("/episodes/<eid>/logistics-orders")
def create_order(eid):
    require_roles("CaseManager")
    episode = derive.get_episode(eid)
    derive.sweep_episode(episode)
    b = body()
    expected_version = req_int(b, "expected_episode_version")
    order_type = req_enum(b, "order_type", ORDER_TYPES)
    start_raw, start_dt = req_dt(b, "window_start")
    end_raw, end_dt = req_dt(b, "window_end")
    vehicle_id = opt_str(b, "vehicle_id", None)
    supplier_id = opt_str(b, "supplier_provider_id", None)
    destination_id = opt_str(b, "destination_provider_id", None)
    item_code = opt_enum(b, "item_code", ITEM_CODES, None)
    mileage = opt_int(b, "mileage_miles", minimum=0, default=None)

    vehicle = derive.get_vehicle(vehicle_id) if vehicle_id is not None else None
    supplier = derive.get_provider(supplier_id) if supplier_id is not None else None
    if destination_id is not None:
        derive.get_provider(destination_id)

    if expected_version != episode["version"]:
        raise ApiError("ERR_STALE_EPISODE_VERSION",
                       "expected_episode_version does not match the episode version")

    if order_type == "DME_DELIVERY" and supplier is not None:
        if supplier["provider_type"] != "DME_SUPPLIER":
            raise ApiError("ERR_PROVIDER_TYPE_MISMATCH",
                           "the supplier must be a DME_SUPPLIER")

    if order_type == "PATIENT_TRANSPORT":
        if vehicle_id is None or mileage is None or supplier_id is not None or item_code is not None:
            raise ApiError("ERR_ORDER_SHAPE_MISMATCH",
                           "PATIENT_TRANSPORT requires vehicle_id and mileage_miles only")
    else:
        if supplier_id is None or item_code is None or vehicle_id is not None or mileage is not None:
            raise ApiError("ERR_ORDER_SHAPE_MISMATCH",
                           "DME_DELIVERY requires supplier_provider_id and item_code only")

    placed = _placed_referral(episode)
    if placed is not None and destination_id is not None:
        chosen = db.offers.get(placed.get("chosen_bed_offer_id"))
        if chosen is not None and chosen["provider_id"] != destination_id:
            raise ApiError("ERR_TRANSPORT_DESTINATION_MISMATCH",
                           "destination differs from the placed referral's provider")

    if end_dt <= start_dt:
        raise ApiError("ERR_INVALID_INTERVAL", "window_end must be strictly after window_start")

    cost = calc.logistics_cost(order_type, vehicle, mileage, item_code)

    if order_type == "PATIENT_TRANSPORT":
        for prior in derive.orders_of(episode["id"]):
            if prior["order_type"] == "PATIENT_TRANSPORT" and \
                    prior["status"] in ("REQUESTED", "CONFIRMED"):
                prior["status"] = "CANCELLED"
                prior["cancel_reason"] = "SUPERSEDED"
                touch(prior)

    row = base_row()
    row.update({
        "episode_id": episode["id"],
        "order_type": order_type,
        "vehicle_id": vehicle_id,
        "supplier_provider_id": supplier_id,
        "destination_provider_id": destination_id,
        "item_code": item_code,
        "mileage_miles": mileage,
        "window_start": start_raw,
        "window_end": end_raw,
        "cost_cents": cost,
        "status": "REQUESTED",
        "cancel_reason": None,
    })
    db.orders[row["id"]] = row
    cascade.advance_to_planning(episode)
    touch(episode)
    return created(derive.ser_order(row))


@bp.post("/logistics-orders/<oid>/confirm")
def confirm_order(oid):
    require_roles("DischargeCoordinator")
    order = derive.get_order(oid)
    episode = derive.get_episode(order["episode_id"])
    derive.sweep_episode(episode)

    if order["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_LOGISTICS_STATE", "the order is not REQUESTED")
    if episode["case_status"] not in ("PLANNING", "READY_FOR_DISCHARGE"):
        raise ApiError("ERR_INVALID_EPISODE_STATE",
                       "the episode does not admit a logistics confirmation")

    if order["order_type"] == "PATIENT_TRANSPORT":
        vehicle = derive.get_vehicle(order["vehicle_id"])
        if vehicle["status"] != "ACTIVE":
            raise ApiError("ERR_RESOURCE_UNAVAILABLE", "the vehicle is OUT_OF_SERVICE")
        start = parse_dt(order["window_start"]) - BUFFER
        end = parse_dt(order["window_end"]) + BUFFER
        for other in db.orders.values():
            if other["id"] == order["id"]:
                continue
            if other["order_type"] != "PATIENT_TRANSPORT" or other["status"] != "CONFIRMED":
                continue
            if other["vehicle_id"] != order["vehicle_id"]:
                continue
            other_start = parse_dt(other["window_start"]) - BUFFER
            other_end = parse_dt(other["window_end"]) + BUFFER
            if start <= other_end and other_start <= end:
                raise ApiError("ERR_VEHICLE_WINDOW_CONFLICT",
                               "the buffered window conflicts with another confirmed order")
    else:
        supplier = derive.get_provider(order["supplier_provider_id"])
        if supplier["provider_type"] != "DME_SUPPLIER":
            raise ApiError("ERR_PROVIDER_TYPE_MISMATCH", "the supplier must be a DME_SUPPLIER")
        if supplier["status"] != "ACTIVE":
            raise ApiError("ERR_RESOURCE_UNAVAILABLE", "the supplier is SUSPENDED")
        placed = _placed_referral(episode)
        if placed is not None:
            needed_by = parse_dt(placed["needed_by"])
            window_end = parse_dt(order["window_end"])
            if needed_by is not None and window_end is not None and window_end > needed_by:
                raise ApiError("ERR_DELIVERY_AFTER_NEEDED_BY",
                               "the delivery window ends after the placed referral's needed_by")

    order["status"] = "CONFIRMED"
    touch(order)
    touch(episode)
    return ok(derive.ser_order(order))


@bp.post("/logistics-orders/<oid>/cancel")
def cancel_order(oid):
    require_roles("DischargeCoordinator", "CaseManager")
    order = derive.get_order(oid)
    derive.get_episode(order["episode_id"])
    b = body()
    reason_code = req_enum(b, "reason_code", CALLER_CANCEL_REASONS)
    if order["status"] not in ("REQUESTED", "CONFIRMED"):
        raise ApiError("ERR_INVALID_LOGISTICS_STATE",
                       "order status %s does not admit a cancellation" % order["status"])
    order["status"] = "CANCELLED"
    order["cancel_reason"] = reason_code
    touch(order)
    return ok(derive.ser_order(order))


@bp.get("/logistics-orders/<oid>")
def read_order(oid):
    require_roles("CaseManager", "DischargeCoordinator", "PlatformAdmin")
    return ok(derive.ser_order(derive.get_order(oid)))


@bp.get("/logistics-orders")
def list_orders():
    require_roles("CaseManager", "DischargeCoordinator", "PlatformAdmin")
    rows = ordered(db.orders.values())
    rows = filter_eq(rows, "episode_id", "episode_id")
    rows = filter_eq(rows, "vehicle_id", "vehicle_id")
    rows = filter_eq(rows, "supplier_provider_id", "supplier_provider_id")
    rows = filter_eq(rows, "destination_provider_id", "destination_provider_id")
    rows = filter_eq(rows, "status", "status")
    return list_response(rows, derive.ser_order)
