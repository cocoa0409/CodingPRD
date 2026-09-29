"""Capacity clusters and live-event operations (PRD 3.3)."""
from flask import Blueprint, request

import config
import db
import resolve
import validators as v
from db import ordered, serialize
from errors import fail
from middleware import authenticate
from response import list_response, object_response, touch
from services import calc

bp = Blueprint("capacity", __name__)

READ_ROLES = (
    config.ROLE_CONTENT_PRODUCER,
    config.ROLE_ECONOMY_DESIGNER,
    config.ROLE_LIVEOPS_COMMANDER,
    config.ROLE_COMPLIANCE_OFFICER,
)


# ---------------------------------------------------------------------------
# Capacity clusters
# ---------------------------------------------------------------------------
@bp.post("/capacity-clusters")
def create_cluster():
    authenticate(config.ROLE_LIVEOPS_COMMANDER)
    payload = v.body()
    name = v.req_string(payload, "name")
    region_code = v.req_enum(payload, "region_code", config.REGION_CODES)
    ccu_capacity = v.req_int(payload, "ccu_capacity", minimum=1)
    buffer_minutes = v.opt_int(
        payload, "maintenance_buffer_minutes", default=30, minimum=0, maximum=240
    )
    cluster = db.insert(
        db.db.clusters,
        {
            "name": name,
            "region_code": region_code,
            "ccu_capacity": ccu_capacity,
            "maintenance_buffer_minutes": buffer_minutes,
            "status": "ACTIVE",
            "reserved_ccu": 0,
        },
    )
    return object_response(serialize(cluster), 201)


@bp.get("/capacity-clusters/<cluster_id>")
def read_cluster(cluster_id):
    authenticate(*READ_ROLES)
    cluster = resolve.cluster(cluster_id)
    return object_response(serialize(cluster))


@bp.post("/capacity-clusters/<cluster_id>/status")
def cluster_status(cluster_id):
    authenticate(config.ROLE_LIVEOPS_COMMANDER)
    cluster = resolve.cluster(cluster_id)
    payload = v.body()
    to_status = v.req_enum(payload, "to_status", config.CLUSTER_STATUSES)

    current = cluster["status"]
    if current == "ACTIVE" and to_status == "DRAINING":
        cluster["status"] = "DRAINING"
    elif current == "DRAINING" and to_status == "ACTIVE":
        cluster["status"] = "ACTIVE"
    elif current == "DRAINING" and to_status == "RETIRED":
        if cluster["reserved_ccu"] != 0:
            fail("ERR_CLUSTER_INVALID_STATE", "The cluster still holds reservations.")
        cluster["status"] = "RETIRED"
    else:
        fail("ERR_CLUSTER_INVALID_STATE", "That transition does not exist from the current status.")
    touch(cluster)
    return object_response(serialize(cluster))


# ---------------------------------------------------------------------------
# Live events
# ---------------------------------------------------------------------------
@bp.post("/live-events")
def create_live_event():
    authenticate(config.ROLE_CONTENT_PRODUCER)
    payload = v.body()
    season = resolve.body_fk(payload, "season_id", db.db.seasons, "ERR_SEASON_NOT_FOUND")
    cluster = resolve.body_fk(
        payload, "capacity_cluster_id", db.db.clusters, "ERR_CLUSTER_NOT_FOUND"
    )
    v.req_string(payload, "season_id")
    v.req_string(payload, "capacity_cluster_id")
    code = v.req_string(payload, "code")
    window_start = v.req_datetime(payload, "window_start")
    window_end = v.req_datetime(payload, "window_end")
    if window_end <= window_start:
        v.bad("window_end", "must be strictly after window_start")
    forecast_ccu = v.req_int(payload, "forecast_ccu", minimum=1)

    for existing in db.db.live_events.values():
        if existing["season_id"] == season["id"] and existing["code"] == code:
            fail("ERR_EVENT_CODE_DUPLICATE", "An event with this code already exists in the season.")

    event = db.insert(
        db.db.live_events,
        {
            "season_id": season["id"],
            "capacity_cluster_id": cluster["id"],
            "code": code,
            "window_start": window_start,
            "window_end": window_end,
            "forecast_ccu": forecast_ccu,
            "status": "PLANNED",
            "reserved_ccu_at_approval": 0,
            "rollback_reason": None,
        },
    )
    return object_response(serialize(event), 201)


@bp.get("/live-events/<event_id>")
def read_live_event(event_id):
    authenticate(*READ_ROLES)
    event = resolve.live_event(event_id)
    return object_response(serialize(event))


@bp.get("/live-events")
def list_live_events():
    authenticate(*READ_ROLES)
    season_id = request.args.get("season_id")
    cluster_id = request.args.get("capacity_cluster_id")
    status = v.query_enum("status", config.EVENT_STATUSES)
    limit, offset = v.pagination()
    rows = list(db.db.live_events.values())
    if season_id is not None:
        rows = [e for e in rows if e["season_id"] == season_id]
    if cluster_id is not None:
        rows = [e for e in rows if e["capacity_cluster_id"] == cluster_id]
    if status is not None:
        rows = [e for e in rows if e["status"] == status]
    records = [serialize(e) for e in ordered(rows)]
    page, total = v.paginate(records, limit, offset)
    return list_response(page, limit, offset, total)


@bp.post("/live-events/<event_id>/approve")
def approve_live_event(event_id):
    authenticate(config.ROLE_LIVEOPS_COMMANDER)
    event = resolve.live_event(event_id)
    season = db.db.seasons.get(event["season_id"])
    cluster = db.db.clusters.get(event["capacity_cluster_id"])

    if event["status"] != "PLANNED":
        fail("ERR_EVENT_INVALID_STATE", "Only a PLANNED event can be approved.")
    if season["status"] != "LIVE":
        fail("ERR_SEASON_NOT_LIVE", "The season must be LIVE to approve an event.")
    if cluster["status"] != "ACTIVE":
        fail("ERR_CLUSTER_NOT_ACTIVE", "The capacity cluster is not ACTIVE.")
    if db.now() >= event["window_end"]:
        fail("ERR_EVENT_INVALID_STATE", "The event window has already closed.")
    if calc.cluster_overlap_load(cluster, event) > cluster["ccu_capacity"]:
        fail("ERR_CLUSTER_CAPACITY_EXCEEDED", "The cluster has insufficient headroom.")

    event["status"] = "APPROVED"
    event["reserved_ccu_at_approval"] = event["forecast_ccu"]
    touch(event)
    cluster["reserved_ccu"] += event["forecast_ccu"]
    touch(cluster)
    return object_response(serialize(event))


@bp.post("/live-events/<event_id>/start")
def start_live_event(event_id):
    authenticate(config.ROLE_LIVEOPS_COMMANDER)
    event = resolve.live_event(event_id)
    cluster = db.db.clusters.get(event["capacity_cluster_id"])

    if event["status"] != "APPROVED":
        fail("ERR_EVENT_INVALID_STATE", "Only an APPROVED event can be started.")
    if db.now() < event["window_start"]:
        fail("ERR_EVENT_INVALID_STATE", "The event window has not opened yet.")
    if cluster["status"] not in ("ACTIVE", "DRAINING"):
        fail("ERR_CLUSTER_NOT_ACTIVE", "The capacity cluster is RETIRED.")

    event["status"] = "RUNNING"
    touch(event)
    return object_response(serialize(event))


@bp.post("/live-events/<event_id>/complete")
def complete_live_event(event_id):
    authenticate(config.ROLE_LIVEOPS_COMMANDER)
    event = resolve.live_event(event_id)
    if event["status"] != "RUNNING":
        fail("ERR_EVENT_INVALID_STATE", "Only a RUNNING event can be completed.")
    event["status"] = "COMPLETED"
    _release_reservation(event)
    touch(event)
    return object_response(serialize(event))


@bp.post("/live-events/<event_id>/rollback")
def rollback_live_event(event_id):
    authenticate(config.ROLE_LIVEOPS_COMMANDER)
    event = resolve.live_event(event_id)
    payload = v.body()
    reason = v.req_string(payload, "reason")
    if event["status"] not in ("APPROVED", "RUNNING"):
        fail("ERR_EVENT_INVALID_STATE", "Only an APPROVED or RUNNING event can be rolled back.")
    event["status"] = "ROLLED_BACK"
    event["rollback_reason"] = reason
    _release_reservation(event)
    touch(event)
    return object_response(serialize(event))


def _release_reservation(event):
    cluster = db.db.clusters.get(event["capacity_cluster_id"])
    snapshot = event["reserved_ccu_at_approval"]
    event["reserved_ccu_at_approval"] = 0
    if cluster is not None:
        cluster["reserved_ccu"] = max(0, cluster["reserved_ccu"] - snapshot)
        touch(cluster)
