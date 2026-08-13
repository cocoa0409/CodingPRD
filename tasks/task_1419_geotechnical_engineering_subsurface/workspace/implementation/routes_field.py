"""Routes: borings (incl. offsets and the drilling machine), utility
clearances, and samples (chain of custody)."""

from datetime import timedelta

from flask import Blueprint, g, request

import calc
import serialize
from db import store
from errors import err
from helpers import (
    forbid_role,
    get_body,
    opt_bool,
    opt_int,
    opt_num,
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

bp = Blueprint("field", __name__)

BORING_STATES = {
    "PLANNED",
    "SCHEDULED",
    "CLEARED",
    "DRILLED",
    "LOGGED",
    "CLOSED",
    "REFUSED",
    "ABANDONED",
}
BORING_TRANSITIONS = {
    ("SCHEDULED", "CLEARED"): "StaffEngineer",
    ("CLEARED", "DRILLED"): "DrillingSub",
    ("DRILLED", "LOGGED"): "FieldGeologist",
    ("LOGGED", "CLOSED"): "StaffEngineer",
    ("DRILLED", "REFUSED"): "DrillingSub",
    ("PLANNED", "ABANDONED"): "ProjectManager",
    ("SCHEDULED", "ABANDONED"): "ProjectManager",
}

CLEARANCE_STATES = {"FILED", "CLEARED", "CONFLICT_MARKED", "EXPIRED"}
CLEARANCE_TRANSITIONS = {
    ("FILED", "CLEARED"): "StaffEngineer",
    ("CONFLICT_MARKED", "CLEARED"): "StaffEngineer",
    ("FILED", "CONFLICT_MARKED"): "ProjectManager",
    ("CLEARED", "CONFLICT_MARKED"): "ProjectManager",
}

SAMPLER_TYPES = {"SPT", "SHELBY", "BULK", "ROCK_CORE"}
SAMPLE_STATES = {"COLLECTED", "IN_TRANSIT", "LAB_RECEIVED", "CONSUMED", "ARCHIVED", "LOST"}
SAMPLE_TRANSITIONS = {
    ("COLLECTED", "IN_TRANSIT"): "FieldGeologist",
    ("IN_TRANSIT", "LAB_RECEIVED"): "LabTechnician",
    ("IN_TRANSIT", "LOST"): "FieldGeologist",
    ("LAB_RECEIVED", "ARCHIVED"): "LabManager",
}


def get_boring_or_404(bid):
    rec = store.borings.get(bid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "Boring %s not found" % bid)
    return rec


def get_clearance_or_404(cid):
    rec = store.clearances.get(cid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "UtilityClearance %s not found" % cid)
    return rec


def _touch_project_of_boring(boring):
    project = calc.project_of_boring(boring)
    if project is not None:
        store.touch(project)
    return project


# --------------------------------------------------------------------------
# Borings
# --------------------------------------------------------------------------
def _create_boring_record(plan_id, boring_no, planned_depth_ft, access_difficult, offset_of):
    rec = {
        "id": store.new_id(),
        "boring_plan_id": plan_id,
        "offset_of_boring_id": offset_of,
        "boring_no": boring_no,
        "planned_depth_ft": planned_depth_ft,
        "access_difficult": access_difficult,
        "status": "PLANNED",
        "actual_depth_ft": None,
        "rock_depth_ft": None,
        "groundwater_depth_ft": None,
        "avg_n60": None,
        "refusal_depth_ft": None,
        "drilling_cost_cents": None,
    }
    store.stamp(rec)
    store.borings[rec["id"]] = rec
    return rec


@bp.route("/geo/boring-plans/<pid>/borings", methods=["POST"])
@require_roles("StaffEngineer")
def create_boring(pid):
    plan = store.plans.get(pid)
    if plan is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "BoringPlan %s not found" % pid)
    body = get_body()
    boring_no = req_str(body, "boring_no")
    planned_depth_ft = req_num(body, "planned_depth_ft", strict_gt=0)
    access_difficult = opt_bool(body, "access_difficult", False)
    if plan["status"] != "APPROVED":
        raise err(
            "ERR_PLAN_NOT_EDITABLE",
            "Borings may be added directly only to an APPROVED plan",
        )
    rec = _create_boring_record(pid, boring_no, planned_depth_ft, access_difficult, None)
    return success(serialize.boring(rec), code=201)


@bp.route("/geo/borings/<bid>", methods=["GET"])
@require_roles(
    "FirmAdmin",
    "ProjectManager",
    "StaffEngineer",
    "FieldGeologist",
    "DrillingSub",
    "SeniorEngineer",
)
def get_boring(bid):
    return success(serialize.boring(get_boring_or_404(bid)))


@bp.route("/geo/borings", methods=["GET"])
@require_roles(
    "FirmAdmin",
    "ProjectManager",
    "StaffEngineer",
    "FieldGeologist",
    "DrillingSub",
    "SeniorEngineer",
)
def list_borings():
    items = list(store.borings.values())
    boring_plan_id = request.args.get("boring_plan_id")
    if boring_plan_id is not None:
        items = [b for b in items if b["boring_plan_id"] == boring_plan_id]
    offset_of_boring_id = request.args.get("offset_of_boring_id")
    if offset_of_boring_id is not None:
        items = [b for b in items if b["offset_of_boring_id"] == offset_of_boring_id]
    page, meta = paginate(sorted_items(items))
    return success([serialize.boring(b) for b in page], "array", 200, meta)


@bp.route("/geo/borings/<bid>/transition", methods=["POST"])
@require_roles("StaffEngineer", "FieldGeologist", "DrillingSub", "ProjectManager")
def boring_transition(bid):
    boring = get_boring_or_404(bid)
    body = get_body()
    to = req_enum(body, "to", BORING_STATES)
    transition = (boring["status"], to)
    actor = BORING_TRANSITIONS.get(transition)
    if actor is None:
        raise err(
            "ERR_INVALID_STATE",
            "Boring in %s cannot transition to %s" % (boring["status"], to),
        )
    if g.role != actor:
        raise forbid_role("Transition to %s requires role %s" % (to, actor))

    # Category 4 body-domain checks that depend on the transition requested.
    payload = {}
    if to == "DRILLED":
        payload["actual_depth_ft"] = req_num(body, "actual_depth_ft", strict_gt=0)
        payload["rock_depth_ft"] = opt_num(body, "rock_depth_ft", 0, min_v=0)
        payload["groundwater_depth_ft"] = opt_num(body, "groundwater_depth_ft", None, min_v=0)
        payload["avg_n60"] = req_num(body, "avg_n60", min_v=0)
    elif to == "REFUSED":
        refusal = req_num(body, "refusal_depth_ft", min_v=0)
        if not refusal < boring["planned_depth_ft"]:
            raise err(
                "ERR_VALIDATION",
                "refusal_depth_ft must be strictly less than planned_depth_ft",
            )
        payload["refusal_depth_ft"] = refusal

    project = calc.project_of_boring(boring)
    plan = store.plans.get(boring["boring_plan_id"])

    if to == "CLEARED":
        tickets = [
            c
            for c in store.clearances.values()
            if c["boring_id"] == bid and c["status"] == "CLEARED"
        ]
        if not tickets:
            raise err(
                "ERR_CLEARANCE_MISSING",
                "No UtilityClearance of this boring is CLEARED",
            )
        if not any(store.clock <= c["_expires_on"] for c in tickets):
            raise err("ERR_CLEARANCE_EXPIRED", "The CLEARED clearance has expired")
        if project is not None and calc.compute_posture(project["id"]) == "FROZEN":
            raise err("ERR_POSTURE_FROZEN", "Project posture is FROZEN")
    elif to == "DRILLED":
        if project is None or project["status"] != "FIELDWORK":
            raise err(
                "ERR_PROJECT_STATE_FORBIDS",
                "Project must be in FIELDWORK to record drilling",
            )
        mobilized = any(
            ra["boring_id"] == bid
            and ra["status"] == "MOBILIZED"
            and ra["subcontractor_id"] == g.user_id
            for ra in store.rig_assignments.values()
        )
        if not mobilized:
            raise err(
                "ERR_RIG_NOT_MOBILIZED",
                "Drilling requires a MOBILIZED rig assignment owned by the caller",
            )
        tickets = [
            c
            for c in store.clearances.values()
            if c["boring_id"] == bid and c["status"] == "CLEARED"
        ]
        if not tickets or not any(store.clock <= c["_expires_on"] for c in tickets):
            raise err(
                "ERR_CLEARANCE_EXPIRED",
                "No CLEARED clearance of this boring is still valid",
            )
        if calc.compute_posture(project["id"]) == "FROZEN":
            raise err("ERR_POSTURE_FROZEN", "Project posture is FROZEN")
    elif to == "LOGGED":
        if not any(s["boring_id"] == bid for s in store.samples.values()):
            raise err(
                "ERR_INVALID_STATE",
                "At least one Sample of this boring must exist before LOGGED",
            )

    # ---- apply -------------------------------------------------------------
    if to == "DRILLED":
        boring["actual_depth_ft"] = payload["actual_depth_ft"]
        boring["rock_depth_ft"] = payload["rock_depth_ft"]
        boring["groundwater_depth_ft"] = payload["groundwater_depth_ft"]
        boring["avg_n60"] = payload["avg_n60"]
        first_of_plan = plan is not None and not plan["mobilization_charged"]
        boring["drilling_cost_cents"] = calc.drilling_cost_cents(
            payload["actual_depth_ft"],
            payload["rock_depth_ft"],
            boring["access_difficult"],
            first_of_plan,
        )
        if plan is not None and first_of_plan:
            plan["mobilization_charged"] = True
            if plan["status"] == "APPROVED":
                # First drill locks the plan; further borings only via offsets.
                plan["status"] = "LOCKED"
            store.bump(plan)
        # New drilling data stalenes every VERIFIED analysis of the project.
        if project is not None:
            for a in store.analyses.values():
                if a["project_id"] == project["id"] and a["status"] == "VERIFIED":
                    a["data_status"] = "STALE"
                    store.bump(a)
        boring["status"] = "DRILLED"
        store.bump(boring)
    elif to == "REFUSED":
        boring["refusal_depth_ft"] = payload["refusal_depth_ft"]
        boring["status"] = "REFUSED"
        store.bump(boring)
    elif to == "ABANDONED" and boring["status"] == "SCHEDULED":
        for ra in store.rig_assignments.values():
            if ra["boring_id"] == bid and ra["status"] in ("SCHEDULED", "MOBILIZED"):
                ra["status"] = "CANCELLED"
                store.bump(ra)
        boring["status"] = "ABANDONED"
        store.bump(boring)
    else:
        boring["status"] = to
        store.bump(boring)
    return success(serialize.boring(boring))


@bp.route("/geo/borings/<bid>/offsets", methods=["POST"])
@require_roles("StaffEngineer")
def create_offset_boring(bid):
    parent = get_boring_or_404(bid)
    body = get_body()
    boring_no = req_str(body, "boring_no")
    planned_depth_ft = req_num(body, "planned_depth_ft", strict_gt=0)
    access_difficult = opt_bool(body, "access_difficult", False)
    # Category 9: the parent must stand in REFUSED.
    if parent["status"] != "REFUSED":
        raise err(
            "ERR_OFFSET_PARENT_NOT_REFUSED",
            "Offset borings may only be created from a REFUSED parent",
        )
    plan = store.plans.get(parent["boring_plan_id"])
    tally = sum(1 for b in store.borings.values() if b["boring_plan_id"] == plan["id"])
    if tally >= plan["planned_boring_count"]:
        # Category 10: over-plan offsets consume an APPROVED authorization.
        auth = None
        for a in sorted_items(store.auths.values()):
            if (
                a["project_id"] == plan["project_id"]
                and a["status"] == "APPROVED"
                and a["consumed_boring_count"] < a["extra_boring_count"]
            ):
                auth = a
                break
        if auth is None:
            raise err(
                "ERR_EXTRA_BORINGS_EXHAUSTED",
                "No APPROVED authorization with remaining extra borings",
            )
        auth["consumed_boring_count"] += 1
        if auth["consumed_boring_count"] >= auth["extra_boring_count"]:
            auth["status"] = "EXHAUSTED"  # amount remains committed on the project
        store.bump(auth)
        store.touch(store.projects[plan["project_id"]])
    rec = _create_boring_record(
        plan["id"], boring_no, planned_depth_ft, access_difficult, parent["id"]
    )
    return success(serialize.boring(rec), code=201)


# --------------------------------------------------------------------------
# Utility clearances
# --------------------------------------------------------------------------
@bp.route("/geo/borings/<bid>/clearances", methods=["POST"])
@require_roles("StaffEngineer")
def create_clearance(bid):
    boring = get_boring_or_404(bid)
    body = get_body()
    ticket_number = req_str(body, "ticket_number")
    issued_on_raw, issued_on = req_dt(body, "issued_on")
    valid_days = opt_int(body, "valid_days", 14, min_v=1)
    if any(
        c["boring_id"] == bid and c["ticket_number"] == ticket_number
        for c in store.clearances.values()
    ):
        raise err(
            "ERR_DUPLICATE_TICKET",
            "ticket_number %s is already filed for this boring" % ticket_number,
        )
    rec = {
        "id": store.new_id(),
        "boring_id": bid,
        "ticket_number": ticket_number,
        "issued_on": issued_on_raw,
        "valid_days": valid_days,
        "_expires_on": issued_on + timedelta(days=valid_days),
        "status": "FILED",
    }
    store.stamp(rec)
    store.clearances[rec["id"]] = rec
    return success(serialize.clearance(rec), code=201)


@bp.route("/geo/clearances/<cid>", methods=["GET"])
@require_roles("FirmAdmin", "ProjectManager", "StaffEngineer")
def get_clearance(cid):
    return success(serialize.clearance(get_clearance_or_404(cid)))


@bp.route("/geo/clearances", methods=["GET"])
@require_roles("FirmAdmin", "ProjectManager", "StaffEngineer")
def list_clearances():
    items = list(store.clearances.values())
    boring_id = request.args.get("boring_id")
    if boring_id is not None:
        items = [c for c in items if c["boring_id"] == boring_id]
    page, meta = paginate(sorted_items(items))
    return success([serialize.clearance(c) for c in page], "array", 200, meta)


@bp.route("/geo/clearances/<cid>/transition", methods=["POST"])
@require_roles("StaffEngineer", "ProjectManager")
def clearance_transition(cid):
    rec = get_clearance_or_404(cid)
    body = get_body()
    to = req_enum(body, "to", CLEARANCE_STATES)
    transition = (rec["status"], to)
    actor = CLEARANCE_TRANSITIONS.get(transition)
    if actor is None:
        # EXPIRED is system-only; everything else is a wrong-from transition.
        raise err(
            "ERR_INVALID_STATE",
            "UtilityClearance in %s cannot transition to %s" % (rec["status"], to),
        )
    if g.role != actor:
        raise forbid_role("Transition to %s requires role %s" % (to, actor))

    if to == "CLEARED":
        if not store.clock <= rec["_expires_on"]:
            raise err("ERR_CLEARANCE_EXPIRED", "The clearance ticket has expired")

    rec["status"] = to
    store.bump(rec)
    # Posture depends on CONFLICT_MARKED tickets of active-plan borings.
    boring = store.borings.get(rec["boring_id"])
    if boring is not None:
        _touch_project_of_boring(boring)
    return success(serialize.clearance(rec))


# --------------------------------------------------------------------------
# Samples
# --------------------------------------------------------------------------
@bp.route("/geo/borings/<bid>/samples", methods=["POST"])
@require_roles("FieldGeologist")
def create_sample(bid):
    boring = get_boring_or_404(bid)
    body = get_body()
    depth_top_ft = req_num(body, "depth_top_ft", min_v=0)
    depth_bottom_ft = req_num(body, "depth_bottom_ft", min_v=0)
    sampler_type = req_enum(body, "sampler_type", SAMPLER_TYPES)
    recovery_pct = req_num(body, "recovery_pct", min_v=0)
    if recovery_pct > 100:
        raise err("ERR_VALIDATION", "recovery_pct must be between 0 and 100 inclusive")
    if not depth_top_ft < depth_bottom_ft:
        raise err("ERR_VALIDATION", "depth_top_ft must be strictly below depth_bottom_ft")
    # Parent-state gate: sampling only on borings in DRILLED or LOGGED.
    if boring["status"] not in ("DRILLED", "LOGGED"):
        raise err(
            "ERR_PROJECT_STATE_FORBIDS",
            "Samples may only be logged against borings in DRILLED or LOGGED",
        )
    actual = boring["actual_depth_ft"]
    if actual is not None and (depth_top_ft > actual or depth_bottom_ft > actual):
        raise err(
            "ERR_VALIDATION",
            "Sample depths must not exceed the boring's actual_depth_ft",
        )
    rec = {
        "id": store.new_id(),
        "boring_id": bid,
        "depth_top_ft": depth_top_ft,
        "depth_bottom_ft": depth_bottom_ft,
        "sampler_type": sampler_type,
        "recovery_pct": recovery_pct,
        "custody_status": "COLLECTED",
        "uscs_class": None,
    }
    store.stamp(rec)
    store.samples[rec["id"]] = rec
    return success(serialize.sample(rec), code=201)


@bp.route("/geo/samples/<sid>", methods=["GET"])
@require_roles(
    "FirmAdmin",
    "ProjectManager",
    "StaffEngineer",
    "FieldGeologist",
    "LabManager",
    "LabTechnician",
    "SeniorEngineer",
)
def get_sample(sid):
    rec = store.samples.get(sid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "Sample %s not found" % sid)
    return success(serialize.sample(rec))


@bp.route("/geo/samples", methods=["GET"])
@require_roles(
    "FirmAdmin",
    "ProjectManager",
    "StaffEngineer",
    "FieldGeologist",
    "LabManager",
    "LabTechnician",
    "SeniorEngineer",
)
def list_samples():
    items = list(store.samples.values())
    boring_id = request.args.get("boring_id")
    if boring_id is not None:
        items = [s for s in items if s["boring_id"] == boring_id]
    page, meta = paginate(sorted_items(items))
    return success([serialize.sample(s) for s in page], "array", 200, meta)


@bp.route("/geo/samples/<sid>/transition", methods=["POST"])
@require_roles("FieldGeologist", "LabTechnician", "LabManager")
def sample_transition(sid):
    rec = store.samples.get(sid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND", "Sample %s not found" % sid)
    body = get_body()
    to = req_enum(body, "to", SAMPLE_STATES)
    transition = (rec["custody_status"], to)
    actor = SAMPLE_TRANSITIONS.get(transition)
    if actor is None:
        raise err(
            "ERR_INVALID_STATE",
            "Sample in %s cannot transition to %s" % (rec["custody_status"], to),
        )
    if g.role != actor:
        raise forbid_role("Transition to %s requires role %s" % (to, actor))

    if to == "ARCHIVED":
        if any(
            o["sample_id"] == sid
            and o["status"]
            in ("REQUESTED", "AUTHORIZED", "IN_TEST", "RESULT_SUBMITTED", "REJECTED")
            for o in store.orders.values()
        ):
            raise err(
                "ERR_INVALID_STATE",
                "Open laboratory orders of this sample block archiving",
            )

    rec["custody_status"] = to
    store.bump(rec)
    return success(serialize.sample(rec))
