from datetime import timedelta

from flask import Blueprint, request

from db import STORE, CLOCK, next_seq, new_id, bump, fmt_ts, parse_ts
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND,
                    ERR_KEY_HIERARCHY_INVALID, ERR_CROSS_BUILDING_REFERENCE)
from middleware import authenticate, require_roles, body
from response import ok_object, paginate
from serializers import ser_building, ser_key_node
from validators import (get_or_404, req_str, opt_int, opt_hhmm, opt_str,
                        req_enum)
from services import (LEVEL_DEPTH, LEVELS, cred_sort_key,
                      deactivate_credential, create_incident)

bp = Blueprint("core", __name__)

ALL_ROLES = ["SecurityAdmin", "SecurityOfficer", "FrontDesk", "Resident",
             "Vendor"]
STAFF_ROLES = ["SecurityAdmin", "SecurityOfficer", "FrontDesk"]


# ------------------------------------------------------------------- clock
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    ctx = authenticate()
    require_roles(ctx, ["SecurityAdmin"])
    b = body()
    dt = parse_ts(b.get("to_iso8601"))
    if dt is None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Missing or invalid to_iso8601")
    CLOCK.set(dt)
    return ok_object({"current_utc": fmt_ts(CLOCK.now())})


# --------------------------------------------------------------- buildings
@bp.route("/buildings", methods=["POST"])
def create_building():
    ctx = authenticate()
    require_roles(ctx, ["SecurityAdmin"])
    b = body()
    name = req_str(b, "name")
    open_utc = opt_hhmm(b, "business_open_utc", "08:00")
    close_utc = opt_hhmm(b, "business_close_utc", "18:00")
    now = CLOCK.now()
    bld = {
        "id": new_id(),
        "name": name,
        "audit_retention_days": opt_int(b, "audit_retention_days", 90),
        "alert_escalation_minutes": opt_int(b, "alert_escalation_minutes", 30),
        "vendor_badge_pool_max": opt_int(b, "vendor_badge_pool_max", 10),
        "default_propped_threshold_seconds":
            opt_int(b, "default_propped_threshold_seconds", 120),
        "base_fee_cents": opt_int(b, "base_fee_cents", 15000),
        "per_door_fee_cents": opt_int(b, "per_door_fee_cents", 7500),
        "per_key_reissue_fee_cents":
            opt_int(b, "per_key_reissue_fee_cents", 2500),
        "emergency_surcharge_pct": opt_int(b, "emergency_surcharge_pct", 20),
        "business_open_utc": open_utc,
        "business_close_utc": close_utc,
        "ops_run_index": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    STORE["buildings"][bld["id"]] = bld
    return ok_object(ser_building(bld), 201)


@bp.route("/buildings/<buildingId>", methods=["GET"])
def get_building(buildingId):
    ctx = authenticate()
    require_roles(ctx, ALL_ROLES)
    bld = get_or_404("buildings", buildingId, "Building")
    return ok_object(ser_building(bld))


@bp.route("/buildings/<buildingId>/run-ops", methods=["POST"])
def run_ops(buildingId):
    ctx = authenticate()
    require_roles(ctx, ["SecurityAdmin", "SecurityOfficer"])
    bld = get_or_404("buildings", buildingId, "Building")
    now = CLOCK.now()

    # Duty 1: vendor expiry sweep (created_at ASC, serial_no ASC)
    expired = 0
    creds = [c for c in STORE["credentials"].values()
             if c["building_id"] == buildingId]
    for c in sorted(creds, key=cred_sort_key):
        if (c["status"] == "ISSUED" and c["expires_at"] is not None
                and now >= c["expires_at"]):
            deactivate_credential(c, "EXPIRED")
            expired += 1

    # Duty 2: propped-door check (door_code ASC); strictly greater duration
    propped = 0
    doors = [d for d in STORE["doors"].values()
             if d["building_id"] == buildingId]
    for d in sorted(doors, key=lambda x: x["door_code"]):
        if d["open_since"] is None:
            continue
        duration = (now - d["open_since"]).total_seconds()
        if duration <= d["propped_threshold_seconds"]:
            continue
        has_live_alert = any(
            a["door_id"] == d["id"] and a["status"] in ("OPEN", "ACKNOWLEDGED")
            for a in STORE["propped_alerts"].values())
        if has_live_alert:
            continue
        alert = {
            "id": new_id(),
            "building_id": buildingId,
            "door_id": d["id"],
            "opened_at": d["open_since"],
            "status": "OPEN",
            "resolved_reason": None,
            "incident_id": None,
            "seq": next_seq(buildingId, "propped_alerts"),
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        STORE["propped_alerts"][alert["id"]] = alert
        propped += 1

    # Duty 3: stale OPEN alert escalation (now - created_at > escalation mins)
    escalated = 0
    alerts = [a for a in STORE["propped_alerts"].values()
              if a["building_id"] == buildingId and a["status"] == "OPEN"]
    for a in sorted(alerts, key=lambda x: (x["created_at"], x["seq"])):
        if now - a["created_at"] > timedelta(
                minutes=bld["alert_escalation_minutes"]):
            inc = create_incident(buildingId, "PROPPED_DOOR",
                                  door_id=a["door_id"], alert_id=a["id"])
            a["status"] = "ESCALATED"
            a["incident_id"] = inc["id"]
            bump(a)
            escalated += 1

    # Duty 4: retention archival (occurred_at strictly older than cutoff)
    archived_count = 0
    cutoff = now - timedelta(days=bld["audit_retention_days"])
    events = [e for e in STORE["access_events"].values()
              if e["building_id"] == buildingId]
    for e in sorted(events, key=lambda x: x["occurred_at"]):
        if not e["archived"] and e["occurred_at"] < cutoff:
            e["archived"] = True
            archived_count += 1

    # Duty 5: bump ops index
    bld["ops_run_index"] += 1
    bump(bld)
    return ok_object({
        "ops_run_index": bld["ops_run_index"],
        "vendor_credentials_expired": expired,
        "propped_alerts_created": propped,
        "alerts_escalated": escalated,
        "events_archived": archived_count,
    })


# --------------------------------------------------------------- key nodes
@bp.route("/key-nodes", methods=["POST"])
def create_key_node():
    ctx = authenticate()
    require_roles(ctx, ["SecurityAdmin"])
    b = body()
    building_id = req_str(b, "building_id")
    level = req_enum(b, "level", LEVELS)
    label = req_str(b, "label")
    parent_id = opt_str(b, "parent_id")
    get_or_404("buildings", building_id, "Building")
    parent = None
    if parent_id is not None:
        parent = get_or_404("key_nodes", parent_id, "KeyNode")
    if parent is not None:
        if parent["building_id"] != building_id:
            raise ApiError(ERR_CROSS_BUILDING_REFERENCE, 422,
                           "parent_id belongs to a different building")
        # Adjacency along GRAND_MASTER -> MASTER -> SUB_MASTER -> CHANGE.
        # The child must sit below the parent; skipping a single intermediate
        # level (e.g. MASTER -> CHANGE) is tolerated, while a two-level skip
        # (GRAND_MASTER -> CHANGE) violates the hierarchy.
        diff = LEVEL_DEPTH[level] - LEVEL_DEPTH[parent["level"]]
        if diff < 1 or diff > 2:
            raise ApiError(ERR_KEY_HIERARCHY_INVALID, 422,
                           "Parent level must be exactly one step above")
    else:
        if level not in ("GRAND_MASTER", "MASTER"):
            raise ApiError(ERR_KEY_HIERARCHY_INVALID, 422,
                           "Root node level must be GRAND_MASTER or MASTER")
    now = CLOCK.now()
    node = {
        "id": new_id(),
        "building_id": building_id,
        "parent_id": parent_id,
        "level": level,
        "label": label,
        "status": "ACTIVE",
        "supersedes_node_id": None,
        "seq": next_seq(building_id, "key_nodes"),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    STORE["key_nodes"][node["id"]] = node
    return ok_object(ser_key_node(node), 201)


@bp.route("/key-nodes", methods=["GET"])
def list_key_nodes():
    ctx = authenticate()
    require_roles(ctx, STAFF_ROLES)
    args = request.args
    rows = list(STORE["key_nodes"].values())
    for f in ("building_id", "parent_id", "status", "supersedes_node_id"):
        v = args.get(f)
        if v is not None:
            rows = [r for r in rows if r[f] == v]
    return paginate(rows, args, ser_key_node)


@bp.route("/key-nodes/<keyNodeId>", methods=["GET"])
def get_key_node(keyNodeId):
    ctx = authenticate()
    require_roles(ctx, STAFF_ROLES)
    node = get_or_404("key_nodes", keyNodeId, "KeyNode")
    return ok_object(ser_key_node(node))
