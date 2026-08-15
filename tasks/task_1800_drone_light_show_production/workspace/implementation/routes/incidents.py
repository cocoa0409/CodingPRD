"""IncidentReport endpoints."""

from flask import Blueprint

import errors
import validate as V
from db import DB, new_id, wall_created_at
from middleware import require_role, get_auth
from response import success_object, success_list
from services.show import (
    serialize_incident, touch, ground_drone_cascade, revoke_authorization_cascade,
)

bp = Blueprint("incidents", __name__)


def _get_incident(incident_id):
    r = DB.incident_reports.get(incident_id)
    if r is None:
        raise errors.not_found("ERR_INCIDENT_NOT_FOUND", "incident report not found")
    return r


def create_incident_record(show_id, drone_id, severity, description, source, filed_by):
    rid = new_id()
    ts = wall_created_at()
    report = {
        "id": rid, "show_event_id": show_id, "drone_id": drone_id,
        "severity": severity, "description": description,
        "source": source, "status": "FILED",
        "filed_by_user_id": filed_by, "closed_by_user_id": None,
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    DB.incident_reports[rid] = report
    DB.insertion_order["incident_reports"].append(rid)
    return report


@bp.route("/api/incident-reports", methods=["POST"])
def create_incident():
    body = V.get_body()
    V.reject_system_fields(body)
    V.req_fields(body, ["show_event_id", "severity", "description"])
    uid, _ = require_role("SafetyOfficer")
    show_id = body["show_event_id"]
    if not isinstance(show_id, str):
        raise errors.validation("show_event_id must be a string")
    severity = V.req_enum(body, "severity", {"MINOR", "MAJOR", "CRITICAL"})
    description = V.req_string(body, "description")
    drone_id = body.get("drone_id")
    if drone_id is not None and not isinstance(drone_id, str):
        raise errors.validation("drone_id must be a string")

    show = DB.show_events.get(show_id)
    if show is None:
        raise errors.not_found("ERR_SHOW_NOT_FOUND", "show not found")
    drone = None
    if drone_id is not None:
        drone = DB.drones.get(drone_id)
        if drone is None:
            raise errors.not_found("ERR_DRONE_NOT_FOUND", "drone not found")

    if show["lifecycle_status"] != "EXECUTED":
        raise errors.conflict("ERR_INVALID_STATE", "incidents can only be filed against an EXECUTED show")

    if severity == "MAJOR" and drone_id is None:
        raise errors.conflict("ERR_DRONE_REQUIRED", "severity MAJOR requires drone_id")

    report = create_incident_record(show_id, drone_id, severity, description, "MANUAL", uid)
    return success_object(serialize_incident(report), 201)


@bp.route("/api/incident-reports/<incidentId>", methods=["GET"])
def get_incident(incidentId):
    get_auth()
    return success_object(serialize_incident(_get_incident(incidentId)))


@bp.route("/api/incident-reports", methods=["GET"])
def list_incidents():
    get_auth()
    limit, offset = V.pagination_params()
    from flask import request
    show_id = V.opt_string(request.args, "show_event_id")
    drone_id = V.opt_string(request.args, "drone_id")
    severity = V.opt_string(request.args, "severity")
    status = V.opt_string(request.args, "status")
    items = [DB.incident_reports[i] for i in DB.insertion_order["incident_reports"]]
    if show_id is not None:
        items = [r for r in items if r["show_event_id"] == show_id]
    if drone_id is not None:
        items = [r for r in items if r["drone_id"] == drone_id]
    if severity is not None:
        items = [r for r in items if r["severity"] == severity]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_incident(r) for r in page], limit, offset, total)


@bp.route("/api/incident-reports/<incidentId>/investigate", methods=["POST"])
def investigate(incidentId):
    body = V.get_body()
    V.reject_system_fields(body)
    require_role("SafetyOfficer")
    report = _get_incident(incidentId)
    if report["status"] != "FILED":
        raise errors.conflict("ERR_INVALID_STATE", "incident must be FILED to investigate")
    report["status"] = "UNDER_INVESTIGATION"
    touch(report)
    return success_object(serialize_incident(report))


@bp.route("/api/incident-reports/<incidentId>/close", methods=["POST"])
def close_incident(incidentId):
    body = V.get_body()
    V.reject_system_fields(body)
    V.req_fields(body, ["outcome"])
    uid, _ = require_role("SafetyOfficer")
    outcome = V.req_enum(body, "outcome", {"CONFIRMED", "REJECTED"})
    report = _get_incident(incidentId)

    if report["status"] != "UNDER_INVESTIGATION":
        raise errors.conflict("ERR_INVALID_STATE", "incident must be UNDER_INVESTIGATION to close")

    if uid == report["filed_by_user_id"]:
        raise errors.sod("closer must differ from filer")

    show = DB.show_events.get(report["show_event_id"])

    if outcome == "REJECTED":
        report["status"] = "CLOSED_REJECTED"
        report["closed_by_user_id"] = uid
        touch(report)
        return success_object(serialize_incident(report))

    # CONFIRMED
    report["status"] = "CLOSED_CONFIRMED"
    report["closed_by_user_id"] = uid
    touch(report)

    if report["severity"] == "CRITICAL":
        # ground every drone with a FlightLog for this show
        drone_ids = []
        seen = set()
        for fid in DB.insertion_order["flight_logs"]:
            f = DB.flight_logs[fid]
            if f["show_event_id"] == report["show_event_id"] and f["drone_id"] not in seen:
                seen.add(f["drone_id"])
                drone_ids.append(f["drone_id"])
        for did in drone_ids:
            drone = DB.drones.get(did)
            if drone is None:
                continue
            if drone["status"] != "GROUNDED":
                was_reserved = drone["status"] == "RESERVED"
                drone["status"] = "GROUNDED"
                touch(drone)
                # void its ASSIGNED assignments on any show
                ground_drone_cascade(drone)
        # revoke the show's APPROVED authorization (pinned or any approved for this show)
        for aid in DB.insertion_order["authorizations"]:
            a = DB.authorizations[aid]
            if a["show_event_id"] == report["show_event_id"] and a["status"] == "APPROVED":
                a["status"] = "REVOKED"
                touch(a)
                revoke_authorization_cascade(a)
    elif report["severity"] == "MAJOR":
        if report["drone_id"] is not None:
            drone = DB.drones.get(report["drone_id"])
            if drone is not None and drone["status"] != "GROUNDED":
                drone["status"] = "GROUNDED"
                touch(drone)
                ground_drone_cascade(drone)

    return success_object(serialize_incident(report))
