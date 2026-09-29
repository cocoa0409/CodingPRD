"""Uniform hazardous waste manifest endpoints (PRD §3.8)."""

from decimal import Decimal

from flask import Blueprint, request

import serializers
from calc import ZERO
from common import gate_frozen, list_response
from envelope import ok
from errors import ApiError
from rollups import (
    containers_of_event,
    containers_of_manifest,
    manifest_invoice,
    manifests_of_event,
    refresh_world,
)
from store import clock_raw, new_row, ordered, set_and_touch, store, touch
from validation import (
    ALL_READ_ROLES,
    authorize,
    authorize_action,
    body,
    context,
    lookup,
    opt_str,
    req_enum,
    req_int,
    req_str,
    req_str_array,
)

bp = Blueprint("manifests", __name__)

MANIFEST_ACTION_ROLES = {
    "SIGN": ["ProgramAdmin"],
    "RECEIVE": ["ProgramAdmin"],
    "REJECT": ["ProgramAdmin"],
    "SHIP": ["PackingContractor"],
    "REOPEN": ["PackingContractor"],
}

MANIFEST_TRANSITIONS = {
    "SIGN": {"DRAFT": "SIGNED"},
    "SHIP": {"SIGNED": "SHIPPED"},
    "RECEIVE": {"SHIPPED": "RECEIVED"},
    "REJECT": {"SHIPPED": "DISCREPANCY"},
    "REOPEN": {"DISCREPANCY": "DRAFT"},
}


@bp.post("/hhw/manifests")
def create_manifest():
    user_id, role = context()
    authorize(role, ["PackingContractor"])
    payload = body()
    event_id = req_str(payload, "event_id")
    tracking_number = req_str(payload, "manifest_tracking_number")
    tsdf_epa_id = req_str(payload, "tsdf_epa_id")
    container_ids = req_str_array(payload, "container_ids")
    expected_event_version = req_int(payload, "expected_event_version")

    event = lookup("event", event_id)                                   # rung 5
    containers = [lookup("container", cid) for cid in container_ids]

    for existing in store.manifests.values():
        if existing["manifest_tracking_number"] == tracking_number:
            raise ApiError("ERR_INVALID_REQUEST",
                           "manifest_tracking_number must be unique.")

    if expected_event_version != event["version"]:                      # rung 8
        raise ApiError("ERR_STALE_VERSION")

    for container in containers:                                        # rung 13
        if container["status"] != "SEALED" or container["manifest_id"] is not None:
            raise ApiError("ERR_CONTAINER_NOT_SEALED")

    program = store.programs.get(event["program_id"])
    gate_frozen(program)                                                # rung 14

    for container in containers:                                       # rung 21
        if container["event_id"] != event["id"]:
            raise ApiError("ERR_CONTAINER_EVENT_MISMATCH")

    row = new_row({
        "event_id": event["id"],
        "manifest_tracking_number": tracking_number,
        "tsdf_epa_id": tsdf_epa_id,
        "status": "DRAFT",
        "container_ids": [],
        "net_weight_kg": ZERO,
        "estimated_disposal_cost_cents": 0,
        "blended_rate_cents_per_kg": Decimal("0"),
        "invoiced_disposal_cost_cents": 0,
        "prepared_by_user_id": user_id,
        "signed_by_user_id": None,
        "signed_at_utc": None,
        "discrepancy_code": None,
        "superseded_by_manifest_id": None,
    })
    store.manifests[row["id"]] = row

    for container in ordered(containers):
        set_and_touch(container, status="MANIFESTED", manifest_id=row["id"],
                      discrepancy_flag=False)

    # Supersede any other DRAFT manifest already open on this event.
    for other in ordered(manifests_of_event(event["id"])):
        if other["id"] == row["id"] or other["status"] != "DRAFT":
            continue
        set_and_touch(other, status="VOIDED", superseded_by_manifest_id=row["id"])
        for container in ordered(containers_of_manifest(other["id"])):
            set_and_touch(container, status="SEALED", manifest_id=None)

    touch(event)
    refresh_world()
    return ok(serializers.manifest(row), 201)


@bp.get("/hhw/manifests")
def list_manifests():
    user_id, role = context()
    authorize(role, ALL_READ_ROLES)
    filters = {
        "event_id": request.args.get("event_id"),
        "status": request.args.get("status"),
        "superseded_by_manifest_id": request.args.get("superseded_by_manifest_id"),
    }
    return list_response(request.args, list(store.manifests.values()),
                         serializers.manifest, filters)


@bp.get("/hhw/manifests/<manifest_id>")
def read_manifest(manifest_id):
    user_id, role = context()
    authorize(role, ALL_READ_ROLES)
    return ok(serializers.manifest(lookup("manifest", manifest_id)))


@bp.post("/hhw/manifests/<manifest_id>/transitions")
def manifest_transition(manifest_id):
    user_id, role = context()
    authorize(role, ["ProgramAdmin", "PackingContractor"])
    payload = body()
    action = payload.get("action")
    authorize_action(role, action, MANIFEST_ACTION_ROLES)
    action = req_enum(payload, "action", list(MANIFEST_TRANSITIONS.keys()))
    opt_str(payload, "invoice_reference")
    discrepancy_code = None
    if action == "REJECT":
        discrepancy_code = req_str(payload, "discrepancy_code")

    manifest = lookup("manifest", manifest_id)
    target = MANIFEST_TRANSITIONS[action].get(manifest["status"])        # rung 9
    if target is None:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    containers = ordered(containers_of_manifest(manifest["id"]))

    if action == "SIGN":
        if not containers:
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "The manifest carries no container.")
        for container in containers:
            if container["status"] != "MANIFESTED":
                raise ApiError("ERR_INVALID_STATE_TRANSITION",
                               "Every container must be manifested.")
        set_and_touch(manifest, status="SIGNED", signed_by_user_id=user_id,
                      signed_at_utc=clock_raw())

    elif action == "SHIP":
        set_and_touch(manifest, status="SHIPPED")
        for container in containers:
            set_and_touch(container, status="SHIPPED")

    elif action == "RECEIVE":
        net, blended, invoiced = manifest_invoice(manifest)
        set_and_touch(manifest, status="RECEIVED", net_weight_kg=net,
                      blended_rate_cents_per_kg=blended,
                      invoiced_disposal_cost_cents=invoiced)
        for container in containers:
            set_and_touch(container, status="DISPOSED")

    elif action == "REJECT":
        set_and_touch(manifest, status="DISCREPANCY",
                      discrepancy_code=discrepancy_code)
        for container in containers:
            set_and_touch(container, status="SEALED", manifest_id=None,
                          discrepancy_flag=True)

    else:  # REOPEN
        event_containers = ordered(containers_of_event(manifest["event_id"]))
        candidates = [c for c in event_containers
                      if c["discrepancy_flag"] and c["status"] == "SEALED"
                      and c["manifest_id"] is None]
        if not candidates:
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "No flagged container is available to re-attach.")
        set_and_touch(manifest, status="DRAFT", discrepancy_code=None,
                      signed_by_user_id=None, signed_at_utc=None)
        for container in candidates:
            set_and_touch(container, status="MANIFESTED",
                          manifest_id=manifest["id"], discrepancy_flag=False)

    refresh_world()
    return ok(serializers.manifest(manifest))
