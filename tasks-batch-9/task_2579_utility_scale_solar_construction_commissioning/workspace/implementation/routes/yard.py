"""Laydown yard zones and inbound deliveries."""

from flask import Blueprint

import calc
import clock
import envelope
import store
import validate
from clock import dec
from errors import fail, invalid
from routes.common import filter_eq, paginate, require_same_project, unique_check
from validate import ALL_ROLES, authorize, body, dt, e, i, s

bp = Blueprint("yard", __name__)

COMPONENT_TYPES = ("MODULE", "TRACKER", "INVERTER")


@bp.post("/solar/projects/<project_id>/yard-zones")
def create_yard_zone(project_id):
    authorize("ProcurementCoordinator")
    data = body(s("zone_code"), i("pallet_capacity", gt=0))
    store.require_project(project_id)
    unique_check(store.yard_zones, "project_id", project_id, "zone_code", data["zone_code"])
    row = store.base()
    row.update(
        {
            "project_id": project_id,
            "zone_code": data["zone_code"],
            "pallet_capacity": data["pallet_capacity"],
            "reserved_pallets": 0,
            "available_pallets": data["pallet_capacity"],
        }
    )
    store.yard_zones[row["id"]] = row
    return envelope.created(row)


@bp.get("/solar/yard-zones/<zone_id>")
def get_yard_zone(zone_id):
    authorize(*ALL_ROLES)
    return envelope.ok(store.require_yard_zone(zone_id))


@bp.get("/solar/projects/<project_id>/yard-zones")
def list_yard_zones(project_id):
    authorize(*ALL_ROLES)
    store.require_project(project_id)
    return paginate(store.children(store.yard_zones, "project_id", project_id))


@bp.post("/solar/deliveries")
def create_delivery():
    authorize("ProcurementCoordinator")
    data = body(
        s("project_id"),
        s("yard_zone_id"),
        e("component_type", COMPONENT_TYPES),
        i("unit_qty", gt=0),
        i("pallets", gt=0),
        dt("planned_arrival_at"),
        dt("laydown_window_start"),
        dt("laydown_window_end"),
        i("expected_yard_zone_version"),
        s("inspection_note", required=False),
    )
    validate.window_bounds(data["laydown_window_start"], data["laydown_window_end"])
    store.require_project(data["project_id"])
    zone = store.require_yard_zone(data["yard_zone_id"])
    require_same_project(zone["project_id"], data["project_id"])
    if data["expected_yard_zone_version"] != zone["version"]:
        fail("ERR_STALE_YARD_ZONE_VERSION")

    occupied = calc.laydown_occupied(
        zone, data["laydown_window_start"], data["laydown_window_end"]
    )
    if occupied + data["pallets"] > zone["pallet_capacity"]:
        fail("ERR_YARD_WINDOW_CAPACITY_EXCEEDED")

    row = store.base()
    row.update(
        {
            "project_id": data["project_id"],
            "yard_zone_id": zone["id"],
            "component_type": data["component_type"],
            "unit_qty": data["unit_qty"],
            "pallets": data["pallets"],
            "planned_arrival_at": data["planned_arrival_at"],
            "laydown_window_start": data["laydown_window_start"],
            "laydown_window_end": data["laydown_window_end"],
            "status": "RESERVED",
            "received_unit_qty": None,
            "damaged_unit_qty": None,
            "accepted_unit_qty": None,
            "damage_ratio": None,
            "inspection_note": data["inspection_note"],
            "cancel_reason": None,
        }
    )
    store.deliveries[row["id"]] = row
    calc.recompute_yard_zone(zone)
    store.touch(zone)
    return envelope.created(row)


@bp.get("/solar/deliveries/<delivery_id>")
def get_delivery(delivery_id):
    authorize(*ALL_ROLES)
    return envelope.ok(store.require_delivery(delivery_id))


@bp.get("/solar/deliveries")
def list_deliveries():
    authorize(*ALL_ROLES)
    rows = store.ordered(list(store.deliveries.values()))
    rows = filter_eq(rows, "project_id", validate.q("project_id"))
    rows = filter_eq(rows, "yard_zone_id", validate.q("yard_zone_id"))
    rows = filter_eq(rows, "status", validate.q("status"))
    rows = filter_eq(rows, "component_type", validate.q("component_type"))
    return paginate(rows)


@bp.post("/solar/deliveries/<delivery_id>/receipt")
def receive_delivery(delivery_id):
    authorize("ProcurementCoordinator")
    data = body(
        i("received_unit_qty", gt=0),
        i("damaged_unit_qty", ge=0),
        s("inspection_note", required=False),
    )
    if data["damaged_unit_qty"] > data["received_unit_qty"]:
        invalid("damaged_unit_qty may not exceed received_unit_qty")
    delivery = store.require_delivery(delivery_id)
    if delivery["status"] != "RESERVED":
        fail("ERR_DELIVERY_NOT_RESERVED")

    ratio = clock.num(
        dec(data["damaged_unit_qty"]) / dec(data["received_unit_qty"]), 4
    )
    delivery["received_unit_qty"] = data["received_unit_qty"]
    delivery["damaged_unit_qty"] = data["damaged_unit_qty"]
    delivery["damage_ratio"] = ratio
    if data["inspection_note"] is not None:
        delivery["inspection_note"] = data["inspection_note"]

    # The ARRIVED fork is resolved inside this same request.
    if dec(ratio) <= calc.MAX_DAMAGE_RATIO:
        delivery["status"] = "ACCEPTED"
        delivery["accepted_unit_qty"] = data["received_unit_qty"] - data["damaged_unit_qty"]
        store.touch(delivery)
    else:
        delivery["status"] = "REJECTED"
        delivery["accepted_unit_qty"] = 0
        store.touch(delivery)
        zone = store.yard_zones.get(delivery["yard_zone_id"])
        if zone is not None:
            calc.recompute_yard_zone(zone)
            store.touch(zone)
    return envelope.ok(delivery)


@bp.post("/solar/deliveries/<delivery_id>/cancellation")
def cancel_delivery(delivery_id):
    authorize("ProcurementCoordinator")
    data = body(s("cancel_reason"))
    delivery = store.require_delivery(delivery_id)
    if delivery["status"] != "RESERVED":
        fail("ERR_DELIVERY_NOT_RESERVED")
    delivery["status"] = "CANCELLED"
    delivery["cancel_reason"] = data["cancel_reason"]
    store.touch(delivery)
    zone = store.yard_zones.get(delivery["yard_zone_id"])
    if zone is not None:
        calc.recompute_yard_zone(zone)
        store.touch(zone)
    return envelope.ok(delivery)
