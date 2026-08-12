"""Inspection endpoints and the certification cascade (PRD §3.8)."""
from datetime import timedelta

from flask import Blueprint, request

from db import stores, now_ts, clock_now, clock_date
from errors import fail
from response import ok
from serializers import ser_inspection
from services import (
    INSPECTION_TERMINAL, PHASE_TERMINAL, WARRANTY_TERM_DAYS,
    advance_project, touch,
)
from validation import auth, require_role, get_body, v_str, v_enum
from routes.common import (
    project_or_404, get_or_404, require_contractor_owner, new_entity,
    list_response,
)

bp = Blueprint("inspections", __name__)

INSPECTION_TYPES = {"ROUGH_IN", "FINAL"}
RESULT_OUTCOMES = {"PASSED", "FAILED"}


@bp.post("/api/projects/<project_id>/inspections")
def create_inspection(project_id):
    role, uid = auth()
    require_role(role, "Contractor")
    project = project_or_404(project_id)
    require_contractor_owner(project, uid)
    body = get_body()
    # Priority 5: work_phase_id body reference must resolve.
    raw_phase = body.get("work_phase_id")
    phase = None
    if isinstance(raw_phase, str):
        phase = stores["work_phases"].get(raw_phase)
        if phase is None:
            fail("ERR_REFERENCED_NOT_FOUND", "work_phase_id does not reference an existing work phase")
    # Priority 7: inspections only while IN_PROGRESS.
    if project["status"] != "IN_PROGRESS":
        fail("ERR_PROJECT_STATE_FORBIDS", "Inspections open only while the project is IN_PROGRESS")
    itype = body.get("type")
    # Priority 20: a FINAL request requires no EXPIRED permit on the project.
    if itype == "FINAL":
        if any(
            p["project_id"] == project_id and p["status"] == "EXPIRED"
            for p in stores["permits"].values()
        ):
            fail("ERR_PERMIT_EXPIRED", "A permit on this project is EXPIRED")
    # Priority 22: inspection targeting.
    if itype == "ROUGH_IN":
        if phase is None or phase["project_id"] != project_id or phase["status"] != "IN_PROGRESS":
            fail("ERR_PHASES_INCOMPLETE", "ROUGH_IN requires the work_phase_id of an IN_PROGRESS phase of this project")
    elif itype == "FINAL":
        if any(
            p["project_id"] == project_id and p["status"] not in PHASE_TERMINAL
            for p in stores["work_phases"].values()
        ):
            fail("ERR_PHASES_INCOMPLETE", "FINAL requires every phase COMPLETED or CANCELLED")
    # Priority 26: shape.
    itype = v_enum(body, "type", INSPECTION_TYPES)
    if raw_phase is not None and not isinstance(raw_phase, str):
        fail("ERR_INVALID_REQUEST", "work_phase_id must be a string")
    e = new_entity({
        "project_id": project_id,
        # work_phase_id is required exactly when type is ROUGH_IN, null for FINAL.
        "work_phase_id": raw_phase if itype == "ROUGH_IN" else None,
        "type": itype,
        "result_notes": None,
        "resulted_at": None,
        "status": "REQUESTED",
    })
    stores["inspections"][e["id"]] = e
    return ok(ser_inspection(e), 201)


@bp.get("/api/projects/<project_id>/inspections")
def list_inspections(project_id):
    auth()
    project_or_404(project_id)
    items = [i for i in stores["inspections"].values() if i["project_id"] == project_id]
    for key in ("type", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [i for i in items if i[key] == val]
    return list_response(items, ser_inspection)


@bp.get("/api/work-phases/<phase_id>/inspections")
def list_phase_inspections(phase_id):
    auth()
    get_or_404("work_phases", phase_id, "WorkPhase")
    items = [i for i in stores["inspections"].values() if i["work_phase_id"] == phase_id]
    return list_response(items, ser_inspection)


@bp.post("/api/inspections/<inspection_id>/record-result")
def record_result(inspection_id):
    role, uid = auth()
    require_role(role, "Inspector")
    ins = get_or_404("inspections", inspection_id, "Inspection")
    project = project_or_404(ins["project_id"])
    if ins["status"] in INSPECTION_TERMINAL:
        fail("ERR_ALREADY_TERMINAL", "Inspection is terminal and refuses further mutation")
    if ins["status"] != "REQUESTED":
        fail("ERR_INVALID_STATE", "Only a REQUESTED inspection can receive a result")
    body = get_body()
    outcome = v_enum(body, "outcome", RESULT_OUTCOMES)
    notes = v_str(body, "notes", required=False)
    ins["status"] = outcome
    ins["resulted_at"] = now_ts()
    ins["result_notes"] = notes
    touch(ins)
    if outcome == "PASSED" and ins["type"] == "FINAL":
        # Certification cascade (PRD §3.8).
        start = clock_date()
        end = start + timedelta(days=WARRANTY_TERM_DAYS)
        cert = new_entity({
            "project_id": project["id"],
            "issued_at": now_ts(),
            "warranty_start": start.isoformat(),
            "warranty_end": end.isoformat(),
            "_warranty_start_date": start,
            "_warranty_end_date": end,
            "status": "ACTIVE",
        })
        stores["certificates"][cert["id"]] = cert
        for p in stores["permits"].values():
            if p["project_id"] == project["id"] and p["status"] == "ISSUED":
                p["status"] = "CLOSED"
                touch(p)
        if project["status"] == "IN_PROGRESS":
            advance_project(project, "COMPLETED")
    return ok(ser_inspection(ins))
