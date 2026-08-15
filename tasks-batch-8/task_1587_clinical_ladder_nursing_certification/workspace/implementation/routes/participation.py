"""ParticipationEvent endpoints."""

from flask import Blueprint, request

from clock import clock
from db import db
from errors import (err_invalid_state, err_not_found, err_not_owner,
                    err_participation_points_range)
from middleware import require_roles
from response import success_list, success_object, parse_pagination
from serializers import participation_event_view
from services.calculations import record_risk_event, recompute_risk
from util import parse_datetime, require_fields, require_int, require_enum

bp = Blueprint("participation", __name__)

EVENT_KINDS = {"COMMITTEE_SEAT", "QI_PROJECT", "PEER_EDUCATION", "EBP_RESEARCH", "PRECEPTORSHIP"}


@bp.route("/clinical-ladder/participation-events", methods=["POST"])
def create_event():
    user_id, _ = require_roles("Nurse")
    payload = request.get_json(silent=True)
    require_fields(payload, ["nurse_id", "event_kind", "points", "occurred_on"])
    nurse_id = payload.get("nurse_id")
    if not isinstance(nurse_id, str):
        from errors import err_invalid_request
        raise err_invalid_request("nurse_id must be a string")
    event_kind = require_enum(payload, "event_kind", EVENT_KINDS)
    points = require_int(payload, "points")
    occurred_on = parse_datetime(payload.get("occurred_on"), "occurred_on")

    nurse = db.nurses.get(nurse_id)
    if nurse is None:
        raise err_not_found("Nurse not found")

    # Ownership: the acting Nurse may only log own events
    if user_id != nurse_id:
        raise err_not_owner()

    # Points within [1,40]; COMMITTEE_SEAT capped at 20
    if not (1 <= points <= 40) or (event_kind == "COMMITTEE_SEAT" and points > 20):
        raise err_participation_points_range()

    now = clock.now()
    event = {
        "id": db.new_id(),
        "nurse_id": nurse_id,
        "event_kind": event_kind,
        "points": points,
        "occurred_on": occurred_on,
        "status": "PENDING_VERIFICATION",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.participation_events[event["id"]] = event
    return success_object(participation_event_view(event), status=201)


@bp.route("/clinical-ladder/participation-events", methods=["GET"])
def list_events():
    require_roles("ProgramAdmin", "RetentionAnalyst")
    limit, offset = parse_pagination(request.args)
    nurse_id = request.args.get("nurse_id")
    event_kind = request.args.get("event_kind")
    status = request.args.get("status")
    rows = sorted(db.participation_events.values(), key=lambda e: e["created_at"])
    if nurse_id is not None:
        rows = [e for e in rows if e["nurse_id"] == nurse_id]
    if event_kind is not None:
        rows = [e for e in rows if e["event_kind"] == event_kind]
    if status is not None:
        rows = [e for e in rows if e["status"] == status]
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([participation_event_view(e) for e in page], limit, offset, total)


def _get_event_or_404(eid):
    event = db.participation_events.get(eid)
    if event is None:
        raise err_not_found("ParticipationEvent not found")
    return event


@bp.route("/clinical-ladder/participation-events/<eid>/verify", methods=["POST"])
def verify_event(eid):
    require_roles("ProgramAdmin")
    event = _get_event_or_404(eid)
    if event["status"] != "PENDING_VERIFICATION":
        raise err_invalid_state("Event has already left PENDING_VERIFICATION")
    event["status"] = "VERIFIED"
    event["updated_at"] = clock.now()
    event["version"] += 1
    record_risk_event(event["nurse_id"], "participation_verified")
    recompute_risk(event["nurse_id"])
    return success_object(participation_event_view(event))


@bp.route("/clinical-ladder/participation-events/<eid>/void", methods=["POST"])
def void_event(eid):
    require_roles("ProgramAdmin")
    event = _get_event_or_404(eid)
    if event["status"] != "PENDING_VERIFICATION":
        raise err_invalid_state("Event has already left PENDING_VERIFICATION")
    event["status"] = "VOIDED"
    event["updated_at"] = clock.now()
    event["version"] += 1
    return success_object(participation_event_view(event))
