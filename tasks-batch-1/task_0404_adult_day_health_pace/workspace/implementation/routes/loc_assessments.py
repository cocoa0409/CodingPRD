"""Level-of-care assessment endpoints. PRD §3.2."""
from flask import Blueprint, request

import db
from errors import err
from middleware import require_roles
from response import success, list_response
from services import common as c
from services import calculations as calc

bp = Blueprint("loc_assessments", __name__)


def loc_view(a):
    return dict(a)


@bp.post("/pace/loc-assessments")
@require_roles("MedicalDirector", "IntakeCoordinator")
def create_loc():
    body = c.get_body()
    participant_id = c.as_str(body, "participant_id")
    nf_score = c.as_int(body, "nf_score", min_val=0, max_val=100)
    assessed_on = c.parse_datetime(body, "assessed_on")
    nf_threshold = c.as_int(body, "nf_threshold", required=False, default=60)
    c.find_or_404(db.participants, participant_id)

    a = c.base_fields()
    a.update({
        "participant_id": participant_id,
        "nf_score": nf_score,
        "nf_threshold": nf_threshold,
        "assessed_on": c.iso_out(assessed_on),
        "expires_on": None,
        "status": "PENDING",
    })
    db.loc_assessments[a["id"]] = a
    return success(loc_view(a), status=201)


@bp.get("/pace/loc-assessments/<assessment_id>")
@require_roles("ProgramAdmin", "IntakeCoordinator", "MedicalDirector", "BillingSpecialist")
def get_loc(assessment_id):
    a = c.find_or_404(db.loc_assessments, assessment_id)
    return success(loc_view(a))


@bp.get("/pace/loc-assessments")
@require_roles("ProgramAdmin", "IntakeCoordinator", "MedicalDirector", "BillingSpecialist")
def list_loc():
    limit, offset = c.get_pagination()
    items = list(db.loc_assessments.values())
    for key in ("participant_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [a for a in items if a.get(key) == val]
    page, total = c.paginate(items, limit, offset)
    return list_response([loc_view(a) for a in page], limit, offset, total)


@bp.post("/pace/loc-assessments/<assessment_id>/certify")
@require_roles("MedicalDirector")
def certify_loc(assessment_id):
    a = c.find_or_404(db.loc_assessments, assessment_id)
    # State (priority 5)
    if a["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Assessment not PENDING")
    # Threshold (priority 9)
    if a["nf_score"] < a["nf_threshold"]:
        raise err("ERR_LOC_BELOW_THRESHOLD", "nf_score below nf_threshold")

    participant = db.participants.get(a["participant_id"])
    program = db.programs.get(participant["program_id"]) if participant else None

    # expires_on := assessed_on + Program.loc_validity_days
    assessed_dt = c.parse_iso(a["assessed_on"])
    validity = program["loc_validity_days"] if program else 365
    a["expires_on"] = c.iso_out(calc.add_days(assessed_dt, validity))

    # Prior CERTIFIED assessment for this participant → SUPERSEDED
    if participant:
        for other in db.loc_assessments.values():
            if (other["id"] != a["id"]
                    and other["participant_id"] == participant["id"]
                    and other["status"] == "CERTIFIED"):
                other["status"] = "SUPERSEDED"
                c.touch(other)

    a["status"] = "CERTIFIED"
    c.touch(a)

    if participant:
        participant["active_loc_assessment_id"] = a["id"]
        # APPLICANT → ELIGIBLE bubble-up; version increments
        if participant["status"] == "APPLICANT":
            participant["status"] = "ELIGIBLE"
        c.touch(participant)

    return success(loc_view(a))


@bp.post("/pace/loc-assessments/<assessment_id>/deny")
@require_roles("MedicalDirector")
def deny_loc(assessment_id):
    a = c.find_or_404(db.loc_assessments, assessment_id)
    if a["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Assessment not PENDING")
    a["status"] = "DENIED"
    c.touch(a)
    return success(loc_view(a))
