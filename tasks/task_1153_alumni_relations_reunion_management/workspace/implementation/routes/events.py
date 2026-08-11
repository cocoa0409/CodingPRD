"""ReunionEvent endpoints."""

from flask import Blueprint, request

import db
from errors import (
    err_invalid_request, err_invalid_state, err_no_active_tier, err_not_found,
    err_quorum,
)
from middleware import require_roles
from response import success_list, success_object
from services.calculations import rederive_posture
from services.cascades import cancel_event
from services.common import (
    apply_pagination, format_ts, json_body, new_entity, pagination_args,
    parse_iso, req_int, req_str, touch,
)
from services.serializers import EVENT_FIELDS, serialize

bp = Blueprint("events", __name__)

STAFF_OR_DIRECTOR = ("AlumniRelationsStaff", "AlumniRelationsDirector")
ALL_READ = ("AlumniRelationsStaff", "AlumniRelationsDirector", "ReunionChair",
            "CommitteeVolunteer", "AffinityGroupLeader", "Alumni")


def get_event_or_404(event_id):
    event = db.events.get(event_id)
    if event is None:
        raise err_not_found("ReunionEvent not found")
    return event


@bp.route("/alumni/events", methods=["POST"])
@require_roles(*STAFF_OR_DIRECTOR)
def create_event(_role, _user_id):
    body = json_body(required=["class_year", "title", "event_date"])
    class_year = req_int(body["class_year"], "class_year")
    title = req_str(body["title"], "title")
    event_date_dt = parse_iso(body["event_date"])
    quorum = body.get("committee_quorum_required", 3)
    if quorum is None:
        quorum = 3
    quorum = req_int(quorum, "committee_quorum_required")
    if quorum < 1:
        raise err_invalid_request("committee_quorum_required must be >= 1")

    milestone_year = db.logical_now().year - class_year

    event = new_entity({
        "class_year": class_year,
        "title": title,
        "event_date": format_ts(event_date_dt),
        "event_date_dt": event_date_dt,
        "milestone_year": milestone_year,
        "status": "PLANNING",
        "posture": "GATED",
        "committee_count": 0,
        "committee_quorum_required": quorum,
        "total_revenue_cents": 0,
    })
    db.events[event["id"]] = event
    return success_object(serialize(event, EVENT_FIELDS), status=201)


@bp.route("/alumni/events/<eid>", methods=["GET"])
@require_roles(*ALL_READ)
def get_event(eid, _role, _user_id):
    return success_object(serialize(get_event_or_404(eid), EVENT_FIELDS))


@bp.route("/alumni/events", methods=["GET"])
@require_roles(*ALL_READ)
def list_events(_role, _user_id):
    limit, offset = pagination_args()
    rows = list(db.events.values())
    status = request.args.get("status")
    if status:
        rows = [e for e in rows if e["status"] == status]
    posture = request.args.get("posture")
    if posture:
        rows = [e for e in rows if e["posture"] == posture]
    class_year = request.args.get("class_year")
    if class_year:
        try:
            cy = int(class_year)
        except ValueError:
            raise err_invalid_request("class_year must be an integer")
        rows = [e for e in rows if e["class_year"] == cy]
    page, total = apply_pagination(rows, limit, offset)
    return success_list([serialize(e, EVENT_FIELDS) for e in page], limit, offset, total)


@bp.route("/alumni/events/<eid>/form-committee", methods=["POST"])
@require_roles(*STAFF_OR_DIRECTOR)
def form_committee(eid, _role, _user_id):
    event = get_event_or_404(eid)
    if event["status"] != "PLANNING":
        raise err_invalid_state("Event must be PLANNING to form committee")
    committee = next((c for c in db.committees.values() if c["event_id"] == eid), None)
    if committee is None:
        raise err_invalid_state("A ReunionCommittee must exist for this event")
    if event["committee_count"] < 1:
        raise err_invalid_state("committee_count must be at least 1")
    event["status"] = "COMMITTEE_FORMED"
    rederive_posture(event)
    return success_object(serialize(event, EVENT_FIELDS))


@bp.route("/alumni/events/<eid>/open-registration", methods=["POST"])
@require_roles(*STAFF_OR_DIRECTOR)
def open_registration(eid, _role, _user_id):
    event = get_event_or_404(eid)
    if event["status"] != "COMMITTEE_FORMED":
        raise err_invalid_state("Event must be COMMITTEE_FORMED to open registration")
    if event["committee_count"] < event["committee_quorum_required"]:
        raise err_quorum()
    now = db.logical_now()
    tiers = [t for t in db.ticket_tiers.values() if t["event_id"] == eid]
    active = [t for t in tiers if t["sales_start_dt"] <= now < t["sales_end_dt"]]
    if not active:
        raise err_no_active_tier()
    event["status"] = "OPEN_FOR_REGISTRATION"
    committee = next((c for c in db.committees.values() if c["event_id"] == eid), None)
    if committee is not None:
        committee["locked"] = True
        touch(committee)
    rederive_posture(event)
    return success_object(serialize(event, EVENT_FIELDS))


@bp.route("/alumni/events/<eid>/mark-held", methods=["POST"])
@require_roles(*STAFF_OR_DIRECTOR)
def mark_held(eid, _role, _user_id):
    event = get_event_or_404(eid)
    if event["status"] != "OPEN_FOR_REGISTRATION":
        raise err_invalid_state("Event must be OPEN_FOR_REGISTRATION to mark held")
    if db.logical_now() < event["event_date_dt"]:
        raise err_invalid_state("Current logical clock has not reached event_date")
    event["status"] = "HELD"
    rederive_posture(event)
    return success_object(serialize(event, EVENT_FIELDS))


@bp.route("/alumni/events/<eid>/reconcile", methods=["POST"])
@require_roles(*STAFF_OR_DIRECTOR)
def reconcile(eid, _role, _user_id):
    event = get_event_or_404(eid)
    if event["status"] != "HELD":
        raise err_invalid_state("Event must be HELD to reconcile")
    for reg in db.registrations.values():
        if reg["event_id"] == eid and reg["payment_status"] == "PENDING_PAYMENT":
            raise err_invalid_state("Event has PENDING_PAYMENT registrations")
    event["status"] = "RECONCILED"
    rederive_posture(event)
    return success_object(serialize(event, EVENT_FIELDS))


@bp.route("/alumni/events/<eid>/cancel", methods=["POST"])
@require_roles("AlumniRelationsDirector")
def cancel(eid, _role, _user_id):
    event = get_event_or_404(eid)
    if event["status"] not in ("PLANNING", "COMMITTEE_FORMED", "OPEN_FOR_REGISTRATION"):
        raise err_invalid_state("Event is not in a cancellable state")
    cancel_event(event)
    return success_object(serialize(event, EVENT_FIELDS))
