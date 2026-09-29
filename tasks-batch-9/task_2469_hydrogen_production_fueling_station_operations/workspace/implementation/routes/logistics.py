"""Delivery logistics: booking, arrival, offload, refusal and rebooking."""
from decimal import Decimal as D

from flask import Blueprint

import derive
import serializers as ser
from auth import actor, require_station_owner
from constants import (
    DELIVERY_MODES,
    DELIVERY_STATUSES,
    MAX_RESCHEDULES,
    REJECT_REASONS,
)
from envelope import created, listing, ok
from errors import raise_error
from helpers import (
    append_ledger,
    bay_conflict,
    get_delivery,
    get_lot,
    get_station,
    get_vessel,
    maybe_consume_lot,
    pressure_delta_for_mass,
    require_not_frozen,
    require_responders,
    require_vessel_fit,
    set_vessel_pressure,
)
from store import base_row, db, sort_created, touch
from validate import (
    bad,
    f_dt,
    f_enum,
    f_num,
    f_str,
    forbid,
    json_body,
    pagination,
    paginate,
    q_enum,
    q_str,
)

bp = Blueprint("logistics", __name__)


@bp.get("/deliveries/<delivery_id>")
def read_delivery(delivery_id):
    actor("PlatformAdmin", "LogisticsDispatcher", "StationOperator", "ComplianceAdmin")
    return ok(ser.delivery(get_delivery(delivery_id)))


@bp.get("/deliveries")
def list_deliveries():
    actor("PlatformAdmin", "LogisticsDispatcher", "StationOperator", "ComplianceAdmin")
    limit, offset = pagination()
    station_id = q_str("station_id")
    lot_id = q_str("production_lot_id")
    vessel_id = q_str("receiving_vessel_id")
    status = q_enum("status", DELIVERY_STATUSES)
    mode = q_enum("mode", DELIVERY_MODES)
    rows = sort_created(list(db.deliveries.values()))
    if station_id is not None:
        rows = [r for r in rows if r["station_id"] == station_id]
    if lot_id is not None:
        rows = [r for r in rows if r["production_lot_id"] == lot_id]
    if vessel_id is not None:
        rows = [r for r in rows if r["receiving_vessel_id"] == vessel_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if mode is not None:
        rows = [r for r in rows if r["mode"] == mode]
    page = paginate(rows, limit, offset)
    return listing([ser.delivery(r) for r in page], limit, offset, len(rows))


@bp.post("/deliveries")
def book_delivery():
    actor("LogisticsDispatcher")
    body = json_body()
    station_id = f_str(body, "station_id")
    lot_id = f_str(body, "production_lot_id")
    vessel_id = f_str(body, "receiving_vessel_id")
    mode = f_enum(body, "mode", DELIVERY_MODES)
    planned_kg = f_num(body, "planned_kg", 3, gt=D(0))
    window_start, raw_ws = f_dt(body, "window_start")
    window_end, raw_we = f_dt(body, "window_end")
    departed_at, raw_dep = f_dt(body, "departed_at")

    if mode == "TUBE_TRAILER":
        trailer_volume = f_num(body, "trailer_water_volume_l", 3, gt=D(0))
        trailer_pressure = f_num(body, "trailer_final_pressure_bar", 2, ge=D(0))
    else:
        forbid(body, "trailer_water_volume_l")
        forbid(body, "trailer_final_pressure_bar")
        trailer_volume = None
        trailer_pressure = None

    if window_end <= window_start:
        bad("Field 'window_end' must be strictly after 'window_start'.")
    if departed_at > window_start:
        bad("Field 'departed_at' must be at or before 'window_start'.")

    station = get_station(station_id)
    get_lot(lot_id)
    vessel = get_vessel(vessel_id)

    if vessel["station_id"] != station["id"]:
        raise_error("ERR_AGREEMENT_MISMATCH")
    require_vessel_fit(vessel)
    if bay_conflict(station, window_start, window_end):
        raise_error("ERR_OFFLOAD_BAY_CONFLICT")

    row = base_row()
    row.update({
        "station_id": station["id"],
        "production_lot_id": lot_id,
        "receiving_vessel_id": vessel["id"],
        "mode": mode,
        "planned_kg": planned_kg,
        "window_start": window_start,
        "window_end": window_end,
        "trailer_water_volume_l": trailer_volume,
        "trailer_final_pressure_bar": trailer_pressure,
        "departed_at": departed_at,
        "arrived_at": None,
        "accepted_at": None,
        "transit_hours": None,
        "boiloff_kg": None,
        "heel_kg": None,
        "net_receipt_kg": None,
        "status": "SCHEDULED",
        "reject_reason": None,
        "reschedule_count": 0,
        "_raw": {"window_start": raw_ws, "window_end": raw_we, "departed_at": raw_dep},
    })
    db.deliveries[row["id"]] = row
    touch(station)
    return created(ser.delivery(row))


@bp.post("/deliveries/<delivery_id>/arrive")
def arrive(delivery_id):
    actor("LogisticsDispatcher")
    delivery = get_delivery(delivery_id)
    if delivery["status"] != "SCHEDULED":
        raise_error("ERR_INVALID_STATE_TRANSITION")

    now = db.clock
    if not (delivery["window_start"] <= now < delivery["window_end"]):
        raise_error("ERR_ARRIVAL_OUTSIDE_WINDOW")

    transit_hours, heel_kg, boiloff_kg, net_receipt_kg = derive.delivery_loss_terms(
        delivery, now)
    delivery["arrived_at"] = now
    delivery["transit_hours"] = transit_hours
    delivery["heel_kg"] = heel_kg
    delivery["boiloff_kg"] = boiloff_kg
    delivery["net_receipt_kg"] = net_receipt_kg
    delivery["status"] = "ARRIVED"
    touch(delivery)
    return ok(ser.delivery(delivery))


@bp.post("/deliveries/<delivery_id>/offload")
def offload(delivery_id):
    user_id, role = actor("StationOperator")
    delivery = get_delivery(delivery_id)
    require_station_owner(role, user_id, delivery["station_id"])

    if delivery["status"] != "ARRIVED":
        raise_error("ERR_INVALID_STATE_TRANSITION")

    station = db.stations[delivery["station_id"]]
    require_not_frozen(station)
    require_responders(station)

    vessel = db.pressure_vessels[delivery["receiving_vessel_id"]]
    require_vessel_fit(vessel)

    lot = db.production_lots[delivery["production_lot_id"]]
    if lot["status"] != "RELEASED":
        raise_error("ERR_LOT_NOT_RELEASED")

    net = delivery["net_receipt_kg"]
    new_pressure = vessel["current_pressure_bar"] + pressure_delta_for_mass(vessel, net)
    if new_pressure > vessel["mawp_bar"]:
        raise_error("ERR_VESSEL_PRESSURE_LIMIT")
    if derive.onsite_inventory(station["id"]) + net > station["storage_capacity_kg"]:
        raise_error("ERR_STORAGE_CAPACITY_EXCEEDED")

    delivery["status"] = "ACCEPTED"
    delivery["accepted_at"] = db.clock
    touch(delivery)

    set_vessel_pressure(vessel, new_pressure)

    append_ledger(station["id"], "DELIVERY_RECEIPT", net, "DELIVERY", delivery["id"])
    loss_reason = "HEEL_RETURNED" if delivery["mode"] == "TUBE_TRAILER" else "BOILOFF_LOSS"
    append_ledger(station["id"], loss_reason, D("0.000"), "DELIVERY", delivery["id"])

    maybe_consume_lot(lot)
    touch(station)
    return ok(ser.delivery(delivery))


@bp.post("/deliveries/<delivery_id>/reject")
def reject(delivery_id):
    user_id, role = actor("StationOperator")
    delivery = get_delivery(delivery_id)
    require_station_owner(role, user_id, delivery["station_id"])

    body = json_body()
    reject_reason = f_enum(body, "reject_reason", REJECT_REASONS)

    if delivery["status"] != "ARRIVED":
        raise_error("ERR_INVALID_STATE_TRANSITION")

    delivery["status"] = "QUARANTINED" if reject_reason == "PURITY_FAIL" else "REJECTED"
    delivery["reject_reason"] = reject_reason
    touch(delivery)
    touch(db.stations[delivery["station_id"]])
    return ok(ser.delivery(delivery))


@bp.post("/deliveries/<delivery_id>/reschedule")
def reschedule(delivery_id):
    actor("LogisticsDispatcher")
    delivery = get_delivery(delivery_id)
    body = json_body()
    window_start, raw_ws = f_dt(body, "window_start")
    window_end, raw_we = f_dt(body, "window_end")
    if window_end <= window_start:
        bad("Field 'window_end' must be strictly after 'window_start'.")

    if delivery["status"] != "REJECTED":
        raise_error("ERR_INVALID_STATE_TRANSITION")
    if delivery["reschedule_count"] >= MAX_RESCHEDULES:
        raise_error("ERR_RESCHEDULE_LIMIT_REACHED")

    station = db.stations[delivery["station_id"]]
    if bay_conflict(station, window_start, window_end, exclude_id=delivery["id"]):
        raise_error("ERR_OFFLOAD_BAY_CONFLICT")

    delivery["window_start"] = window_start
    delivery["window_end"] = window_end
    delivery.setdefault("_raw", {})["window_start"] = raw_ws
    delivery["_raw"]["window_end"] = raw_we
    delivery["reschedule_count"] = delivery["reschedule_count"] + 1
    delivery["arrived_at"] = None
    delivery["transit_hours"] = None
    delivery["boiloff_kg"] = None
    delivery["heel_kg"] = None
    delivery["net_receipt_kg"] = None
    delivery["reject_reason"] = None
    delivery["status"] = "SCHEDULED"
    touch(delivery)
    touch(station)
    return ok(ser.delivery(delivery))
