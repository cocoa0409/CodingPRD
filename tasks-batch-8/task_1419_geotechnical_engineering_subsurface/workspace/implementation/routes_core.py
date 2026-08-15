"""Routes: clients, projects (+lifecycle transition), boring plans,
subcontractors, rig assignments."""

from flask import Blueprint, g, request

import calc
import serialize
from db import store
from errors import err
from helpers import (
    forbid_role,
    get_body,
    opt_str,
    paginate,
    req_dt,
    req_enum,
    req_int,
    req_num,
    req_str,
    require_roles,
    sorted_items,
)
from response import success

bp = Blueprint("core", __name__)

PROJECT_STATES = {
    "DRAFT",
    "SCOPED",
    "FIELD_AUTHORIZED",
    "FIELDWORK",
    "LAB_ANALYSIS",
    "REPORT_REVIEW",
    "ISSUED",
    "CONSTRUCTION_SUPPORT",
    "CLOSED",
}

PROJECT_TRANSITIONS = {
    ("DRAFT", "SCOPED"): "ProjectManager",
    ("SCOPED", "FIELD_AUTHORIZED"): "ProjectManager",
    ("FIELD_AUTHORIZED", "FIELDWORK"): "ProjectManager",
    ("FIELDWORK", "LAB_ANALYSIS"): "ProjectManager",
    ("LAB_ANALYSIS", "REPORT_REVIEW"): "SeniorEngineer",
    ("REPORT_REVIEW", "LAB_ANALYSIS"): "PrincipalEngineer",
    ("REPORT_REVIEW", "ISSUED"): "ProjectManager",
    ("ISSUED", "CONSTRUCTION_SUPPORT"): "ClientRep",
    ("CONSTRUCTION_SUPPORT", "CLOSED"): "ProjectManager",
}

PLAN_STATES = {"DRAFT", "SUBMITTED", "APPROVED", "LOCKED", "SUPERSEDED"}
PLAN_TRANSITIONS = {
    ("DRAFT", "SUBMITTED"): "StaffEngineer",
    ("SUBMITTED", "DRAFT"): "ProjectManager",
    ("SUBMITTED", "APPROVED"): "ProjectManager",
}

SUB_TRANSITIONS = {
    ("GOOD_STANDING", "SUSPENDED"): "FirmAdmin",
    ("SUSPENDED", "GOOD_STANDING"): "FirmAdmin",
}

RIG_STATES = {"SCHEDULED", "MOBILIZED", "DEMOBILIZED", "CANCELLED"}
RIG_TRANSITIONS = {
    ("SCHEDULED", "MOBILIZED"): "DrillingSub",
    ("MOBILIZED", "DEMOBILIZED"): "DrillingSub",
    ("SCHEDULED", "CANCELLED"): "ProjectManager",
    ("MOBILIZED", "CANCELLED"): "ProjectManager",
}


def get_client_or_404(cid):
    rec = store.clients.get(cid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "Client %s not found" % cid)
    return rec


def get_project_or_404(pid):
    rec = store.projects.get(pid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "Project %s not found" % pid)
    return rec


def get_plan_or_404(pid):
    rec = store.plans.get(pid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "BoringPlan %s not found" % pid)
    return rec


def clientrep_owns_project(project):
    """Entity-backed ownership: ClientRep's X-User-ID is the Client id."""
    if g.role == "ClientRep" and project["client_id"] != g.user_id:
        raise forbid_role("ClientRep does not own this project")


# --------------------------------------------------------------------------
# Clients
# --------------------------------------------------------------------------
@bp.route("/geo/clients", methods=["POST"])
@require_roles("FirmAdmin")
def create_client():
    body = get_body()
    rec = {
        "id": store.new_id(),
        "name": req_str(body, "name"),
        "contact_email": req_str(body, "contact_email"),
    }
    store.stamp(rec)
    store.clients[rec["id"]] = rec
    return success(serialize.client(rec), code=201)


@bp.route("/geo/clients/<cid>", methods=["GET"])
@require_roles("FirmAdmin", "ProjectManager", "ClientRep", "SeniorEngineer")
def get_client(cid):
    rec = get_client_or_404(cid)
    if g.role == "ClientRep" and rec["id"] != g.user_id:
        raise forbid_role("ClientRep may only read its own client record")
    return success(serialize.client(rec))


# --------------------------------------------------------------------------
# Projects
# --------------------------------------------------------------------------
@bp.route("/geo/projects", methods=["POST"])
@require_roles("FirmAdmin")
def create_project():
    body = get_body()
    client_id = req_str(body, "client_id")
    name = req_str(body, "name")
    site_address = req_str(body, "site_address")
    target_report_date, _ = req_dt(body, "target_report_date")
    base_fee_cents = req_int(body, "base_fee_cents", min_v=0)
    additional_auth_cap_cents = req_int(body, "additional_auth_cap_cents", min_v=0)
    assumed_gwt_depth_ft = req_num(body, "assumed_gwt_depth_ft")
    if client_id not in store.clients:
        raise err("ERR_VALIDATION", "client_id does not reference an existing client")
    rec = {
        "id": store.new_id(),
        "client_id": client_id,
        "name": name,
        "site_address": site_address,
        "target_report_date": target_report_date,
        "base_fee_cents": base_fee_cents,
        "additional_auth_cap_cents": additional_auth_cap_cents,
        "assumed_gwt_depth_ft": assumed_gwt_depth_ft,
        "status": "DRAFT",
    }
    store.stamp(rec)
    store.projects[rec["id"]] = rec
    return success(serialize.project(rec), code=201)


@bp.route("/geo/projects/<pid>", methods=["GET"])
@require_roles(
    "FirmAdmin",
    "ProjectManager",
    "StaffEngineer",
    "FieldGeologist",
    "SeniorEngineer",
    "PrincipalEngineer",
    "LabManager",
    "LabTechnician",
    "ClientRep",
    "DrillingSub",
)
def get_project(pid):
    rec = get_project_or_404(pid)
    clientrep_owns_project(rec)
    return success(serialize.project(rec))


@bp.route("/geo/projects", methods=["GET"])
@require_roles("FirmAdmin", "ProjectManager", "SeniorEngineer", "ClientRep")
def list_projects():
    items = list(store.projects.values())
    client_id = request.args.get("client_id")
    if client_id is not None:
        items = [p for p in items if p["client_id"] == client_id]
    if g.role == "ClientRep":
        items = [p for p in items if p["client_id"] == g.user_id]
    page, meta = paginate(sorted_items(items))
    return success([serialize.project(p) for p in page], "array", 200, meta)


# --------------------------------------------------------------------------
# Project lifecycle transition
# --------------------------------------------------------------------------
@bp.route("/geo/projects/<pid>/transition", methods=["POST"])
@require_roles("ProjectManager", "SeniorEngineer", "PrincipalEngineer", "ClientRep")
def project_transition(pid):
    project = get_project_or_404(pid)
    body = get_body()
    to = req_enum(body, "to", PROJECT_STATES)
    transition = (project["status"], to)
    actor = PROJECT_TRANSITIONS.get(transition)
    if actor is None:
        raise err(
            "ERR_INVALID_STATE",
            "Project in %s cannot transition to %s" % (project["status"], to),
        )
    if g.role != actor:
        raise forbid_role("Transition %s -> %s requires role %s" % (transition[0], to, actor))
    if actor == "ClientRep":
        clientrep_owns_project(project)

    if to == "SCOPED":
        if not any(
            p["project_id"] == pid and p["status"] in ("APPROVED", "LOCKED")
            for p in store.plans.values()
        ):
            raise err(
                "ERR_PROJECT_STATE_FORBIDS",
                "No boring plan of this project is APPROVED or LOCKED",
            )
    elif to == "FIELD_AUTHORIZED":
        plan = calc.active_plan(pid)
        plan_borings = (
            [b for b in store.borings.values() if b["boring_plan_id"] == plan["id"]]
            if plan
            else []
        )
        boring_ids = {b["id"] for b in plan_borings}
        if not any(
            ra["boring_id"] in boring_ids and ra["status"] == "SCHEDULED"
            for ra in store.rig_assignments.values()
        ):
            raise err(
                "ERR_PROJECT_STATE_FORBIDS",
                "No SCHEDULED rig assignment covers a boring of the active plan",
            )
        for b in plan_borings:
            if not any(
                c["boring_id"] == b["id"] and c["status"] in ("FILED", "CLEARED")
                for c in store.clearances.values()
            ):
                raise err(
                    "ERR_CLEARANCE_MISSING",
                    "Boring %s holds no clearance ticket in FILED or CLEARED" % b["id"],
                )
    elif to == "FIELDWORK":
        if calc.compute_posture(pid) == "FROZEN":
            raise err("ERR_POSTURE_FROZEN", "Project posture is FROZEN")
    elif to == "LAB_ANALYSIS" and project["status"] == "FIELDWORK":
        plan = calc.active_plan(pid)
        plan_borings = (
            [b for b in store.borings.values() if b["boring_plan_id"] == plan["id"]]
            if plan
            else []
        )
        if any(b["status"] not in ("CLOSED", "ABANDONED") for b in plan_borings):
            raise err(
                "ERR_PROJECT_STATE_FORBIDS",
                "Every boring of the active plan must be CLOSED or ABANDONED",
            )
    elif to == "REPORT_REVIEW":
        verified = any(
            a["project_id"] == pid
            and a["status"] == "VERIFIED"
            and a["data_status"] == "CURRENT"
            for a in store.analyses.values()
        )
        if not verified:
            raise err(
                "ERR_ANALYSIS_NOT_VERIFIED",
                "No VERIFIED FoundationAnalysis with CURRENT data exists",
            )
        if any(
            o["project_id"] == pid and o["status"] != "ACCEPTED"
            for o in store.orders.values()
        ):
            raise err(
                "ERR_ORDER_STATE_FORBIDS",
                "Every LabTestOrder of the project must be ACCEPTED",
            )
    elif to == "ISSUED":
        reports = [r for r in store.reports.values() if r["project_id"] == pid]
        top = max(reports, key=lambda r: (r["revision_no"], r["_seq"]), default=None)
        if top is None or top["status"] != "ISSUED":
            raise err(
                "ERR_REPORT_NOT_ISSUABLE",
                "The highest-revision report of the project is not ISSUED",
            )
    elif to == "CLOSED":
        if any(
            c["project_id"] == pid
            and c["status"] in ("SUBMITTED", "UNDER_REVIEW", "SUBSTANTIATED")
            for c in store.claims.values()
        ):
            raise err(
                "ERR_CLAIM_STATE_FORBIDS",
                "Open claims block project closeout",
            )
        if any(
            v["project_id"] == pid and v["status"] != "CLOSED"
            for v in store.visits.values()
        ):
            raise err(
                "ERR_INVALID_STATE",
                "Every ObservationVisit of the project must be CLOSED",
            )

    project["status"] = to
    store.bump(project)
    return success(serialize.project(project))


# --------------------------------------------------------------------------
# Boring plans
# --------------------------------------------------------------------------
@bp.route("/geo/projects/<pid>/boring-plans", methods=["POST"])
@require_roles("StaffEngineer")
def create_boring_plan(pid):
    project = get_project_or_404(pid)
    body = get_body()
    planned_boring_count = req_int(body, "planned_boring_count", min_v=0)
    planned_total_footage_ft = req_num(body, "planned_total_footage_ft", min_v=0)
    expected_project_version = req_int(body, "expected_project_version")
    supersedes_plan_id = opt_str(body, "supersedes_plan_id")
    if supersedes_plan_id is not None:
        target = store.plans.get(supersedes_plan_id)
        if target is None or target["project_id"] != pid:
            raise err(
                "ERR_VALIDATION",
                "supersedes_plan_id does not reference a plan of this project",
            )
    # OCC (category 5): stale view of the project's version is rejected.
    if expected_project_version != project["version"]:
        raise err(
            "ERR_STALE_PROJECT_VERSION",
            "expected_project_version does not match the project's current version",
        )
    siblings = [p for p in store.plans.values() if p["project_id"] == pid]
    revision_no = max((p["revision_no"] for p in siblings), default=0) + 1
    rec = {
        "id": store.new_id(),
        "project_id": pid,
        "revision_no": revision_no,
        "status": "DRAFT",
        "planned_boring_count": planned_boring_count,
        "planned_total_footage_ft": planned_total_footage_ft,
        "supersedes_plan_id": supersedes_plan_id,
        "mobilization_charged": False,
    }
    store.stamp(rec)
    store.plans[rec["id"]] = rec
    # Plan creation increments the parent Project's version (PRD 2.4).
    store.bump(project)
    return success(serialize.boring_plan(rec), code=201)


@bp.route("/geo/boring-plans/<pid>", methods=["GET"])
@require_roles(
    "FirmAdmin", "ProjectManager", "StaffEngineer", "SeniorEngineer", "PrincipalEngineer"
)
def get_boring_plan(pid):
    return success(serialize.boring_plan(get_plan_or_404(pid)))


@bp.route("/geo/boring-plans", methods=["GET"])
@require_roles("FirmAdmin", "ProjectManager", "StaffEngineer", "SeniorEngineer")
def list_boring_plans():
    items = list(store.plans.values())
    project_id = request.args.get("project_id")
    if project_id is not None:
        items = [p for p in items if p["project_id"] == project_id]
    supersedes_plan_id = request.args.get("supersedes_plan_id")
    if supersedes_plan_id is not None:
        items = [p for p in items if p["supersedes_plan_id"] == supersedes_plan_id]
    page, meta = paginate(sorted_items(items))
    return success([serialize.boring_plan(p) for p in page], "array", 200, meta)


@bp.route("/geo/boring-plans/<pid>/transition", methods=["POST"])
@require_roles("StaffEngineer", "ProjectManager")
def boring_plan_transition(pid):
    plan = get_plan_or_404(pid)
    body = get_body()
    to = req_enum(body, "to", PLAN_STATES)
    transition = (plan["status"], to)
    actor = PLAN_TRANSITIONS.get(transition)
    if actor is None:
        raise err(
            "ERR_INVALID_STATE",
            "BoringPlan in %s cannot transition to %s" % (plan["status"], to),
        )
    if g.role != actor:
        raise forbid_role("Transition to %s requires role %s" % (to, actor))

    if to == "SUBMITTED":
        if plan["planned_boring_count"] < 1:
            raise err("ERR_VALIDATION", "planned_boring_count must be at least 1")
    elif to == "APPROVED":
        project = store.projects[plan["project_id"]]
        if project["status"] not in ("DRAFT", "SCOPED"):
            raise err(
                "ERR_PROJECT_STATE_FORBIDS",
                "Project must be in DRAFT or SCOPED to approve a plan",
            )
        for other in store.plans.values():
            if (
                other["project_id"] == plan["project_id"]
                and other["id"] != plan["id"]
                and other["status"] in ("APPROVED", "LOCKED")
                and other["id"] != plan["supersedes_plan_id"]
            ):
                raise err(
                    "ERR_PLAN_ALREADY_ACTIVE",
                    "Another boring plan of the project is APPROVED or LOCKED",
                )
        # Supersede cascade: the named predecessor, if APPROVED, retires.
        if plan["supersedes_plan_id"]:
            pred = store.plans.get(plan["supersedes_plan_id"])
            if pred is not None and pred["status"] == "APPROVED":
                pred["status"] = "SUPERSEDED"
                store.bump(pred)

    plan["status"] = to
    store.bump(plan)
    return success(serialize.boring_plan(plan))


# --------------------------------------------------------------------------
# Subcontractors
# --------------------------------------------------------------------------
@bp.route("/geo/subcontractors", methods=["POST"])
@require_roles("FirmAdmin")
def create_subcontractor():
    body = get_body()
    name = req_str(body, "name")
    license_no = req_str(body, "license_no")
    day_rate_cents = req_int(body, "day_rate_cents", min_v=0)
    max_concurrent_rigs = req_int(body, "max_concurrent_rigs", min_v=0)
    if any(s["license_no"] == license_no for s in store.subcontractors.values()):
        raise err("ERR_DUPLICATE_TICKET", "license_no %s is already registered" % license_no)
    rec = {
        "id": store.new_id(),
        "name": name,
        "license_no": license_no,
        "day_rate_cents": day_rate_cents,
        "max_concurrent_rigs": max_concurrent_rigs,
        "standing": "GOOD_STANDING",
    }
    store.stamp(rec)
    store.subcontractors[rec["id"]] = rec
    return success(serialize.subcontractor(rec), code=201)


@bp.route("/geo/subcontractors/<sid>", methods=["GET"])
@require_roles("FirmAdmin", "ProjectManager", "DrillingSub")
def get_subcontractor(sid):
    rec = store.subcontractors.get(sid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "Subcontractor %s not found" % sid)
    if g.role == "DrillingSub" and rec["id"] != g.user_id:
        raise forbid_role("DrillingSub may only read its own subcontractor record")
    return success(serialize.subcontractor(rec))


@bp.route("/geo/subcontractors/<sid>/transition", methods=["POST"])
@require_roles("FirmAdmin")
def subcontractor_transition(sid):
    rec = store.subcontractors.get(sid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "Subcontractor %s not found" % sid)
    body = get_body()
    to = req_enum(body, "to", {"GOOD_STANDING", "SUSPENDED"})
    if (rec["standing"], to) not in SUB_TRANSITIONS:
        raise err(
            "ERR_INVALID_STATE",
            "Subcontractor in %s cannot transition to %s" % (rec["standing"], to),
        )
    rec["standing"] = to
    store.bump(rec)
    return success(serialize.subcontractor(rec))


# --------------------------------------------------------------------------
# Rig assignments
# --------------------------------------------------------------------------
@bp.route("/geo/borings/<bid>/rig-assignments", methods=["POST"])
@require_roles("ProjectManager")
def create_rig_assignment(bid):
    boring = store.borings.get(bid)
    if boring is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "Boring %s not found" % bid)
    body = get_body()
    subcontractor_id = req_str(body, "subcontractor_id")
    window_start_raw, window_start = req_dt(body, "window_start")
    window_end_raw, window_end = req_dt(body, "window_end")
    sub = store.subcontractors.get(subcontractor_id)
    if sub is None:
        raise err("ERR_VALIDATION", "subcontractor_id does not reference a subcontractor")
    project = calc.project_of_boring(boring)
    # Category 6: frozen-posture freeze gates new rig scheduling.
    if project is not None and calc.compute_posture(project["id"]) == "FROZEN":
        raise err("ERR_POSTURE_FROZEN", "Project posture is FROZEN")
    # Category 7: half-open overlap check against the same subcontractor.
    for ra in store.rig_assignments.values():
        if (
            ra["subcontractor_id"] == subcontractor_id
            and ra["status"] in ("SCHEDULED", "MOBILIZED")
            and window_start < ra["_window_end"]
            and ra["_window_start"] < window_end
        ):
            raise err(
                "ERR_RIG_DOUBLE_BOOKED",
                "Window overlaps an existing assignment of this subcontractor",
            )
    if sub["standing"] != "GOOD_STANDING":
        raise err("ERR_STANDING_SUSPENDED", "Subcontractor standing is SUSPENDED")
    # Category 8: temporal ordering is NOT a body-validation error.
    if not window_end > window_start:
        raise err("ERR_INVALID_WINDOW", "window_end must be strictly after window_start")

    rec = {
        "id": store.new_id(),
        "boring_id": bid,
        "subcontractor_id": subcontractor_id,
        "window_start": window_start_raw,
        "window_end": window_end_raw,
        "_window_start": window_start,
        "_window_end": window_end,
        "status": "SCHEDULED",
    }
    store.stamp(rec)
    store.rig_assignments[rec["id"]] = rec
    # The boring's first assignment advances it PLANNED -> SCHEDULED.
    if boring["status"] == "PLANNED":
        boring["status"] = "SCHEDULED"
        store.bump(boring)
    return success(serialize.rig_assignment(rec), code=201)


@bp.route("/geo/rig-assignments/<rid>", methods=["GET"])
@require_roles("FirmAdmin", "ProjectManager", "DrillingSub")
def get_rig_assignment(rid):
    rec = store.rig_assignments.get(rid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "RigAssignment %s not found" % rid)
    if g.role == "DrillingSub" and rec["subcontractor_id"] != g.user_id:
        raise forbid_role("DrillingSub does not own this rig assignment")
    return success(serialize.rig_assignment(rec))


@bp.route("/geo/rig-assignments", methods=["GET"])
@require_roles("FirmAdmin", "ProjectManager", "DrillingSub")
def list_rig_assignments():
    items = list(store.rig_assignments.values())
    boring_id = request.args.get("boring_id")
    if boring_id is not None:
        items = [r for r in items if r["boring_id"] == boring_id]
    subcontractor_id = request.args.get("subcontractor_id")
    if subcontractor_id is not None:
        items = [r for r in items if r["subcontractor_id"] == subcontractor_id]
    if g.role == "DrillingSub":
        items = [r for r in items if r["subcontractor_id"] == g.user_id]
    page, meta = paginate(sorted_items(items))
    return success([serialize.rig_assignment(r) for r in page], "array", 200, meta)


@bp.route("/geo/rig-assignments/<rid>/transition", methods=["POST"])
@require_roles("DrillingSub", "ProjectManager")
def rig_assignment_transition(rid):
    rec = store.rig_assignments.get(rid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "RigAssignment %s not found" % rid)
    body = get_body()
    to = req_enum(body, "to", RIG_STATES)
    transition = (rec["status"], to)
    actor = RIG_TRANSITIONS.get(transition)
    if actor is None:
        raise err(
            "ERR_INVALID_STATE",
            "RigAssignment in %s cannot transition to %s" % (rec["status"], to),
        )
    if g.role != actor:
        raise forbid_role("Transition to %s requires role %s" % (to, actor))

    boring = store.borings.get(rec["boring_id"])
    project = calc.project_of_boring(boring) if boring else None

    if to == "MOBILIZED":
        if g.user_id != rec["subcontractor_id"]:
            raise forbid_role("X-User-ID must equal the assignment's subcontractor_id")
        if project is not None and calc.compute_posture(project["id"]) == "FROZEN":
            raise err("ERR_POSTURE_FROZEN", "Project posture is FROZEN")
        sub = store.subcontractors[rec["subcontractor_id"]]
        if sub["standing"] != "GOOD_STANDING":
            raise err("ERR_STANDING_SUSPENDED", "Subcontractor standing is SUSPENDED")
    elif to == "DEMOBILIZED":
        if g.user_id != rec["subcontractor_id"]:
            raise forbid_role("X-User-ID must equal the assignment's subcontractor_id")
    elif to == "CANCELLED" and rec["status"] == "MOBILIZED":
        if boring is not None and boring["status"] in ("DRILLED", "LOGGED", "CLOSED"):
            raise err(
                "ERR_INVALID_STATE",
                "Cannot cancel a MOBILIZED assignment once the boring is DRILLED",
            )

    rec["status"] = to
    store.bump(rec)
    return success(serialize.rig_assignment(rec))
