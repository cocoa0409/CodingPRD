"""Compartment ops: out-of-service / in-service toggles."""

from db import DB
from errors import APIError
from services.audit import append_compartment_event
from services.machine import get_compartment
from services.util import stamp_update, opt_field, check_version


def out_of_service(machine_id: str, compartment_id: str, payload: dict, actor_id: str):
    c = get_compartment(machine_id, compartment_id)
    check_version(c, opt_field(payload, "version"))
    if c.get("status") == "OUT_OF_SERVICE":
        return c
    if c.get("status") == "OCCUPIED":
        raise APIError(
            "ERR_OCCUPIED_COMPARTMENT_NEEDS_CLEAR",
            "Occupied compartment must be recalled or disposed before going OUT_OF_SERVICE",
            409,
        )
    if c.get("status") == "DECOMMISSIONED":
        raise APIError("ERR_PARCEL_STATE_CHANGED",
                       "DECOMMISSIONED compartment cannot be moved", 409)
    c["status"] = "OUT_OF_SERVICE"
    c["current_parcel_id"] = None
    stamp_update(c)
    append_compartment_event(c["id"], None, "OperationsAdmin", actor_id, "OUT_OF_SERVICE_TOGGLE")
    return c


def in_service(machine_id: str, compartment_id: str, payload: dict, actor_id: str):
    c = get_compartment(machine_id, compartment_id)
    check_version(c, opt_field(payload, "version"))
    if c.get("status") == "AVAILABLE":
        return c
    if c.get("status") != "OUT_OF_SERVICE":
        raise APIError("ERR_PARCEL_STATE_CHANGED",
                       f"Compartment must be OUT_OF_SERVICE (currently {c.get('status')})", 409)
    c["status"] = "AVAILABLE"
    stamp_update(c)
    append_compartment_event(c["id"], None, "OperationsAdmin", actor_id, "OUT_OF_SERVICE_TOGGLE")
    return c
