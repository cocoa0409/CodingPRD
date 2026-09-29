"""Pack artwork, claims and regulatory clearance (PRD §3.7)."""

from flask import Blueprint

import db
import errors as E
import middleware as M
import response as R
import validation as V
from routes import common
from services import core

bp = Blueprint("labels", __name__)

LABEL_DECISIONS = ("APPROVE", "APPROVE_WITH_CHANGES", "REJECT")


@bp.post("/innovation-projects/<project_id>/label-approvals")
def create_label(project_id):
    M.authenticate("InnovationLead")
    project = common.project(project_id)
    data = V.body()
    formulation_id = V.id_field(data, "formulation_id")
    label_version = V.string_field(data, "label_version", max_len=40)
    claims = V.string_array_field(data, "claims", min_items=1, max_items=10)

    formulation = common.formulation(formulation_id)
    if formulation["project_id"] != project["id"]:
        E.fail(E.ERR_FORMULATION_PROJECT_MISMATCH,
               "Formulation %s belongs to another project." % formulation["id"])

    row = core.new_row(db.label_approvals, {
        "project_id": project["id"],
        "formulation_id": formulation["id"],
        "label_version": label_version,
        "claims": claims,
        "status": "DRAFT",
        "unsupported_claims": [],
        "decided_by_user_id": None,
    })
    return R.object_response(row, 201)


@bp.get("/label-approvals")
def list_labels():
    M.reader()
    rows = M.apply_filters(db.rows(db.label_approvals), {
        "project_id": "project_id",
        "formulation_id": "formulation_id",
        "status": "status",
    })
    rows = M.order(rows)
    page, limit, offset, total = M.page(rows)
    return R.list_response(page, limit, offset, total)


@bp.get("/label-approvals/<label_approval_id>")
def read_label(label_approval_id):
    M.reader()
    return R.object_response(common.label(label_approval_id))


@bp.post("/label-approvals/<label_approval_id>/submit")
def submit_label(label_approval_id):
    M.authenticate("InnovationLead")
    row = common.label(label_approval_id)

    if row["status"] not in ("DRAFT", "REJECTED"):
        E.fail(E.ERR_LABEL_INVALID_STATE,
               "A %s label may not be submitted." % row["status"])
    formulation = db.formulations.get(row["formulation_id"])
    if formulation is None or formulation["status"] != "SHELF_LIFE_CLEARED":
        E.fail(E.ERR_FORMULATION_INVALID_STATE,
               "Claims may only be reviewed against a SHELF_LIFE_CLEARED "
               "formulation.")

    changes = {"status": "IN_REVIEW"}
    if row["status"] == "REJECTED":
        changes["unsupported_claims"] = []
    core.apply(row, changes)
    return R.object_response(row, 200)


@bp.post("/label-approvals/<label_approval_id>/decide")
def decide_label(label_approval_id):
    user_id = M.authenticate("RegulatoryApprover")
    row = common.label(label_approval_id)
    data = V.body()
    decision = V.enum_field(data, "decision", LABEL_DECISIONS)
    unsupported = V.string_array_field(data, "unsupported_claims", required=False)
    V.string_field(data, "comment", required=False, max_len=1000)

    if row["status"] != "IN_REVIEW":
        E.fail(E.ERR_LABEL_INVALID_STATE,
               "Only an IN_REVIEW label may be decided; this one is %s."
               % row["status"])

    if decision == "APPROVE_WITH_CHANGES" and not unsupported:
        E.fail(E.ERR_UNSUPPORTED_CLAIMS_REQUIRED,
               "APPROVE_WITH_CHANGES requires a non-empty unsupported_claims "
               "array.")

    status = {"APPROVE": "APPROVED",
              "APPROVE_WITH_CHANGES": "CONDITIONAL",
              "REJECT": "REJECTED"}[decision]
    changes = {"status": status, "decided_by_user_id": user_id}
    if unsupported is not None:
        changes["unsupported_claims"] = unsupported
    core.apply(row, changes)

    if status in ("APPROVED", "CONDITIONAL"):
        core.auto_approve(row["project_id"], "REGULATORY_CLEARANCE")
    return R.object_response(row, 200)
