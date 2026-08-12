"""Design package endpoints (PRD §3.3)."""
from flask import Blueprint

from db import stores
from errors import fail
from response import ok
from serializers import ser_design, ser_permit
from services import PACKAGE_TERMINAL, touch
from validation import auth, require_role, get_body, v_str, v_arr, v_enum, v_int, v_item_object
from routes.common import (
    project_or_404, get_or_404, require_contractor_owner,
    require_homeowner_owner, new_entity, list_response,
)

bp = Blueprint("designs", __name__)

DESIGN_GATE = {"ASSESSMENT", "DESIGN", "PERMITTING"}
RELOCATION_SYSTEMS = {"HVAC", "PLUMBING", "ELECTRICAL"}


def _has_accepted_assessment(project_id):
    return any(
        a["project_id"] == project_id and a["status"] == "ACCEPTED"
        for a in stores["assessments"].values()
    )


def _relocations_shape(body):
    items = v_arr(body, "mechanical_relocations")
    for item in items:
        v_item_object(item, "mechanical_relocations")
        v_enum(item, "system", RELOCATION_SYSTEMS)
        v_str(item, "description")
        v_int(item, "estimated_cents")
    return items


@bp.post("/api/projects/<project_id>/design-packages")
def create_design(project_id):
    role, uid = auth()
    require_role(role, "Contractor")
    project = project_or_404(project_id)
    require_contractor_owner(project, uid)
    body = get_body()
    if project["status"] not in DESIGN_GATE:
        fail("ERR_PROJECT_STATE_FORBIDS", "Project status does not permit design packages")
    layout_notes = v_str(body, "layout_notes")
    relocations = _relocations_shape(body)
    e = new_entity({
        "project_id": project_id,
        "layout_notes": layout_notes,
        "mechanical_relocations": relocations,
        "revision_number": 1,
        "revision_notes": None,
        "status": "DRAFT",
    })
    stores["designs"][e["id"]] = e
    return ok(ser_design(e), 201)


@bp.get("/api/projects/<project_id>/design-packages")
def list_designs(project_id):
    auth()
    project_or_404(project_id)
    items = [d for d in stores["designs"].values() if d["project_id"] == project_id]
    return list_response(items, ser_design)


@bp.get("/api/design-packages/<design_id>")
def get_design(design_id):
    auth()
    return ok(ser_design(get_or_404("designs", design_id, "DesignPackage")))


@bp.get("/api/design-packages/<design_id>/permits")
def list_design_permits(design_id):
    auth()
    get_or_404("designs", design_id, "DesignPackage")
    items = [p for p in stores["permits"].values() if p["pinned_design_id"] == design_id]
    return list_response(items, ser_permit)


@bp.post("/api/design-packages/<design_id>/submit")
def submit_design(design_id):
    role, uid = auth()
    require_role(role, "Contractor")
    d = get_or_404("designs", design_id, "DesignPackage")
    project = project_or_404(d["project_id"])
    require_contractor_owner(project, uid)
    if d["status"] in PACKAGE_TERMINAL:
        fail("ERR_ALREADY_TERMINAL", "Package is terminal and refuses further mutation")
    if d["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        fail("ERR_INVALID_STATE", "Only a DRAFT or REVISION_REQUESTED package can be submitted")
    # Priority 10: design submit requires an ACCEPTED moisture assessment.
    if not _has_accepted_assessment(project["id"]):
        fail("ERR_MOISTURE_NOT_CLEARED", "Design submit requires an ACCEPTED moisture assessment")
    if d["status"] == "REVISION_REQUESTED":
        d["revision_number"] += 1
    d["status"] = "SUBMITTED"
    touch(d)
    return ok(ser_design(d))


@bp.post("/api/design-packages/<design_id>/approve")
def approve_design(design_id):
    role, uid = auth()
    require_role(role, "Homeowner")
    d = get_or_404("designs", design_id, "DesignPackage")
    project = project_or_404(d["project_id"])
    require_homeowner_owner(project, uid)
    if d["status"] in PACKAGE_TERMINAL:
        fail("ERR_ALREADY_TERMINAL", "Package is terminal and refuses further mutation")
    if d["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Only a SUBMITTED package can be approved")
    for other in stores["designs"].values():
        if (
            other["project_id"] == project["id"]
            and other["id"] != d["id"]
            and other["status"] == "APPROVED"
        ):
            other["status"] = "SUPERSEDED"
            touch(other)
    d["status"] = "APPROVED"
    touch(d)
    project["approved_design_id"] = d["id"]
    if project["status"] == "DESIGN":
        project["status"] = "PERMITTING"
    touch(project)
    return ok(ser_design(d))


@bp.post("/api/design-packages/<design_id>/request-revision")
def request_revision(design_id):
    role, uid = auth()
    require_role(role, "Homeowner")
    d = get_or_404("designs", design_id, "DesignPackage")
    project = project_or_404(d["project_id"])
    require_homeowner_owner(project, uid)
    if d["status"] in PACKAGE_TERMINAL:
        fail("ERR_ALREADY_TERMINAL", "Package is terminal and refuses further mutation")
    if d["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Only a SUBMITTED package can receive a revision request")
    body = get_body()
    notes = v_str(body, "revision_notes")
    d["revision_notes"] = notes
    d["status"] = "REVISION_REQUESTED"
    touch(d)
    return ok(ser_design(d))
