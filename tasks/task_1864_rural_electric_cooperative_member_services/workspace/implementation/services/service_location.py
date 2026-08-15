"""ServiceLocation service: CRUD and lifecycle transitions."""
from errors import ApiError
import db
from db import store, new_common, touch


def create_service_location(body):
    required = ["member_id", "address", "rate_class"]
    for field in required:
        if field not in body:
            raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing required field: {field}")
    member = store.members.get(body["member_id"])
    if not member:
        raise ApiError("ERR_NOT_FOUND", 404, "Member not found")
    if body["rate_class"] not in ("RESIDENTIAL", "COMMERCIAL_GENERAL", "COMMERCIAL_DEMAND", "IRRIGATION", "SEASONAL"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid rate_class")
    loc = new_common({
        "member_id": body["member_id"],
        "address": body["address"],
        "rate_class": body["rate_class"],
        "status": "PENDING_CONSTRUCTION",
        "energized_at": None,
        "seasonal_active": True,
        "irrigation_connected_load_kw": body.get("irrigation_connected_load_kw"),
    })
    store.service_locations[loc["id"]] = loc
    return loc


def get_service_location(loc_id):
    loc = store.service_locations.get(loc_id)
    if not loc:
        raise ApiError("ERR_NOT_FOUND", 404, "ServiceLocation not found")
    return loc


def energize_location(loc_id):
    loc = get_service_location(loc_id)
    if loc["status"] == "PENDING_CONSTRUCTION":
        # Check: ServiceOrder in CONSTRUCTED
        orders = [so for so in store.service_orders.values()
                  if so.get("service_location_id") == loc_id and so.get("status") == "CONSTRUCTED"]
        if not orders:
            raise ApiError("ERR_SERVICE_NOT_CONSTRUCTED", 409,
                           "No ServiceOrder in CONSTRUCTED status for this location")
        # Check: ROW in RECORDED
        rows = [r for r in store.right_of_way_agreements.values()
                if r.get("service_location_id") == loc_id and r.get("status") == "RECORDED"]
        if not rows:
            raise ApiError("ERR_ROW_NOT_RECORDED", 409,
                           "RightOfWayAgreement not in RECORDED status")
        loc["status"] = "ENERGIZED"
        loc["energized_at"] = db.wall_now()
        touch(loc)
        # Cascade: ServiceOrder CONSTRUCTED -> ENERGIZED
        for so in orders:
            so["status"] = "ENERGIZED"
            touch(so)
    elif loc["status"] == "DISCONNECTED":
        member = store.members.get(loc["member_id"])
        if not member or member["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", 409, "Member must be ACTIVE to re-energize")
        loc["status"] = "ENERGIZED"
        loc["energized_at"] = db.wall_now()
        touch(loc)
    else:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Location must be PENDING_CONSTRUCTION or DISCONNECTED to energize")
    return loc


def disconnect_location(loc_id):
    loc = get_service_location(loc_id)
    if loc["status"] != "ENERGIZED":
        raise ApiError("ERR_INVALID_STATE", 409, "Location must be ENERGIZED to disconnect")
    loc["status"] = "DISCONNECTED"
    touch(loc)
    # Cascade: devices ENROLLED/ACTIVE -> SUSPENDED
    for dev in store.load_management_devices.values():
        if dev.get("service_location_id") == loc_id and dev["status"] in ("ENROLLED", "ACTIVE"):
            dev["status"] = "SUSPENDED"
            touch(dev)
    return loc


def remove_location(loc_id):
    loc = get_service_location(loc_id)
    if loc["status"] != "DISCONNECTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Location must be DISCONNECTED to remove")
    member = store.members.get(loc["member_id"])
    if not member or member["status"] != "TERMINATED":
        raise ApiError("ERR_INVALID_STATE", 409, "Member must be TERMINATED to remove location")
    loc["status"] = "REMOVED"
    touch(loc)
    return loc
