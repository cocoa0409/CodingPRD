"""Device endpoints."""

from flask import Blueprint, request

from db import store
from middleware import require_roles, ALL_ROLES, ROLE_CONTRACTOR_ADMIN
from response import success_object, list_response
from util import get_body, check_unknown_fields, req_str, req_enum
from errors import (
    invalid_state, open_items_block, duplicate_constraint,
    cross_reference_mismatch, invalid_request,
)
from services.core import (
    base_record, public, touch,
    get_system, get_device, ref_device,
    contractor_of_system, property_of_system,
    require_contractor_active, require_property_active,
)
from services import calc

bp = Blueprint("devices", __name__)

DEVICE_TYPES = {
    "SMOKE_DETECTOR", "PULL_STATION", "NOTIFICATION_APPLIANCE",
    "SPRINKLER_HEAD", "GAUGE_VALVE", "FIRE_PUMP_CONTROLLER",
    "BACKFLOW_ASSEMBLY", "SUPERVISORY_SWITCH",
}


def _gates_for_system(sys):
    prop = property_of_system(sys)
    con = contractor_of_system(sys)
    require_contractor_active(con)
    require_property_active(prop)
    return prop, con


@bp.route("/fire-compliance/systems/<sid>/devices", methods=["POST"])
def create_device(sid):
    require_roles([ROLE_CONTRACTOR_ADMIN])
    sys = get_system(sid)
    body = get_body()
    check_unknown_fields(body, {"device_type", "serial_no"})
    serial_no = req_str(body, "serial_no")
    device_type_raw = body.get("device_type")
    if not isinstance(device_type_raw, str):
        raise invalid_request("device_type is required and must be a string")
    prop, con = _gates_for_system(sys)
    if sys["status"] != "IN_SERVICE":
        raise invalid_state("ProtectedSystem is DECOMMISSIONED")
    # uniqueness (priority 13) before enum membership (priority 14)
    for dev in store.devices.values():
        if dev["system_id"] == sys["id"] and dev["serial_no"] == serial_no:
            raise duplicate_constraint("serial_no must be unique within the parent system")
    device_type = req_enum(body, "device_type", DEVICE_TYPES)

    frequency = calc.FREQ_BY_DEVICE_TYPE[device_type]
    next_due = calc.device_next_due_from_base(sys["install_date"], frequency)
    rec = base_record()
    rec.update({
        "system_id": sys["id"],
        "device_type": device_type,
        "serial_no": serial_no,
        "frequency_code": frequency,
        "next_due_date": next_due,
        "replaced_by_device_id": None,
        "status": "IN_SERVICE",
    })
    store.devices[rec["id"]] = rec
    if prop is not None:
        calc.recompute_property_plan_totals(prop["id"])
    return success_object(public(rec), status=201)


@bp.route("/fire-compliance/systems/<sid>/devices", methods=["GET"])
def list_devices(sid):
    require_roles(ALL_ROLES)
    sys = get_system(sid)
    status = request.args.get("status")
    rows = [d for d in store.devices.values() if d["system_id"] == sys["id"]]
    if status is not None:
        rows = [d for d in rows if d["status"] == status]
    return list_response(rows, request.args, public)


@bp.route("/fire-compliance/devices/<did>", methods=["GET"])
def fetch_device(did):
    require_roles(ALL_ROLES)
    return success_object(public(get_device(did)))


@bp.route("/fire-compliance/devices", methods=["GET"])
def list_devices_cross():
    require_roles(ALL_ROLES)
    system_id = request.args.get("system_id")
    replaced_by = request.args.get("replaced_by_device_id")
    status = request.args.get("status")
    rows = list(store.devices.values())
    if system_id is not None:
        rows = [d for d in rows if d["system_id"] == system_id]
    if replaced_by is not None:
        rows = [d for d in rows if d["replaced_by_device_id"] == replaced_by]
    if status is not None:
        rows = [d for d in rows if d["status"] == status]
    return list_response(rows, request.args, public)


def _no_open_deficiency(dev):
    for d in store.deficiencies.values():
        if d["device_id"] == dev["id"] and d["status"] == "OPEN":
            raise open_items_block("Device has an OPEN deficiency")


@bp.route("/fire-compliance/devices/<did>/replace", methods=["POST"])
def replace_device(did):
    require_roles([ROLE_CONTRACTOR_ADMIN])
    dev = get_device(did)
    body = get_body()
    check_unknown_fields(body, {"replaced_by_device_id"})
    if dev["status"] != "IN_SERVICE":
        raise invalid_state("Device is not IN_SERVICE")
    sys = store.systems.get(dev["system_id"])
    prop, con = _gates_for_system(sys)
    replaced_by_id = req_str(body, "replaced_by_device_id")
    replacement = ref_device(replaced_by_id, field="replaced_by_device_id")
    # must reference a different IN_SERVICE device in the same system
    if (replacement["id"] == dev["id"]
            or replacement["system_id"] != dev["system_id"]
            or replacement["status"] != "IN_SERVICE"):
        raise cross_reference_mismatch(
            "replaced_by_device_id must reference a different IN_SERVICE device in the same system")
    _no_open_deficiency(dev)

    dev["status"] = "REPLACED"
    dev["replaced_by_device_id"] = replacement["id"]
    touch(dev)
    # replacement inherits urgency: earlier of its own default and the old
    # device's current next_due_date
    if dev["next_due_date"] < replacement["next_due_date"]:
        replacement["next_due_date"] = dev["next_due_date"]
        touch(replacement)
    if prop is not None:
        calc.recompute_property_plan_totals(prop["id"])
    return success_object(public(dev))


@bp.route("/fire-compliance/devices/<did>/remove", methods=["POST"])
def remove_device(did):
    require_roles([ROLE_CONTRACTOR_ADMIN])
    dev = get_device(did)
    if dev["status"] != "IN_SERVICE":
        raise invalid_state("Device is not IN_SERVICE")
    sys = store.systems.get(dev["system_id"])
    prop, con = _gates_for_system(sys)
    _no_open_deficiency(dev)

    dev["status"] = "REMOVED"
    touch(dev)
    if prop is not None:
        calc.recompute_property_plan_totals(prop["id"])
    return success_object(public(dev))
