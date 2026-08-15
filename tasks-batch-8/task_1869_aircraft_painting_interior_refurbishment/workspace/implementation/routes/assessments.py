"""SurfaceAssessment endpoints (PENDING -> DECIDED; amend self-loop; supersede)."""
from flask import Blueprint, request

from db import STORE
from domain import (new_entity, bump, get_or_404, by_created,
                    serialize_assessment)
from errors import ApiError, ref_integrity, invalid_state, ERR_ASSESSMENT_LOCKED
from middleware import auth
from response import success
from validation import get_body, field, paginate

bp = Blueprint("assessments", __name__)

DECISIONS = ("STRIP", "SCUFF")
SEVERITIES = ("NONE", "LIGHT", "HEAVY")


@bp.post("/surface-assessments")
def create_assessment():
    auth("ShopTechnician")
    data = get_body(required=True)
    program_id = field(data, "program_id", "str")
    if program_id not in STORE.programs:
        raise ref_integrity("program_id does not reference an existing program")
    # Creating a new assessment supersedes the prior PENDING/DECIDED one.
    for a in STORE.surface_assessments.values():
        if a["program_id"] == program_id and a["status"] in ("PENDING", "DECIDED"):
            a["status"] = "SUPERSEDED"
            bump(a)
    assessment = new_entity()
    assessment.update({
        "program_id": program_id,
        "status": "PENDING",
        "decision": None,
        "corrosion_severity": None,
        "findings_note": None,
        "revision": 1,
    })
    STORE.surface_assessments[assessment["id"]] = assessment
    return success(serialize_assessment(assessment), status=201)


@bp.get("/surface-assessments/<aid>")
def get_assessment(aid):
    auth()
    a = get_or_404(STORE.surface_assessments, aid, "SurfaceAssessment")
    return success(serialize_assessment(a))


@bp.get("/surface-assessments")
def list_assessments():
    auth()
    items = by_created(list(STORE.surface_assessments.values()))
    program_id = request.args.get("program_id")
    if program_id is not None:
        items = [a for a in items if a["program_id"] == program_id]
    return paginate(items, serialize_assessment)


def _decision_fields(data):
    decision = field(data, "decision", "str", enum=DECISIONS)
    severity = field(data, "corrosion_severity", "str", enum=SEVERITIES)
    note = field(data, "findings_note", "str", required=False, default=None)
    return decision, severity, note


@bp.post("/surface-assessments/<aid>/decide")
def decide_assessment(aid):
    auth("ShopTechnician")
    data = get_body(required=True)
    decision, severity, note = _decision_fields(data)
    a = get_or_404(STORE.surface_assessments, aid, "SurfaceAssessment")
    prog = STORE.programs[a["program_id"]]
    if a["status"] != "PENDING":
        raise invalid_state("Only a PENDING assessment can be decided")
    if prog["status"] not in ("INDUCTED", "SURFACE_REVIEW"):
        raise invalid_state(
            "Decide is permitted only while the program is INDUCTED or SURFACE_REVIEW")
    a["decision"] = decision
    a["corrosion_severity"] = severity
    a["findings_note"] = note
    a["status"] = "DECIDED"
    bump(a)
    return success(serialize_assessment(a))


@bp.post("/surface-assessments/<aid>/amend")
def amend_assessment(aid):
    auth("ShopTechnician")
    data = get_body(required=True)
    decision, severity, note = _decision_fields(data)
    a = get_or_404(STORE.surface_assessments, aid, "SurfaceAssessment")
    prog = STORE.programs[a["program_id"]]
    if a["status"] != "DECIDED":
        raise invalid_state("Only a DECIDED assessment can be amended")
    if prog["status"] != "SURFACE_REVIEW":
        raise ApiError(ERR_ASSESSMENT_LOCKED, 409,
                       "Amend is permitted only while the program is in SURFACE_REVIEW")
    a["decision"] = decision
    a["corrosion_severity"] = severity
    a["findings_note"] = note
    a["revision"] += 1
    bump(a)
    return success(serialize_assessment(a))
