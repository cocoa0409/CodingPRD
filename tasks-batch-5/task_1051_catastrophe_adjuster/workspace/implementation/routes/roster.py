from flask import Blueprint, request

from core import (
    require_ctx, ALL_ROLES, get_body, require_fields, require_enum, require_str,
    require_int, respond_object, list_response, fetch, base_record, touch, DB,
    current_clock, parse_dt, ApiError,
)

bp = Blueprint("roster", __name__)

CAT_PERIL_TYPES = {"HURRICANE", "FLOOD", "WILDFIRE", "TORNADO", "HAIL", "WIND"}
ROSTER_SEAT_STATUSES = {"CONFIRMED", "ACTIVE"}


# ---------------------------------------------------------------------------
# CatEvent
# ---------------------------------------------------------------------------
@bp.route("/cat-events", methods=["POST"])
def create_cat_event():
    require_ctx({"LicensingAdmin"})
    body = get_body()
    require_fields(body, ["name", "peril_type", "affected_states", "roster_capacity"])
    require_str(body["name"], "name")
    require_enum(body["peril_type"], CAT_PERIL_TYPES, "peril_type")
    if not isinstance(body["affected_states"], list) or not all(isinstance(s, str) for s in body["affected_states"]):
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid affected_states")
    require_int(body["roster_capacity"], "roster_capacity", minimum=1)
    rec = base_record()
    rec.update({
        "name": body["name"],
        "peril_type": body["peril_type"],
        "affected_states": body["affected_states"],
        "roster_capacity": body["roster_capacity"],
        "roster_filled_count": 0,
        "status": "OPEN",
    })
    DB["cat_events"][rec["id"]] = rec
    return respond_object(rec, status=201)


@bp.route("/cat-events", methods=["GET"])
def list_cat_events():
    require_ctx(ALL_ROLES)
    return list_response("cat_events", {
        "status": request.args.get("status"),
        "peril_type": request.args.get("peril_type"),
    })


@bp.route("/cat-events/<rid>", methods=["GET"])
def get_cat_event(rid):
    require_ctx(ALL_ROLES)
    return respond_object(fetch("cat_events", rid, "ERR_CAT_EVENT_NOT_FOUND"))


@bp.route("/cat-events/<rid>/close", methods=["POST"])
def close_cat_event(rid):
    require_ctx({"LicensingAdmin"})
    ev = fetch("cat_events", rid, "ERR_CAT_EVENT_NOT_FOUND")
    if ev["status"] != "OPEN":
        raise ApiError("ERR_CAT_EVENT_NOT_OPEN", 409)
    for d in DB["deployments"].values():
        if d["cat_event_id"] == rid and d["status"] in ROSTER_SEAT_STATUSES:
            raise ApiError("ERR_ROSTER_NOT_EMPTY", 409)
    ev["status"] = "CLOSED"
    touch(ev)
    return respond_object(ev)


# ---------------------------------------------------------------------------
# Deployment
# ---------------------------------------------------------------------------
@bp.route("/deployments", methods=["POST"])
def create_deployment():
    require_ctx({"LicensingAdmin"})
    body = get_body()
    require_fields(body, ["adjuster_id", "cat_event_id", "start_at", "end_at"])
    fetch("adjusters", body["adjuster_id"], "ERR_ADJUSTER_NOT_FOUND")
    fetch("cat_events", body["cat_event_id"], "ERR_CAT_EVENT_NOT_FOUND")
    try:
        start = parse_dt(body["start_at"])
        end = parse_dt(body["end_at"])
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid datetime")
    if not start < end:
        raise ApiError("ERR_INVALID_REQUEST", 400, "start_at must be before end_at")
    rec = base_record()
    rec.update({
        "adjuster_id": body["adjuster_id"],
        "cat_event_id": body["cat_event_id"],
        "start_at": body["start_at"],
        "end_at": body["end_at"],
        "status": "REQUESTED",
    })
    rec["_start_dt"] = start
    rec["_end_dt"] = end
    DB["deployments"][rec["id"]] = rec
    return respond_object(rec, status=201)


@bp.route("/deployments", methods=["GET"])
def list_deployments():
    require_ctx(ALL_ROLES)
    return list_response("deployments", {
        "adjuster_id": request.args.get("adjuster_id"),
        "cat_event_id": request.args.get("cat_event_id"),
        "status": request.args.get("status"),
    })


@bp.route("/deployments/<rid>", methods=["GET"])
def get_deployment(rid):
    require_ctx(ALL_ROLES)
    return respond_object(fetch("deployments", rid, "ERR_DEPLOYMENT_NOT_FOUND"))


def _overlaps(a_start, a_end, b_start, b_end):
    # half-open [start, end): overlap iff they share an interior instant.
    return a_start < b_end and b_start < a_end


@bp.route("/deployments/<rid>/confirm", methods=["POST"])
def confirm_deployment(rid):
    require_ctx({"LicensingAdmin"})
    dep = fetch("deployments", rid, "ERR_DEPLOYMENT_NOT_FOUND")
    if dep["status"] != "REQUESTED":
        raise ApiError("ERR_DEPLOYMENT_NOT_REQUESTED", 409)
    ev = DB["cat_events"][dep["cat_event_id"]]
    if ev["status"] != "OPEN":
        raise ApiError("ERR_CAT_EVENT_NOT_OPEN", 409)
    # Overlap (same adjuster, CONFIRMED/ACTIVE) is checked BEFORE capacity.
    for other in DB["deployments"].values():
        if other["id"] == rid:
            continue
        if other["adjuster_id"] != dep["adjuster_id"]:
            continue
        if other["status"] not in ROSTER_SEAT_STATUSES:
            continue
        if _overlaps(dep["_start_dt"], dep["_end_dt"], other["_start_dt"], other["_end_dt"]):
            raise ApiError("ERR_DEPLOYMENT_WINDOW_OVERLAP", 409)
    if ev["roster_filled_count"] >= ev["roster_capacity"]:
        raise ApiError("ERR_ROSTER_CAPACITY_EXCEEDED", 409)
    dep["status"] = "CONFIRMED"
    touch(dep)
    ev["roster_filled_count"] += 1
    touch(ev)
    return respond_object(dep)


@bp.route("/deployments/<rid>/activate", methods=["POST"])
def activate_deployment(rid):
    require_ctx({"LicensingAdmin"})
    dep = fetch("deployments", rid, "ERR_DEPLOYMENT_NOT_FOUND")
    if dep["status"] != "CONFIRMED":
        raise ApiError("ERR_DEPLOYMENT_NOT_CONFIRMED", 409)
    now = current_clock()
    if not (dep["_start_dt"] <= now < dep["_end_dt"]):
        raise ApiError("ERR_DEPLOYMENT_WINDOW_NOT_OPEN", 409)
    dep["status"] = "ACTIVE"
    touch(dep)
    return respond_object(dep)


@bp.route("/deployments/<rid>/complete", methods=["POST"])
def complete_deployment(rid):
    require_ctx({"LicensingAdmin"})
    dep = fetch("deployments", rid, "ERR_DEPLOYMENT_NOT_FOUND")
    if dep["status"] != "ACTIVE":
        raise ApiError("ERR_DEPLOYMENT_NOT_ACTIVE", 409)
    dep["status"] = "COMPLETED"
    touch(dep)
    ev = DB["cat_events"][dep["cat_event_id"]]
    ev["roster_filled_count"] -= 1
    touch(ev)
    return respond_object(dep)


@bp.route("/deployments/<rid>/withdraw", methods=["POST"])
def withdraw_deployment(rid):
    require_ctx({"LicensingAdmin"})
    dep = fetch("deployments", rid, "ERR_DEPLOYMENT_NOT_FOUND")
    if dep["status"] not in {"REQUESTED", "CONFIRMED", "ACTIVE"}:
        raise ApiError("ERR_DEPLOYMENT_NOT_WITHDRAWABLE", 409)
    held_seat = dep["status"] in ROSTER_SEAT_STATUSES
    dep["status"] = "WITHDRAWN"
    touch(dep)
    if held_seat:
        ev = DB["cat_events"][dep["cat_event_id"]]
        ev["roster_filled_count"] -= 1
        touch(ev)
    return respond_object(dep)
