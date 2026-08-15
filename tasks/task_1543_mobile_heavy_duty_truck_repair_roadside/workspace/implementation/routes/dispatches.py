"""Dispatch endpoints: create (OCC-guarded), accept/reject/depart/arrive/
complete/release."""
from flask import Blueprint, request

from db import store, new_record, touch
from errors import (ApiError, err_not_found, err_invalid_state,
                    err_forbidden_ownership, err_stale_version, err_validation)
from middleware import auth
from response import success
from serializers import serialize
from services.cascades import (append_event, free_technician, wall_now,
                               revert_call_if_no_active_dispatch,
                               has_active_dispatch)
from routes.service_calls import (get_call_or_404, ensure_not_cancelled,
                                  fleet_gate_active)
from util import Field, validate_body, parse_pagination, paginate

bp = Blueprint("dispatches", __name__)

READ_ROLES = ["OpsAdmin", "Dispatcher", "Technician"]
ACTIVE_STATES = ("PROPOSED", "ACCEPTED", "EN_ROUTE", "ON_SITE")


def _get_dispatch(dispatch_id):
    d = store.dispatches.get(dispatch_id)
    if d is None:
        raise err_not_found("Dispatch not found")
    return d


def _require_own_dispatch(disp, uid):
    if disp["technician_id"] != uid:
        raise err_forbidden_ownership(
            "Actor is not the dispatch's assigned technician")


@bp.route("/roadside/service-calls/<serviceCallId>/dispatches",
          methods=["POST"])
def create_dispatch(serviceCallId):
    uid, role = auth(["Dispatcher", "OpsAdmin"])
    call = get_call_or_404(serviceCallId)
    vals = validate_body(request.get_json(silent=True), [
        Field("technician_id", "string", required=True),
        Field("window_start_at", "datetime", required=True),
        Field("window_end_at", "datetime", required=True),
        Field("planned_travel_miles", "int", required=True, min_val=0),
        Field("expected_service_call_version", "int", required=True),
    ])
    tech = store.technicians.get(vals["technician_id"])
    if tech is None:
        raise err_not_found("Technician not found")
    if vals["window_end_at"] <= vals["window_start_at"]:
        raise err_validation("window_end_at must be > window_start_at")
    ensure_not_cancelled(call)
    if call["status"] == "DISPATCHED":
        # A DISPATCHED call whose dispatches are all still PROPOSED may be
        # re-dispatched (the create supersedes them); an ACCEPTED / EN_ROUTE /
        # ON_SITE dispatch on the call refuses creation.
        for d in store.dispatches.values():
            if (d["service_call_id"] == call["id"]
                    and d["status"] in ("ACCEPTED", "EN_ROUTE", "ON_SITE")):
                raise ApiError("ERR_DISPATCH_ACTIVE",
                               "The call already has an active dispatch", 409)
    elif call["status"] != "TRIAGED":
        raise err_invalid_state("Dispatch create requires status TRIAGED")
    if vals["expected_service_call_version"] != call["version"]:
        raise err_stale_version()
    # certification gate
    req_cert = call.get("required_certification")
    if req_cert and req_cert != "ANY" and req_cert not in tech["certifications"]:
        raise ApiError("ERR_TECHNICIAN_NOT_CERTIFIED",
                       "Technician lacks the call's required certification", 409)
    # half-open window overlap on the technician's active dispatches
    ws, we = vals["window_start_at"], vals["window_end_at"]
    for d in store.dispatches.values():
        if (d["technician_id"] == tech["id"] and d["status"] in ACTIVE_STATES
                and ws < d["window_end_at"] and d["window_start_at"] < we):
            raise ApiError("ERR_DISPATCH_WINDOW_OVERLAP",
                           "Technician holds an overlapping dispatch window", 409)
    fleet_gate_active(call)
    # supersede prior PROPOSED dispatches of the call
    for d in store.dispatches.values():
        if d["service_call_id"] == call["id"] and d["status"] == "PROPOSED":
            d["status"] = "SUPERSEDED"
            touch(d, wall_now())
    rec = new_record()
    now = wall_now()
    rec.update({
        "_created": now, "_updated": now,
        "service_call_id": call["id"],
        "technician_id": tech["id"],
        "window_start_at": ws,
        "window_end_at": we,
        "planned_travel_miles": vals["planned_travel_miles"],
        "status": "PROPOSED",
        "departed_at": None,
        "arrived_at": None,
        "completed_at": None,
        "actual_travel_minutes": None,
        "actual_travel_miles": None,
        "rejection_reason": None,
        "release_reason": None,
    })
    store.dispatches[rec["id"]] = rec
    call["status"] = "DISPATCHED"
    touch(call, now)  # dispatch create increments the call's version
    append_event(call["id"], "DISPATCH_CREATED", role, uid)
    return success(serialize("dispatch", rec), status=201)


@bp.route("/roadside/dispatches/<dispatchId>", methods=["GET"])
def get_dispatch(dispatchId):
    auth(READ_ROLES)
    return success(serialize("dispatch", _get_dispatch(dispatchId)))


@bp.route("/roadside/dispatches", methods=["GET"])
def list_dispatches():
    auth(READ_ROLES)
    limit, offset = parse_pagination(request.args)
    call_f = request.args.get("service_call_id")
    tech_f = request.args.get("technician_id")
    status_f = request.args.get("status")
    items = sorted(store.dispatches.values(), key=lambda r: r["_seq"])
    if call_f is not None:
        items = [d for d in items if d["service_call_id"] == call_f]
    if tech_f is not None:
        items = [d for d in items if d["technician_id"] == tech_f]
    if status_f is not None:
        items = [d for d in items if d["status"] == status_f]
    page, total, has_more = paginate(items, limit, offset)
    return success([serialize("dispatch", d) for d in page],
                   response_type="array",
                   pagination={"limit": limit, "offset": offset,
                               "total_count": total, "has_more": has_more})


@bp.route("/roadside/dispatches/<dispatchId>/accept", methods=["POST"])
def accept(dispatchId):
    uid, role = auth(["Technician"])
    disp = _get_dispatch(dispatchId)
    _require_own_dispatch(disp, uid)
    if disp["status"] != "PROPOSED":
        raise err_invalid_state("Accept requires status PROPOSED")
    tech = store.technicians.get(disp["technician_id"])
    if tech is None or tech["status"] != "AVAILABLE":
        raise ApiError("ERR_TECHNICIAN_NOT_AVAILABLE",
                       "Technician is not AVAILABLE", 409)
    disp["status"] = "ACCEPTED"
    touch(disp, wall_now())
    tech["status"] = "ON_DISPATCH"
    tech["current_dispatch_id"] = disp["id"]
    touch(tech, wall_now())
    call = store.service_calls.get(disp["service_call_id"])
    if call is not None:
        append_event(call["id"], "DISPATCH_ACCEPTED", role, uid)
    return success(serialize("dispatch", disp))


@bp.route("/roadside/dispatches/<dispatchId>/reject", methods=["POST"])
def reject(dispatchId):
    uid, role = auth(["Technician"])
    disp = _get_dispatch(dispatchId)
    _require_own_dispatch(disp, uid)
    vals = validate_body(request.get_json(silent=True), [
        Field("reason", "string"),
    ])
    if disp["status"] != "PROPOSED":
        raise err_invalid_state("Reject requires status PROPOSED")
    disp["status"] = "REJECTED"
    disp["rejection_reason"] = vals.get("reason")
    touch(disp, wall_now())
    call = store.service_calls.get(disp["service_call_id"])
    if call is not None:
        revert_call_if_no_active_dispatch(call)
        append_event(call["id"], "DISPATCH_REJECTED", role, uid)
    return success(serialize("dispatch", disp))


@bp.route("/roadside/dispatches/<dispatchId>/depart", methods=["POST"])
def depart(dispatchId):
    uid, role = auth(["Technician"])
    disp = _get_dispatch(dispatchId)
    _require_own_dispatch(disp, uid)
    validate_body(request.get_json(silent=True), [])
    if disp["status"] != "ACCEPTED":
        raise err_invalid_state("Depart requires status ACCEPTED")
    disp["status"] = "EN_ROUTE"
    disp["departed_at"] = store.clock
    touch(disp, wall_now())
    call = store.service_calls.get(disp["service_call_id"])
    if call is not None and call["status"] == "DISPATCHED":
        call["status"] = "EN_ROUTE"
        touch(call, wall_now())
        append_event(call["id"], "DISPATCH_DEPARTED", role, uid)
    return success(serialize("dispatch", disp))


@bp.route("/roadside/dispatches/<dispatchId>/arrive", methods=["POST"])
def arrive(dispatchId):
    uid, role = auth(["Technician"])
    disp = _get_dispatch(dispatchId)
    _require_own_dispatch(disp, uid)
    vals = validate_body(request.get_json(silent=True), [
        Field("actual_travel_miles", "int", required=True, min_val=0),
    ])
    if disp["status"] != "EN_ROUTE":
        raise err_invalid_state("Arrive requires status EN_ROUTE")
    disp["arrived_at"] = store.clock
    disp["actual_travel_miles"] = vals["actual_travel_miles"]
    if disp.get("departed_at") is not None:
        elapsed = (disp["arrived_at"] - disp["departed_at"]).total_seconds()
        disp["actual_travel_minutes"] = int(elapsed // 60)
    else:
        disp["actual_travel_minutes"] = 0
    disp["status"] = "ON_SITE"
    touch(disp, wall_now())
    call = store.service_calls.get(disp["service_call_id"])
    if call is not None and call["status"] == "EN_ROUTE":
        call["status"] = "ON_SITE"
        touch(call, wall_now())
        append_event(call["id"], "DISPATCH_ARRIVED", role, uid)
    return success(serialize("dispatch", disp))


@bp.route("/roadside/dispatches/<dispatchId>/complete", methods=["POST"])
def complete(dispatchId):
    uid, role = auth(["Technician"])
    disp = _get_dispatch(dispatchId)
    _require_own_dispatch(disp, uid)
    validate_body(request.get_json(silent=True), [])
    if disp["status"] != "ON_SITE":
        raise err_invalid_state("Complete requires status ON_SITE")
    call = store.service_calls.get(disp["service_call_id"])
    if call is None or call["status"] not in ("REPAIR_COMPLETED",
                                              "TOW_IN_PROGRESS", "TOWED"):
        raise err_invalid_state(
            "Dispatch complete requires the call in REPAIR_COMPLETED, "
            "TOW_IN_PROGRESS, or TOWED")
    disp["status"] = "COMPLETED"
    disp["completed_at"] = store.clock
    touch(disp, wall_now())
    free_technician(disp["technician_id"])
    return success(serialize("dispatch", disp))


@bp.route("/roadside/dispatches/<dispatchId>/release", methods=["POST"])
def release(dispatchId):
    uid, role = auth(["Dispatcher", "OpsAdmin"])
    disp = _get_dispatch(dispatchId)
    vals = validate_body(request.get_json(silent=True), [
        Field("reason", "string"),
    ])
    if disp["status"] not in ("PROPOSED", "ACCEPTED"):
        raise err_invalid_state("Release requires status PROPOSED or ACCEPTED")
    was_accepted = disp["status"] == "ACCEPTED"
    disp["status"] = "RELEASED"
    disp["release_reason"] = vals.get("reason")
    touch(disp, wall_now())
    if was_accepted:
        free_technician(disp["technician_id"])
    call = store.service_calls.get(disp["service_call_id"])
    if call is not None:
        revert_call_if_no_active_dispatch(call)
    return success(serialize("dispatch", disp))
