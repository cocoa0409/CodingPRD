"""Work phase endpoints (PRD §3.6)."""
from flask import Blueprint, request

from db import stores, parse_date
from errors import fail
from response import ok
from serializers import ser_work_phase
from services import (
    TRADES, ROUGH_IN_TRADES, PHASE_TERMINAL, creates_cycle, zone_conflict,
    crew_capacity_exceeded, promote_successors, advance_project, touch,
)
from validation import (
    auth, require_role, get_body, v_str, v_int, v_arr, v_enum, v_date,
)
from routes.common import (
    project_or_404, get_or_404, require_contractor_owner, new_entity, list_response,
)

bp = Blueprint("phases", __name__)

PHASE_GATE = {"SCHEDULING", "IN_PROGRESS"}


def _assigned_phase_or_403(phase, uid):
    if phase["subcontractor_id"] != uid:
        fail("ERR_NOT_RESOURCE_OWNER", "Subcontractor is not the assigned crew of this phase")


@bp.post("/api/projects/<project_id>/work-phases")
def create_phase(project_id):
    role, uid = auth()
    require_role(role, "Contractor")
    project = project_or_404(project_id)
    require_contractor_owner(project, uid)
    body = get_body()
    # Priority 5: body references — subcontractor_id and predecessor_ids.
    sub_id = body.get("subcontractor_id")
    if isinstance(sub_id, str) and sub_id not in stores["subcontractors"]:
        fail("ERR_REFERENCED_NOT_FOUND", "subcontractor_id does not reference an existing subcontractor")
    raw_preds = body.get("predecessor_ids")
    preds_list = raw_preds if isinstance(raw_preds, list) else []
    pred_ids = [p for p in preds_list if isinstance(p, str)]
    for pid in pred_ids:
        if pid not in stores["work_phases"]:
            fail("ERR_REFERENCED_NOT_FOUND", "predecessor_ids references a phase that does not exist")
    # Priority 7: project state gate.
    if project["status"] not in PHASE_GATE:
        fail("ERR_PROJECT_STATE_FORBIDS", "Work phases open only in SCHEDULING or IN_PROGRESS")
    # Priority 16: predecessors must be non-CANCELLED phases of the same
    # project and the graph must stay acyclic.
    for pid in pred_ids:
        pred = stores["work_phases"].get(pid)
        if pred is None or pred["project_id"] != project_id or pred["status"] == "CANCELLED":
            fail("ERR_PHASE_CYCLE", "Predecessors must be existing, non-CANCELLED phases of this project")
    new_id_holder = new_entity({})  # reserve an id for the cycle check
    if creates_cycle(project_id, new_id_holder["id"], pred_ids):
        fail("ERR_PHASE_CYCLE", "predecessor_ids would create a cycle")
    # Priorities 17/18 need parseable dates; malformed dates fall to shape (26).
    start_d = parse_date(body.get("start_date"))
    end_d = parse_date(body.get("end_date"))
    zone_raw = body.get("zone")
    trade_raw = body.get("trade")
    crew_raw = body.get("crew_count")
    if start_d is not None and end_d is not None and isinstance(zone_raw, str):
        if zone_conflict(project_id, zone_raw, trade_raw, start_d, end_d):
            fail("ERR_ZONE_SCHEDULE_OVERLAP", "Zone interval collision or DRYWALL dust-buffer violation")
        if isinstance(crew_raw, int) and not isinstance(crew_raw, bool):
            if crew_capacity_exceeded(project_id, start_d, end_d, crew_raw):
                fail("ERR_CREW_CAPACITY_EXCEEDED", "Aggregate daily crew count would exceed 4")
    # Priority 26: shape.
    trade = v_enum(body, "trade", TRADES)
    zone = v_str(body, "zone")
    start_date = v_date(body, "start_date")
    end_date = v_date(body, "end_date")
    if parse_date(end_date) < parse_date(start_date):
        fail("ERR_INVALID_REQUEST", "start_date must not be after end_date")
    crew_count = v_int(body, "crew_count")
    subcontractor_id = v_str(body, "subcontractor_id")
    predecessor_ids = v_arr(body, "predecessor_ids", required=False) or []
    for pid in predecessor_ids:
        if not isinstance(pid, str):
            fail("ERR_INVALID_REQUEST", "predecessor_ids entries must be strings")
    e = new_id_holder
    e.update({
        "project_id": project_id,
        "subcontractor_id": subcontractor_id,
        "trade": trade,
        "zone": zone,
        "start_date": start_date,
        "end_date": end_date,
        "crew_count": crew_count,
        "predecessor_ids": predecessor_ids,
        "requires_rough_in": trade in ROUGH_IN_TRADES,
        "pre_block_status": None,
        # READY when no predecessors, else PLANNED (endpoint side effect).
        "status": "READY" if len(predecessor_ids) == 0 else "PLANNED",
    })
    stores["work_phases"][e["id"]] = e
    return ok(ser_work_phase(e), 201)


@bp.get("/api/projects/<project_id>/work-phases")
def list_project_phases(project_id):
    auth()
    project_or_404(project_id)
    items = [p for p in stores["work_phases"].values() if p["project_id"] == project_id]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return list_response(items, ser_work_phase)


@bp.get("/api/work-phases/<phase_id>")
def get_phase(phase_id):
    auth()
    return ok(ser_work_phase(get_or_404("work_phases", phase_id, "WorkPhase")))


@bp.get("/api/work-phases")
def list_phases():
    auth()
    items = list(stores["work_phases"].values())
    for key in ("subcontractor_id", "project_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [p for p in items if str(p.get(key)) == val]
    return list_response(items, ser_work_phase)


@bp.post("/api/work-phases/<phase_id>/start")
def start_phase(phase_id):
    role, uid = auth()
    require_role(role, "Subcontractor")
    phase = get_or_404("work_phases", phase_id, "WorkPhase")
    project = project_or_404(phase["project_id"])
    _assigned_phase_or_403(phase, uid)
    # Priority 7: project must be in SCHEDULING or IN_PROGRESS.
    if project["status"] not in PHASE_GATE:
        fail("ERR_PROJECT_STATE_FORBIDS", "Project status does not permit starting phases")
    if phase["status"] in PHASE_TERMINAL:
        fail("ERR_ALREADY_TERMINAL", "Phase is terminal and refuses further mutation")
    if phase["status"] != "READY":
        fail("ERR_INVALID_STATE", "Only a READY phase can be started")
    phase["status"] = "IN_PROGRESS"
    touch(phase)
    if project["status"] == "SCHEDULING":
        advance_project(project, "IN_PROGRESS")
    return ok(ser_work_phase(phase))


@bp.post("/api/work-phases/<phase_id>/complete")
def complete_phase(phase_id):
    role, uid = auth()
    require_role(role, "Subcontractor")
    phase = get_or_404("work_phases", phase_id, "WorkPhase")
    project = project_or_404(phase["project_id"])
    _assigned_phase_or_403(phase, uid)
    if phase["status"] in PHASE_TERMINAL:
        fail("ERR_ALREADY_TERMINAL", "Phase is terminal and refuses further mutation")
    if phase["status"] != "IN_PROGRESS":
        fail("ERR_INVALID_STATE", "Only an IN_PROGRESS phase can be completed")
    # Priority 23: rough-in trades need a PASSED ROUGH_IN inspection on this phase.
    if phase["requires_rough_in"]:
        passed = any(
            ins["project_id"] == project["id"]
            and ins["type"] == "ROUGH_IN"
            and ins["work_phase_id"] == phase["id"]
            and ins["status"] == "PASSED"
            for ins in stores["inspections"].values()
        )
        if not passed:
            fail("ERR_ROUGH_IN_REQUIRED", "Completing this trade requires a PASSED rough-in inspection")
    phase["status"] = "COMPLETED"
    touch(phase)
    promote_successors(project, phase)
    return ok(ser_work_phase(phase))


@bp.post("/api/work-phases/<phase_id>/cancel")
def cancel_phase(phase_id):
    role, uid = auth()
    require_role(role, "Contractor")
    phase = get_or_404("work_phases", phase_id, "WorkPhase")
    project = project_or_404(phase["project_id"])
    require_contractor_owner(project, uid)
    if phase["status"] in PHASE_TERMINAL:
        fail("ERR_ALREADY_TERMINAL", "Phase is terminal and refuses further mutation")
    if phase["status"] not in ("PLANNED", "READY"):
        fail("ERR_INVALID_STATE", "Only a PLANNED or READY phase can be cancelled directly")
    body = get_body()
    v_str(body, "reason", required=False)
    phase["status"] = "CANCELLED"
    phase["pre_block_status"] = None
    touch(phase)
    return ok(ser_work_phase(phase))
