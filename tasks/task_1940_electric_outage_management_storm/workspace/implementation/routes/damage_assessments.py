"""DamageAssessment endpoints: create (FieldCrewLead), get, list, submit, return,
accept (Dispatcher, OCC). Accept cascades: supersede prior ACCEPTED, outage
CONFIRMED -> ASSESSED, DAMAGE_FOUND system revision, single version increment."""
from flask import Blueprint, request

from db import db, iso_ms
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE_TRANSITION,
    ERR_OWNERSHIP_MISMATCH, ERR_STALE_OUTAGE_VERSION,
)
from services.core import (
    get_body, req_string, req_enum, req_int, req_bool, paginate,
    new_common, bump,
    get_outage, get_assessment, get_event, get_crew,
    serialize_assessment, sort_created_asc,
    etr_post_assessment, create_etr_revision, check_event_not_closed,
    DAMAGE_CLASSES,
)

bp = Blueprint("damage_assessments", __name__)


@bp.route("/om/outages/<oid>/damage-assessments", methods=["GET"])
def list_for_outage(oid):
    require_roles(ALL_ROLES)
    get_outage(oid)
    items = [a for a in db.damage_assessments.values() if a["outage_id"] == oid]
    items = sort_created_asc(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_assessment(a) for a in page], limit, offset, total)


@bp.route("/om/damage-assessments", methods=["POST"])
def create_assessment():
    user_id, _ = require_roles(["FieldCrewLead"])
    body = get_body()
    outage_id = req_string(body, "outage_id")
    damage_class = req_enum(body, "damage_class", DAMAGE_CLASSES)
    minutes = req_int(body, "estimated_repair_minutes", minimum=1)
    requires_switching = req_bool(body, "requires_switching")
    outage = get_outage(outage_id)
    # The lead's X-User-ID must identify an existing crew record.
    crew = db.crews.get(user_id)
    if crew is None:
        raise_err(ERR_INVALID_REQUEST,
                  "X-User-ID of a FieldCrewLead must identify an existing Crew")
    if outage["outage_status"] not in ("CONFIRMED", "ASSESSED", "WORKING"):
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"Outage in {outage['outage_status']} cannot be assessed")
    event = get_event(outage["storm_event_id"])
    check_event_not_closed(event)

    a = new_common()
    a.update({
        "outage_id": outage_id,
        "assessor_crew_id": user_id,
        "assessment_status": "DRAFT",
        "damage_class": damage_class,
        "estimated_repair_minutes": minutes,
        "requires_switching": requires_switching,
    })
    db.damage_assessments[a["id"]] = a
    return success_object(serialize_assessment(a), status=201)


@bp.route("/om/damage-assessments/<aid>", methods=["GET"])
def get_one(aid):
    require_roles(ALL_ROLES)
    a = get_assessment(aid)
    return success_object(serialize_assessment(a))


@bp.route("/om/damage-assessments", methods=["GET"])
def list_assessments():
    require_roles(ALL_ROLES)
    items = list(db.damage_assessments.values())
    outage_id = request.args.get("outage_id")
    assessor = request.args.get("assessor_crew_id")
    status = request.args.get("assessment_status")
    if outage_id is not None:
        items = [a for a in items if a["outage_id"] == outage_id]
    if assessor is not None:
        items = [a for a in items if a["assessor_crew_id"] == assessor]
    if status is not None:
        items = [a for a in items if a["assessment_status"] == status]
    items = sort_created_asc(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_assessment(a) for a in page], limit, offset, total)


@bp.route("/om/damage-assessments/<aid>/submit", methods=["POST"])
def submit(aid):
    user_id, _ = require_roles(["FieldCrewLead"])
    a = get_assessment(aid)
    if a["assessment_status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"Assessment in {a['assessment_status']} cannot be submitted")
    if user_id != a["assessor_crew_id"]:
        raise_err(ERR_OWNERSHIP_MISMATCH,
                  "Only the assessing crew may submit its assessment")
    a["assessment_status"] = "SUBMITTED"
    bump(a)
    return success_object(serialize_assessment(a))


@bp.route("/om/damage-assessments/<aid>/return", methods=["POST"])
def return_for_rework(aid):
    require_roles(["Dispatcher"])
    a = get_assessment(aid)
    if a["assessment_status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"Assessment in {a['assessment_status']} cannot be returned")
    a["assessment_status"] = "DRAFT"
    bump(a)
    return success_object(serialize_assessment(a))


@bp.route("/om/damage-assessments/<aid>/accept", methods=["POST"])
def accept(aid):
    require_roles(["Dispatcher"])
    a = get_assessment(aid)
    body = get_body()
    expected = body.get("expected_outage_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise_err(ERR_INVALID_REQUEST,
                  "expected_outage_version is required and must be an integer")

    if a["assessment_status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"Assessment in {a['assessment_status']} cannot be accepted")
    outage = get_outage(a["outage_id"])
    if outage["outage_status"] not in ("CONFIRMED", "ASSESSED", "WORKING"):
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"Linked outage in {outage['outage_status']} cannot accept an assessment")
    event = get_event(outage["storm_event_id"])
    check_event_not_closed(event)

    # OCC gate against the linked outage's current version.
    if expected != outage["version"]:
        raise_err(ERR_STALE_OUTAGE_VERSION,
                  "expected_outage_version does not match the outage's current version")

    # Cascade: supersede any other ACCEPTED assessment on the same outage.
    for other in db.damage_assessments.values():
        if other["outage_id"] == outage["id"] and other["id"] != a["id"] \
                and other["assessment_status"] == "ACCEPTED":
            other["assessment_status"] = "SUPERSEDED"
            bump(other)

    a["assessment_status"] = "ACCEPTED"
    bump(a)

    # Outage promotion: CONFIRMED -> ASSESSED.
    if outage["outage_status"] == "CONFIRMED":
        outage["outage_status"] = "ASSESSED"

    # System DAMAGE_FOUND revision (post_assessment variant).
    etr = etr_post_assessment(a, outage, db.now())
    create_etr_revision(outage, "DAMAGE_FOUND", etr, "system")

    # Single version increment for the whole accept request.
    bump(outage)
    return success_object(serialize_assessment(a))
