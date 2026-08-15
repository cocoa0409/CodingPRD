from flask import Blueprint, request

from db import STORE, CLOCK, next_seq, new_id, bump, fmt_ts, is_int
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_STALE_VERSION,
                    ERR_KEY_HIERARCHY_INVALID, ERR_CROSS_BUILDING_REFERENCE,
                    ERR_DOOR_CODE_EXISTS)
from middleware import authenticate, require_roles, body
from response import ok_object, paginate
from serializers import ser_door, ser_access_event
from validators import get_or_404, req_str, opt_str
from services import access_decision

bp = Blueprint("doors", __name__)

STAFF_ROLES = ["SecurityAdmin", "SecurityOfficer", "FrontDesk"]


@bp.route("/doors", methods=["POST"])
def create_door():
    ctx = authenticate()
    require_roles(ctx, ["SecurityAdmin"])
    b = body()
    building_id = req_str(b, "building_id")
    door_code = req_str(b, "door_code")
    key_node_id = req_str(b, "key_node_id")
    bitting_code = opt_str(b, "bitting_code") or "STANDARD"
    threshold = b.get("propped_threshold_seconds")
    if threshold is not None and (not is_int(threshold) or threshold < 1):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "propped_threshold_seconds must be an integer >= 1")
    bld = get_or_404("buildings", building_id, "Building")
    node = get_or_404("key_nodes", key_node_id, "KeyNode")
    if node["building_id"] != building_id:
        raise ApiError(ERR_CROSS_BUILDING_REFERENCE, 422,
                       "key_node_id belongs to a different building")
    if any(d["building_id"] == building_id and d["door_code"] == door_code
           for d in STORE["doors"].values()):
        raise ApiError(ERR_DOOR_CODE_EXISTS, 422,
                       "door_code already used in this building")
    if node["level"] != "CHANGE":
        raise ApiError(ERR_KEY_HIERARCHY_INVALID, 422,
                       "Doors pin to CHANGE-level nodes only")
    if threshold is None:
        threshold = bld["default_propped_threshold_seconds"]
    now = CLOCK.now()
    door = {
        "id": new_id(),
        "building_id": building_id,
        "door_code": door_code,
        "key_node_id": key_node_id,
        "bitting_code": bitting_code,
        "hardware_status": "OPERATIONAL",
        "core_status": "ACTIVE",
        "open_since": None,
        "propped_threshold_seconds": threshold,
        "seq": next_seq(building_id, "doors"),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    STORE["doors"][door["id"]] = door
    return ok_object(ser_door(door), 201)


@bp.route("/doors", methods=["GET"])
def list_doors():
    ctx = authenticate()
    require_roles(ctx, STAFF_ROLES)
    args = request.args
    rows = list(STORE["doors"].values())
    for f in ("building_id", "key_node_id", "hardware_status", "core_status"):
        v = args.get(f)
        if v is not None:
            rows = [r for r in rows if r[f] == v]
    return paginate(rows, args, ser_door)


@bp.route("/doors/<doorId>", methods=["GET"])
def get_door(doorId):
    ctx = authenticate()
    require_roles(ctx, STAFF_ROLES)
    door = get_or_404("doors", doorId, "Door")
    return ok_object(ser_door(door))


@bp.route("/doors/<doorId>", methods=["PATCH"])
def patch_door(doorId):
    ctx = authenticate()
    require_roles(ctx, ["SecurityAdmin"])
    door = get_or_404("doors", doorId, "Door")
    b = body()
    expected = b.get("expected_door_version")
    if not is_int(expected):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "expected_door_version is required")
    if expected != door["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_door_version does not match current version")
    if "propped_threshold_seconds" in b and b["propped_threshold_seconds"] is not None:
        v = b["propped_threshold_seconds"]
        if not is_int(v) or v < 1:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "propped_threshold_seconds must be an integer >= 1")
        door["propped_threshold_seconds"] = v
    bump(door)
    return ok_object(ser_door(door))


@bp.route("/doors/<doorId>/close", methods=["POST"])
def close_door(doorId):
    ctx = authenticate()
    require_roles(ctx, ["SecurityOfficer", "FrontDesk", "SecurityAdmin"])
    door = get_or_404("doors", doorId, "Door")
    if door["open_since"] is not None:
        door["open_since"] = None
        bump(door)
    for a in STORE["propped_alerts"].values():
        if (a["door_id"] == door["id"]
                and a["status"] in ("OPEN", "ACKNOWLEDGED")):
            a["status"] = "RESOLVED"
            a["resolved_reason"] = "DOOR_CLOSED"
            bump(a)
    return ok_object(ser_door(door))


@bp.route("/doors/<doorId>/access-checks", methods=["POST"])
def access_check(doorId):
    ctx = authenticate()
    require_roles(ctx, STAFF_ROLES)
    door = get_or_404("doors", doorId, "Door")
    b = body()
    credential_id = req_str(b, "credential_id")
    mode = b.get("mode")
    if mode not in ("RECORDED", "SIMULATED"):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "mode must be RECORDED or SIMULATED")
    cred = STORE["credentials"].get(credential_id)
    if cred is None:
        from errors import ERR_NOT_FOUND
        raise ApiError(ERR_NOT_FOUND, 404, "Credential not found")
    now = CLOCK.now()
    outcome = access_decision(cred, door, now)
    event_id = None
    if mode == "RECORDED":
        evt = {
            "id": new_id(),
            "building_id": door["building_id"],
            "credential_id": cred["id"],
            "door_id": door["id"],
            "occurred_at": now,
            "outcome": outcome,
            "archived": False,
            "seq": next_seq(door["building_id"], "access_events"),
            "created_at": now,
        }
        STORE["access_events"][evt["id"]] = evt
        event_id = evt["id"]
        if outcome == "GRANTED" and door["open_since"] is None:
            door["open_since"] = now
            bump(door)
    return ok_object({
        "outcome": outcome,
        "credential_id": cred["id"],
        "door_id": door["id"],
        "evaluated_at": fmt_ts(now),
        "access_event_id": event_id,
    })


# ------------------------------------------------------------ access events
@bp.route("/access-events", methods=["GET"])
def list_access_events():
    ctx = authenticate()
    require_roles(ctx, ["SecurityAdmin", "SecurityOfficer"])
    args = request.args
    include_archived = (args.get("include_archived", "false").lower()
                        in ("true", "1", "yes"))
    rows = list(STORE["access_events"].values())
    if not include_archived:
        rows = [e for e in rows if not e["archived"]]
    for f in ("building_id", "credential_id", "door_id", "outcome"):
        v = args.get(f)
        if v is not None:
            rows = [r for r in rows if r[f] == v]
    return paginate(rows, args, ser_access_event)


@bp.route("/access-events/<accessEventId>", methods=["GET"])
def get_access_event(accessEventId):
    ctx = authenticate()
    require_roles(ctx, ["SecurityAdmin", "SecurityOfficer"])
    evt = get_or_404("access_events", accessEventId, "AccessEvent")
    return ok_object(ser_access_event(evt))
