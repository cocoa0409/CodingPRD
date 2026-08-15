"""DispatchAssignment action endpoints: arrive / clear / cancel / preempt."""
from flask import Blueprint

import clock
import db
import domain
import response
from auth import require_roles
from errors import ApiError
from routes.common import (check_incident_read_scope, load_assignment,
                           load_incident)
from validate import get_body, req_str

bp = Blueprint("dispatches", __name__)

ALL = ("SystemAdmin", "Dispatcher", "FieldTechnician", "Supervisor", "Regulator")


@bp.route("/gas-ops/dispatches/<dispatchId>", methods=["GET"])
@require_roles(*ALL)
def get_dispatch(dispatchId, user_id, role):
    assignment = load_assignment(dispatchId)
    incident = load_incident(assignment["incident_id"])
    check_incident_read_scope(incident, role, user_id)
    return response.success(domain.ser_assignment(assignment), 200)


def _check_owner(assignment, user_id):
    if assignment["technician_id"] != user_id:
        raise ApiError("ERR_NOT_ASSIGNED_TO_INCIDENT",
                       "The assignment belongs to a different technician", 403)


@bp.route("/gas-ops/dispatches/<dispatchId>/arrive", methods=["POST"])
@require_roles("FieldTechnician")
def arrive(dispatchId, user_id, role):
    assignment = load_assignment(dispatchId)
    _check_owner(assignment, user_id)
    if assignment["status"] != "EN_ROUTE":
        raise ApiError("ERR_INVALID_STATE", "Arrive requires an EN_ROUTE assignment", 409)
    now = clock.now()
    assignment["arrived_at"] = now
    assignment["status"] = "ON_SCENE"
    domain.bump(assignment)
    incident = load_incident(assignment["incident_id"])
    if incident["first_arrival_at"] is None:
        # First arrival of the current segment: stop the clock, auto-close open
        # pauses, advance the lifecycle, recompute breach (computed on read).
        incident["first_arrival_at"] = now
        for p in domain.segment_pauses(incident):
            if p["ended_at"] is None:
                p["ended_at"] = now
                domain.bump(p)
        if incident["lifecycle_status"] == "DISPATCHED":
            incident["lifecycle_status"] = "ON_SCENE"
        domain.bump(incident)
    return response.success(domain.ser_assignment(assignment), 200)


@bp.route("/gas-ops/dispatches/<dispatchId>/clear", methods=["POST"])
@require_roles("FieldTechnician")
def clear(dispatchId, user_id, role):
    assignment = load_assignment(dispatchId)
    _check_owner(assignment, user_id)
    if assignment["status"] != "ON_SCENE":
        raise ApiError("ERR_INVALID_STATE", "Clear requires an ON_SCENE assignment", 409)
    assignment["cleared_at"] = clock.now()
    assignment["status"] = "CLEARED"
    domain.bump(assignment)
    return response.success(domain.ser_assignment(assignment), 200)


@bp.route("/gas-ops/dispatches/<dispatchId>/cancel", methods=["POST"])
@require_roles("Supervisor")
def cancel(dispatchId, user_id, role):
    assignment = load_assignment(dispatchId)
    body = get_body()
    req_str(body, "reason")
    if assignment["status"] != "EN_ROUTE":
        raise ApiError("ERR_INVALID_STATE", "Cancel requires an EN_ROUTE assignment", 409)
    assignment["status"] = "CANCELLED"
    domain.bump(assignment)
    return response.success(domain.ser_assignment(assignment), 200)


@bp.route("/gas-ops/dispatches/<dispatchId>/preempt", methods=["POST"])
@require_roles("Supervisor")
def preempt(dispatchId, user_id, role):
    assignment = load_assignment(dispatchId)
    body = get_body()
    target_id = req_str(body, "target_incident_id")
    reason = req_str(body, "reason")
    if assignment["status"] != "EN_ROUTE":
        raise ApiError("ERR_DISPATCH_NOT_PREEMPTABLE",
                       "Only EN_ROUTE assignments can be preempted", 409)
    target = db.incidents.get(target_id)
    source_incident = load_incident(assignment["incident_id"])
    if (target is None or target["lifecycle_status"] not in ("TRIAGED", "DISPATCHED")
            or domain.PRIORITY_RANK[target["priority"]]
            <= domain.PRIORITY_RANK[source_incident["priority"]]):
        raise ApiError("ERR_INVALID_STATE",
                       "Preempt target must exist, be TRIAGED or DISPATCHED, and carry a "
                       "strictly higher priority than the source incident", 409)
    # Atomic re-pointing: source assignment PREEMPTED, new EN_ROUTE assignment
    # auto-created on the target for the same technician (count net unchanged).
    assignment["status"] = "PREEMPTED"
    assignment["preempt_reason"] = reason
    domain.bump(assignment)
    rec = domain.new_record(common_fields=True)
    rec.update({
        "incident_id": target["id"],
        "technician_id": assignment["technician_id"],
        "status": "EN_ROUTE",
        "sla_threshold_minutes": domain.threshold_minutes(target),
        "dispatched_at": clock.now(),
        "arrived_at": None,
        "cleared_at": None,
        "preempt_reason": None,
        "notes": None,
    })
    db.assignments[rec["id"]] = rec
    if target["lifecycle_status"] == "TRIAGED":
        target["lifecycle_status"] = "DISPATCHED"
        domain.bump(target)
    return response.success(domain.ser_assignment(rec), 200)
