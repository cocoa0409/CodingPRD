"""Path segments: adding and retiring hops (PRD 3.2)."""

from flask import Blueprint

import db
import derive
import lookup
from consts import ALL_ROLES, LEG_GROUPS, SEGMENT_STATES
from db import base_record, rows, touch
from errors import fail
from middleware import authenticate
from routes._common import body_ref, send, send_list
from valid import body, q_enum, q_string, req_enum, req_int

bp = Blueprint("segments", __name__)


@bp.post("/path-segments")
def create_segment():
    authenticate("PlatformAdmin")
    payload = body()
    path = body_ref(payload, "application_path_id", lookup.path)
    circuit = body_ref(payload, "circuit_id", lookup.circuit)
    device = body_ref(payload, "device_id", lookup.device)
    if path is None:
        fail("ERR_INVALID_REQUEST", "application_path_id is required.")
    leg_group = req_enum(payload, "leg_group", LEG_GROUPS)
    sequence_index = req_int(payload, "sequence_index", 1)

    if (circuit is None) == (device is None):
        fail("ERR_SEGMENT_TARGET_INVALID")

    for existing in db.db.segments.values():
        if (
            existing["application_path_id"] == path["id"]
            and existing["leg_group"] == leg_group
            and existing["sequence_index"] == sequence_index
            and existing["segment_state"] == "ACTIVE"
        ):
            fail("ERR_SEGMENT_POSITION_TAKEN")

    segment = base_record()
    segment.update(
        {
            "application_path_id": path["id"],
            "leg_group": leg_group,
            "sequence_index": sequence_index,
            "circuit_id": circuit["id"] if circuit else None,
            "device_id": device["id"] if device else None,
            "segment_state": "ACTIVE",
        }
    )
    db.db.segments[segment["id"]] = segment

    derive.recompute_topology()
    touch(path)
    return send(segment, 201)


@bp.get("/path-segments/<id>")
def get_segment(id):
    authenticate(
        "NocAnalyst", "NocShiftLead", "VendorManager", "CapacityPlanner", "PlatformAdmin"
    )
    return send(lookup.segment(id))


@bp.get("/path-segments")
def list_segments():
    authenticate(
        "NocAnalyst", "NocShiftLead", "VendorManager", "CapacityPlanner", "PlatformAdmin"
    )
    application_path_id = q_string("application_path_id")
    circuit_id = q_string("circuit_id")
    device_id = q_string("device_id")
    leg_group = q_enum("leg_group", LEG_GROUPS)
    segment_state = q_enum("segment_state", SEGMENT_STATES)
    result = []
    for segment in rows(db.db.segments):
        if application_path_id and segment["application_path_id"] != application_path_id:
            continue
        if circuit_id and segment["circuit_id"] != circuit_id:
            continue
        if device_id and segment["device_id"] != device_id:
            continue
        if leg_group and segment["leg_group"] != leg_group:
            continue
        if segment_state and segment["segment_state"] != segment_state:
            continue
        result.append(segment)
    return send_list(result)


@bp.delete("/path-segments/<id>")
def retire_segment(id):
    authenticate("PlatformAdmin")
    segment = lookup.segment(id)
    path = db.db.paths.get(segment["application_path_id"])
    segment["segment_state"] = "RETIRED"
    touch(segment)
    derive.recompute_topology()
    if path is not None:
        touch(path)
    return send(segment)
