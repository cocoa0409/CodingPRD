"""The deliverable checklist: manual items, the prerequisite DAG, submit,
decide and waive (PRD §3.5)."""

from flask import Blueprint

import db
import errors as E
import middleware as M
import response as R
import validation as V
from routes import common
from services import core

bp = Blueprint("deliverables", __name__)

LIVE_STATUSES = ("PENDING", "SUBMITTED", "APPROVED", "REJECTED", "WAIVED")
DECISIONS = ("APPROVE", "REJECT")


def _closes_cycle(row_id, prerequisite_id):
    """True when pointing ``row_id`` at ``prerequisite_id`` closes a loop.

    A self-edge is the shortest loop, so the walk starts at the proposed
    prerequisite and follows the existing chain rather than comparing endpoints.
    """
    seen = set()
    cursor = prerequisite_id
    while cursor is not None:
        if row_id is not None and cursor == row_id:
            return True
        if cursor in seen:
            return True
        seen.add(cursor)
        parent = db.deliverables.get(cursor)
        if parent is None:
            return False
        cursor = parent.get("prerequisite_deliverable_id")
    return False


# ---------------------------------------------------------------------------
# creation and reads
# ---------------------------------------------------------------------------
@bp.post("/innovation-projects/<project_id>/deliverables")
def create_deliverable(project_id):
    M.authenticate("InnovationLead", "GateChair")
    project = common.project(project_id)
    data = V.body()
    gate_id = V.id_field(data, "gate_id")
    deliverable_type = V.enum_field(data, "deliverable_type", V.DELIVERABLE_TYPES)
    owner_function = V.enum_field(data, "owner_function", V.FUNCTIONS)
    due_raw, due_dt = V.datetime_field(data, "due_at", required=False)
    prerequisite_id = V.id_field(data, "prerequisite_deliverable_id", required=False)

    gate = common.stage_gate(gate_id)
    if prerequisite_id is not None:
        common.prerequisite(prerequisite_id)

    if project["dev_status"] not in ("IDEA", "SCREENED", "PILOT_QUALIFIED",
                                    "LAUNCH_READY"):
        E.fail(E.ERR_PROJECT_INVALID_STATE,
               "dev_status %s does not admit new checklist items."
               % project["dev_status"])

    if prerequisite_id is not None and _closes_cycle(None, prerequisite_id):
        E.fail(E.ERR_DELIVERABLE_CYCLE,
               "The proposed prerequisite edge closes a cycle.")

    for row in core.project_deliverables(project["id"]):
        if (row["gate_id"] == gate["id"]
                and row["deliverable_type"] == deliverable_type
                and row["status"] in LIVE_STATUSES):
            E.fail(E.ERR_DUPLICATE_DELIVERABLE_TYPE,
                   "A live %s item already exists on this gate checklist."
                   % deliverable_type)

    row = core.new_row(db.deliverables, {
        "project_id": project["id"],
        "gate_id": gate["id"],
        "deliverable_type": deliverable_type,
        "owner_function": owner_function,
        "prerequisite_deliverable_id": prerequisite_id,
        "status": "PENDING",
        "due_at": due_raw,
        "evidence_url": None,
        "submitted_by_user_id": None,
        "decided_by_user_id": None,
        "submission_count": 0,
    })
    row["_dt_due_at"] = due_dt
    return R.object_response(row, 201)


@bp.get("/deliverables")
def list_deliverables():
    M.reader()
    rows = M.apply_filters(db.rows(db.deliverables), {
        "project_id": "project_id",
        "gate_id": "gate_id",
        "prerequisite_deliverable_id": "prerequisite_deliverable_id",
        "status": "status",
        "owner_function": "owner_function",
    })
    rows = M.order(rows, [(M.by("created_at"), False),
                          (M.by("deliverable_type"), False)])
    page, limit, offset, total = M.page(rows)
    return R.list_response(page, limit, offset, total)


@bp.get("/deliverables/<deliverable_id>")
def read_deliverable(deliverable_id):
    M.reader()
    return R.object_response(common.deliverable(deliverable_id))


# ---------------------------------------------------------------------------
# submit / decide / waive
# ---------------------------------------------------------------------------
@bp.post("/deliverables/<deliverable_id>/submit")
def submit_deliverable(deliverable_id):
    user_id = M.authenticate("InnovationLead", "RnDLead", "FunctionalReviewer",
                             "SalesAccountManager")
    row = common.deliverable(deliverable_id)
    data = V.body()
    evidence_url = V.string_field(data, "evidence_url", max_len=500)

    if row["status"] not in ("PENDING", "REJECTED"):
        E.fail(E.ERR_DELIVERABLE_INVALID_STATE,
               "A %s item takes no submission." % row["status"])
    project = db.projects.get(row["project_id"])
    if project is not None and project["dev_status"] in core.TERMINAL_DEV:
        E.fail(E.ERR_DELIVERABLE_INVALID_STATE,
               "The owning project is %s." % project["dev_status"])

    prerequisite_id = row.get("prerequisite_deliverable_id")
    if prerequisite_id is not None:
        parent = db.deliverables.get(prerequisite_id)
        if parent is None or parent["status"] not in ("APPROVED", "WAIVED"):
            E.fail(E.ERR_PREREQUISITE_NOT_SATISFIED,
                   "The prerequisite item is not yet APPROVED or WAIVED.")

    changes = {
        "status": "SUBMITTED",
        "evidence_url": evidence_url,
        "submitted_by_user_id": user_id,
        "submission_count": row["submission_count"] + 1,
    }
    if row["status"] == "REJECTED":
        changes["decided_by_user_id"] = None
    core.apply(row, changes)
    return R.object_response(row, 200)


@bp.post("/deliverables/<deliverable_id>/decide")
def decide_deliverable(deliverable_id):
    user_id = M.authenticate("FunctionalReviewer")
    row = common.deliverable(deliverable_id)
    data = V.body()
    decision = V.enum_field(data, "decision", DECISIONS)
    V.string_field(data, "comment", required=False, max_len=1000)

    if row["status"] != "SUBMITTED":
        E.fail(E.ERR_DELIVERABLE_INVALID_STATE,
               "Only a SUBMITTED item may be decided; this one is %s."
               % row["status"])
    if row.get("submitted_by_user_id") == user_id:
        E.fail(E.ERR_SELF_APPROVAL_FORBIDDEN,
               "The submitter of an item may not decide it.")

    core.apply(row, {
        "status": "APPROVED" if decision == "APPROVE" else "REJECTED",
        "decided_by_user_id": user_id,
    })

    if decision == "APPROVE" and row["deliverable_type"] in V.READINESS_TYPES:
        project = db.projects.get(row["project_id"])
        if project is not None:
            core.recompute_launch_readiness(project)
    return R.object_response(row, 200)


@bp.post("/deliverables/<deliverable_id>/waive")
def waive_deliverable(deliverable_id):
    M.authenticate("GateChair")
    row = common.deliverable(deliverable_id)
    data = V.body()
    V.string_field(data, "reason", max_len=500)

    if row["status"] not in ("PENDING", "SUBMITTED", "REJECTED"):
        E.fail(E.ERR_DELIVERABLE_INVALID_STATE,
               "A %s item may not be waived." % row["status"])
    if row["deliverable_type"] == "REGULATORY_CLEARANCE":
        E.fail(E.ERR_REGULATORY_WAIVER_FORBIDDEN,
               "A REGULATORY_CLEARANCE item can never be waived.")

    core.apply(row, {"status": "WAIVED"})
    return R.object_response(row, 200)


@bp.post("/deliverables/<deliverable_id>/set-prerequisite")
def set_prerequisite(deliverable_id):
    M.authenticate("InnovationLead", "GateChair")
    row = common.deliverable(deliverable_id)
    data = V.body()
    prerequisite_id = V.id_field(data, "prerequisite_deliverable_id")
    common.prerequisite(prerequisite_id)

    if _closes_cycle(row["id"], prerequisite_id):
        E.fail(E.ERR_DELIVERABLE_CYCLE,
               "The proposed prerequisite edge closes a cycle.")

    core.apply(row, {"prerequisite_deliverable_id": prerequisite_id})
    return R.object_response(row, 200)
