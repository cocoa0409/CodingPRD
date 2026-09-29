"""Lab-pack container endpoints (PRD §3.8)."""

from flask import Blueprint, request

import serializers
from calc import ZERO, dec
from common import gate_frozen, list_response
from envelope import ok
from errors import ApiError
from rollups import (
    containers_of_event,
    live_container_net_weight,
    program_counters,
    refresh_world,
)
from routes_material import COMPATIBILITY_CLASSES
from store import new_row, set_and_touch, store
from validation import (
    ALL_READ_ROLES,
    authorize,
    body,
    context,
    lookup,
    req_enum,
    req_num,
    req_str,
)

bp = Blueprint("containers", __name__)

CONTAINER_ACTIONS = ["SEAL", "UNSEAL"]


@bp.post("/hhw/containers")
def create_container():
    user_id, role = context()
    authorize(role, ["PackingContractor"])
    payload = body()
    event_id = req_str(payload, "event_id")
    container_code = req_str(payload, "container_code")
    compatibility_class = req_enum(payload, "compatibility_class", COMPATIBILITY_CLASSES)
    capacity_kg = req_num(payload, "capacity_kg", gt=0)

    event = lookup("event", event_id)

    for existing in containers_of_event(event["id"]):
        if existing["container_code"] == container_code:
            raise ApiError("ERR_INVALID_REQUEST",
                           "container_code must be unique within the event.")

    row = new_row({
        "event_id": event["id"],
        "manifest_id": None,
        "container_code": container_code,
        "compatibility_class": compatibility_class,
        "capacity_kg": capacity_kg,
        "status": "OPEN",
        "line_count": 0,
        "net_weight_kg": ZERO,
        "estimated_disposal_cost_cents": 0,
        "sealed_by_user_id": None,
        "discrepancy_flag": False,
    })
    store.containers[row["id"]] = row
    refresh_world()
    return ok(serializers.packed_container(row), 201)


@bp.get("/hhw/containers")
def list_containers():
    user_id, role = context()
    authorize(role, ALL_READ_ROLES)
    filters = {
        "event_id": request.args.get("event_id"),
        "manifest_id": request.args.get("manifest_id"),
        "status": request.args.get("status"),
    }
    return list_response(request.args, list(store.containers.values()),
                         serializers.packed_container, filters)


@bp.get("/hhw/containers/<container_id>")
def read_container(container_id):
    user_id, role = context()
    authorize(role, ALL_READ_ROLES)
    return ok(serializers.packed_container(lookup("container", container_id)))


@bp.post("/hhw/containers/<container_id>/lines")
def pack_line(container_id):
    user_id, role = context()
    authorize(role, ["PackingContractor"])
    payload = body()
    dropoff_line_id = req_str(payload, "dropoff_line_id")

    container = lookup("container", container_id)                       # rung 4
    line = lookup("dropoff_line", dropoff_line_id)                      # rung 5

    if container["status"] != "OPEN":                                   # rung 9
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "The container is not open for packing.")

    category = store.material_categories.get(line["material_category_id"])
    if category is None or category["compatibility_class"] != container["compatibility_class"]:
        raise ApiError("ERR_INCOMPATIBLE_MATERIAL_CLASS")               # rung 20

    appointment = store.appointments.get(line["appointment_id"])
    if appointment is None or appointment["event_id"] != container["event_id"]:
        raise ApiError("ERR_CONTAINER_EVENT_MISMATCH")                  # rung 21

    if line["container_id"] is not None or line["disposition"] != "ACCEPTED":
        raise ApiError("ERR_LINE_ALREADY_PACKED")                       # rung 22

    projected = live_container_net_weight(container) + dec(line["net_weight_kg"])
    if projected > dec(container["capacity_kg"]):                       # rung 29
        raise ApiError("ERR_CONTAINER_CAPACITY_EXCEEDED")

    set_and_touch(line, container_id=container["id"])
    set_and_touch(container)
    refresh_world()
    return ok(serializers.packed_container(container))


@bp.post("/hhw/containers/<container_id>/transitions")
def container_transition(container_id):
    user_id, role = context()
    authorize(role, ["PackingContractor"])
    payload = body()
    action = req_enum(payload, "action", CONTAINER_ACTIONS)

    container = lookup("container", container_id)
    event = store.events.get(container["event_id"])
    program = store.programs.get(event["program_id"]) if event else None

    if action == "SEAL":
        if container["status"] != "OPEN":                               # rung 9
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        if container["line_count"] < 1:
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "The container holds no line.")
        gate_frozen(program)                                            # rung 14
        counters = program_counters(program)                            # rung 31
        committed = (counters["budget_encumbered_cents"]
                     + counters["budget_in_transit_cents"]
                     + counters["budget_spent_cents"])
        if committed + container["estimated_disposal_cost_cents"] > program["budget_cents"]:
            raise ApiError("ERR_PROGRAM_BUDGET_EXCEEDED")
        set_and_touch(container, status="SEALED", sealed_by_user_id=user_id)
    else:
        if container["status"] != "SEALED":                             # rung 9
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        if container["manifest_id"] is not None:
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "The container is listed on a manifest.")
        set_and_touch(container, status="OPEN", sealed_by_user_id=None)

    refresh_world()
    return ok(serializers.packed_container(container))
