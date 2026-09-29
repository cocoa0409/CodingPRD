"""Incident reports: filing, formal review, closure and the recovery cascade."""

from flask import Blueprint, request

import domain
import store
import validation as v
from auth import ALL_ROLES, actor, require
from envelope import created, ok, paginate
from errors import fail
from store import new_entity, touch

bp = Blueprint("incident", __name__)

INCIDENT_SEVERITIES = ("MINOR", "MODERATE", "SEVERE")
INCIDENT_STATUSES = ("OPEN", "UNDER_REVIEW", "CLOSED")


@bp.post("/incidents")
@require("Volunteer", "CrewLeader")
def create_incident():
    data = v.body()
    work_party_id = v.req_id(data, "work_party_id")
    severity_class = v.req_enum(data, "severity_class", INCIDENT_SEVERITIES)
    first_aid_rendered = v.req_bool(data, "first_aid_rendered")
    narrative = v.req_str(data, "narrative", allow_empty=True)
    occurred_at = v.req_datetime(data, "occurred_at")
    injured_volunteer_id = v.opt_id(data, "injured_volunteer_id")

    if occurred_at > store.now():
        fail("ERR_INVALID_REQUEST", "occurred_at must be at or before the logical clock.")

    party = domain.get_party(work_party_id)
    if injured_volunteer_id is not None:
        domain.get_volunteer(injured_volunteer_id)

    incident = new_entity({
        "work_party_id": work_party_id,
        "trail_segment_id": party["trail_segment_id"],
        "injured_volunteer_id": injured_volunteer_id,
        "severity_class": severity_class,
        "first_aid_rendered": first_aid_rendered,
        "narrative": narrative,
        "occurred_at": store.iso(occurred_at),
        "status": "OPEN",
        "reported_by_user_id": actor(),
        "closed_by_user_id": None,
        "corrective_action": None,
        "closed_at": None,
    })
    store.incidents[incident["id"]] = incident

    segment = store.segments.get(party["trail_segment_id"])
    if segment is not None:
        previous = segment["open_severe_incident_count"]
        domain.recompute_severe_incidents(segment)
        changed = segment["open_severe_incident_count"] != previous
        domain.settle_segment(segment, force_touch=changed)
    return created(domain.s_incident(incident))


@bp.get("/incidents/<entity_id>")
@require(*ALL_ROLES)
def read_incident(entity_id):
    return ok(domain.s_incident(domain.get_incident(entity_id)))


@bp.get("/incidents")
@require(*ALL_ROLES)
def list_incidents():
    work_party_id = request.args.get("work_party_id")
    trail_segment_id = request.args.get("trail_segment_id")
    injured_volunteer_id = request.args.get("injured_volunteer_id")
    status = request.args.get("status")
    if status is not None and status not in INCIDENT_STATUSES:
        fail("ERR_INVALID_REQUEST", "Query parameter 'status' is not a declared member.")
    rows = store.ordered(list(store.incidents.values()))
    if work_party_id is not None:
        rows = [r for r in rows if r["work_party_id"] == work_party_id]
    if trail_segment_id is not None:
        rows = [r for r in rows if r["trail_segment_id"] == trail_segment_id]
    if injured_volunteer_id is not None:
        rows = [r for r in rows if r.get("injured_volunteer_id") == injured_volunteer_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, domain.s_incident)


@bp.post("/incidents/<entity_id>/review")
@require("SafetyOfficer")
def review_incident(entity_id):
    incident = domain.get_incident(entity_id)
    if incident["status"] != "OPEN":
        fail("ERR_INVALID_STATE", "Only an OPEN incident may enter review.")
    if incident["severity_class"] not in ("MODERATE", "SEVERE"):
        fail("ERR_INVALID_STATE", "Only a MODERATE or SEVERE incident has a review step.")

    incident["status"] = "UNDER_REVIEW"
    touch(incident)
    return ok(domain.s_incident(incident))


@bp.post("/incidents/<entity_id>/close")
@require("SafetyOfficer")
def close_incident(entity_id):
    incident = domain.get_incident(entity_id)
    if actor() == incident.get("reported_by_user_id"):
        fail("ERR_SEGREGATION_OF_DUTIES", "The closer may not be the reporter.")

    data = v.body()
    corrective_action = v.req_str(data, "corrective_action")

    if incident["status"] == "OPEN":
        if incident["severity_class"] != "MINOR":
            fail("ERR_INVALID_STATE",
                 "A MODERATE or SEVERE incident must pass through UNDER_REVIEW.")
    elif incident["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE", "The incident is already CLOSED.")

    from_review = incident["status"] == "UNDER_REVIEW"
    incident["status"] = "CLOSED"
    incident["closed_by_user_id"] = actor()
    incident["corrective_action"] = corrective_action
    incident["closed_at"] = store.now_iso()
    touch(incident)

    if from_review:
        segment = store.segments.get(incident["trail_segment_id"])
        if segment is not None:
            previous = segment["open_severe_incident_count"]
            domain.recompute_severe_incidents(segment)
            changed = segment["open_severe_incident_count"] != previous
            domain.settle_segment(segment, force_touch=changed)
    return ok(domain.s_incident(incident))
