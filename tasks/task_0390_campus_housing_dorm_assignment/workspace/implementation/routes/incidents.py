"""Incident report routes: file, get, list, escalate, resolve."""

from flask import Blueprint, request

import db
import errors
import response
import common
from middleware import authenticate, require_role
from services import core

bp = Blueprint("incidents", __name__)

# GET incident endpoints are limited to HousingOfficer and ResidentAdvisor.
READ_ROLES = ("HousingOfficer", "ResidentAdvisor")
SEVERITIES = {"MINOR", "MAJOR", "CRITICAL"}


@bp.route("/incident-reports", methods=["POST"])
def file_incident():
    principal = authenticate()
    require_role(principal, ("ResidentAdvisor",))
    body = common.get_body()
    common.require_fields(body, ["room_id", "reporter_student_id", "severity"])
    room_id = body["room_id"]
    reporter_id = body["reporter_student_id"]
    severity = common.require_enum(body, "severity", SEVERITIES)

    with db.LOCK:
        # Ownership: the filing RA's X-User-ID must equal reporter_student_id.
        if principal.user_id != reporter_id:
            raise errors.forbidden("RA may only file reports under their own id.")
        room = core.get_or_404(db.rooms, room_id)
        core.get_or_404(db.students, reporter_id)

        rec = core.init_record({
            "room_id": room_id,
            "reporter_student_id": reporter_id,
            "severity": severity,
            "status": "OPEN",
        })
        db.incident_reports[rec["id"]] = rec
        # Room open_incident_count += 1, re-derive status.
        core.reconcile_room(room)
        return response.object_response(core.serialize(rec), status=201)


@bp.route("/incident-reports/<incident_id>", methods=["GET"])
def get_incident(incident_id):
    principal = authenticate()
    require_role(principal, READ_ROLES)
    with db.LOCK:
        rec = core.get_or_404(db.incident_reports, incident_id)
        return response.object_response(core.serialize(rec))


@bp.route("/incident-reports", methods=["GET"])
def list_incidents():
    principal = authenticate()
    require_role(principal, READ_ROLES)
    with db.LOCK:
        limit, offset = common.parse_pagination()
        items = list(db.incident_reports.values())
        for key in ("room_id", "reporter_student_id"):
            val = request.args.get(key)
            if val is not None:
                items = [i for i in items if i.get(key) == val]
        items = common.sort_by_created(items)
        page, total = common.paginate(items, limit, offset)
        return response.array_response(
            [core.serialize(i) for i in page], limit, offset, total
        )


@bp.route("/incident-reports/<incident_id>/escalate", methods=["POST"])
def escalate_incident(incident_id):
    principal = authenticate()
    require_role(principal, ("ResidentAdvisor",))
    with db.LOCK:
        rec = core.get_or_404(db.incident_reports, incident_id)
        # Ownership: only the reporter may escalate.
        if principal.user_id != rec["reporter_student_id"]:
            raise errors.forbidden("Only the reporting RA may escalate.")
        if rec["status"] != "OPEN":
            raise errors.invalid_state("Incident is not OPEN.")
        rec["status"] = "ESCALATED"
        core.touch(rec)
        # open_incident_count unchanged (ESCALATED still open); re-derive status.
        room = db.rooms.get(rec["room_id"])
        if room is not None:
            core.reconcile_room(room)
        return response.object_response(core.serialize(rec))


@bp.route("/incident-reports/<incident_id>/resolve", methods=["POST"])
def resolve_incident(incident_id):
    principal = authenticate()
    require_role(principal, ("HousingOfficer",))
    with db.LOCK:
        rec = core.get_or_404(db.incident_reports, incident_id)
        if rec["status"] not in ("OPEN", "ESCALATED"):
            raise errors.invalid_state("Incident is not OPEN or ESCALATED.")
        rec["status"] = "RESOLVED"
        core.touch(rec)
        room = db.rooms.get(rec["room_id"])
        if room is not None:
            core.reconcile_room(room)
        return response.object_response(core.serialize(rec))
