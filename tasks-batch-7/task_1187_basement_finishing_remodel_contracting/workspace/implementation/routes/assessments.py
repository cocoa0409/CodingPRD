"""Moisture assessment endpoints (PRD §3.2)."""
from flask import Blueprint

from db import stores
from errors import fail
from response import ok
from serializers import ser_assessment
from services import (
    moisture_risk, band_acceptable, advance_project,
)
from services import touch
from validation import auth, require_role, get_body, v_str, v_num, v_bool, v_int, v_enum
from routes.common import (
    project_or_404, get_or_404, require_contractor_owner, new_entity, list_response,
)

bp = Blueprint("assessments", __name__)

ASSESSMENT_GATE = {"INTAKE", "ASSESSMENT", "DESIGN"}
KINDS = {"SCREENING", "VERIFICATION"}


def _readings_shape(body):
    return {
        "slab_moisture_lbs": v_num(body, "slab_moisture_lbs"),
        "interior_rh_pct": v_num(body, "interior_rh_pct"),
        "efflorescence_observed": v_bool(body, "efflorescence_observed"),
        "grading_deficit": v_bool(body, "grading_deficit"),
    }


@bp.post("/api/projects/<project_id>/moisture-assessments")
def create_assessment(project_id):
    role, uid = auth()
    require_role(role, "Contractor")
    project = project_or_404(project_id)
    require_contractor_owner(project, uid)
    body = get_body()
    # Priority 7: project state gate.
    if project["status"] not in ASSESSMENT_GATE:
        fail("ERR_PROJECT_STATE_FORBIDS", "Project status does not permit assessments")
    # Priority 14: at most one DRAFT assessment per project.
    for a in stores["assessments"].values():
        if a["project_id"] == project_id and a["status"] == "DRAFT":
            fail("ERR_ASSESSMENT_IN_PROGRESS", "A DRAFT assessment already exists on this project")
    # Priority 15: VERIFICATION only where a REJECTED assessment exists.
    raw_kind = body.get("assessment_kind")
    if raw_kind == "VERIFICATION":
        has_rejected = any(
            a["project_id"] == project_id and a["status"] == "REJECTED"
            for a in stores["assessments"].values()
        )
        if not has_rejected:
            fail("ERR_REASSESSMENT_NOT_ALLOWED", "VERIFICATION requires a prior REJECTED assessment")
    # Priority 26: shape.
    kind = v_enum(body, "assessment_kind", KINDS, required=False) or "SCREENING"
    readings = _readings_shape(body)
    egress_windows_existing = v_int(body, "egress_windows_existing")
    ceiling_height_in = v_num(body, "ceiling_height_in")
    e = new_entity({
        "project_id": project_id,
        "assessment_kind": kind,
        "slab_moisture_lbs": readings["slab_moisture_lbs"],
        "interior_rh_pct": readings["interior_rh_pct"],
        "efflorescence_observed": readings["efflorescence_observed"],
        "grading_deficit": readings["grading_deficit"],
        "egress_windows_existing": egress_windows_existing,
        "ceiling_height_in": ceiling_height_in,
        "remediation_notes": None,
        "moisture_risk_score": None,
        "risk_band": None,
        "status": "DRAFT",
    })
    stores["assessments"][e["id"]] = e
    # First assessment on an INTAKE project advances it to ASSESSMENT.
    if project["status"] == "INTAKE":
        advance_project(project, "ASSESSMENT")
    return ok(ser_assessment(e), 201)


@bp.get("/api/projects/<project_id>/moisture-assessments")
def list_assessments(project_id):
    auth()
    project_or_404(project_id)
    items = [a for a in stores["assessments"].values() if a["project_id"] == project_id]
    return list_response(items, ser_assessment)


@bp.post("/api/moisture-assessments/<assessment_id>/submit")
def submit_assessment(assessment_id):
    role, uid = auth()
    require_role(role, "Contractor")
    a = get_or_404("assessments", assessment_id, "MoistureAssessment")
    project = project_or_404(a["project_id"])
    require_contractor_owner(project, uid)
    # Priority 7: project state gate.
    if project["status"] not in ASSESSMENT_GATE:
        fail("ERR_PROJECT_STATE_FORBIDS", "Project status does not permit assessment submission")
    # Terminal guard, then from-state (PRD §3.2).
    if a["status"] == "ACCEPTED":
        fail("ERR_ALREADY_TERMINAL", "An ACCEPTED assessment is terminal")
    if a["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Only a DRAFT assessment can be submitted")
    score, band = moisture_risk(
        a["assessment_kind"],
        a["slab_moisture_lbs"],
        a["interior_rh_pct"],
        a["efflorescence_observed"],
        a["grading_deficit"],
    )
    a["moisture_risk_score"] = score
    a["risk_band"] = band
    if band_acceptable(a["assessment_kind"], band):
        a["status"] = "ACCEPTED"
        touch(a)
        if project["status"] in ("INTAKE", "ASSESSMENT"):
            advance_project(project, "DESIGN")
    else:
        a["status"] = "REJECTED"
        touch(a)
    return ok(ser_assessment(a))


@bp.post("/api/moisture-assessments/<assessment_id>/reopen")
def reopen_assessment(assessment_id):
    role, uid = auth()
    require_role(role, "Contractor")
    a = get_or_404("assessments", assessment_id, "MoistureAssessment")
    project = project_or_404(a["project_id"])
    require_contractor_owner(project, uid)
    if a["status"] == "ACCEPTED":
        fail("ERR_ALREADY_TERMINAL", "An ACCEPTED assessment is terminal")
    if a["status"] != "REJECTED":
        fail("ERR_INVALID_STATE", "Only a REJECTED assessment can be reopened")
    body = get_body()
    remediation_notes = v_str(body, "remediation_notes")
    readings = _readings_shape(body)
    # Post-remediation readings overwrite prior readings; kind forced to
    # VERIFICATION; score/band cleared until the next submit (PRD §3.2).
    a["remediation_notes"] = remediation_notes
    a["slab_moisture_lbs"] = readings["slab_moisture_lbs"]
    a["interior_rh_pct"] = readings["interior_rh_pct"]
    a["efflorescence_observed"] = readings["efflorescence_observed"]
    a["grading_deficit"] = readings["grading_deficit"]
    a["assessment_kind"] = "VERIFICATION"
    a["moisture_risk_score"] = None
    a["risk_band"] = None
    a["status"] = "DRAFT"
    touch(a)
    return ok(ser_assessment(a))
