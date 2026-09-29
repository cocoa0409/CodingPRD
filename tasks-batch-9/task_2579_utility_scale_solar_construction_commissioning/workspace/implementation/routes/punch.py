"""Punch list items and their closure workflow."""

from flask import Blueprint

import calc
import envelope
import store
import validate
from errors import fail
from routes.common import filter_eq, paginate, require_same_project
from validate import ALL_ROLES, authorize, body, e, i, s

bp = Blueprint("punch", __name__)

CATEGORIES = ("MECHANICAL", "ELECTRICAL", "CIVIL", "DOCUMENTATION")
SEVERITIES = ("CRITICAL", "MAJOR", "MINOR")


@bp.post("/solar/projects/<project_id>/punch-list-items")
def create_punch_item(project_id):
    authorize("OwnerEngineer")
    data = body(
        s("title"),
        e("category", CATEGORIES),
        e("severity", SEVERITIES),
        i("estimated_cost_cents", ge=0),
        s("block_id", required=False),
    )
    project = store.require_project(project_id)
    block_id = None
    if data["block_id"] is not None:
        block = store.require_block(data["block_id"])
        require_same_project(block["project_id"], project_id)
        block_id = block["id"]

    row = store.base()
    row.update(
        {
            "project_id": project_id,
            "block_id": block_id,
            "title": data["title"],
            "category": data["category"],
            "severity": data["severity"],
            "estimated_cost_cents": data["estimated_cost_cents"],
            "status": "OPEN",
            "closure_evidence_ref": None,
            "rejection_count": 0,
            "submitted_by_user_id": None,
            "decided_by_user_id": None,
        }
    )
    store.punch_items[row["id"]] = row
    calc.sync_project(project, force=True)
    return envelope.created(row)


@bp.get("/solar/punch-list-items/<item_id>")
def get_punch_item(item_id):
    authorize(*ALL_ROLES)
    return envelope.ok(store.require_punch_item(item_id))


@bp.get("/solar/punch-list-items")
def list_punch_items():
    authorize(*ALL_ROLES)
    rows = store.ordered(list(store.punch_items.values()))
    rows = filter_eq(rows, "project_id", validate.q("project_id"))
    rows = filter_eq(rows, "block_id", validate.q("block_id"))
    rows = filter_eq(rows, "status", validate.q("status"))
    rows = filter_eq(rows, "severity", validate.q("severity"))
    return paginate(rows)


@bp.post("/solar/punch-list-items/<item_id>/closure-submissions")
def submit_closure(item_id):
    user_id = authorize("InstallationForeman")
    data = body(s("closure_evidence_ref"))
    item = store.require_punch_item(item_id)
    if item["status"] != "OPEN":
        fail("ERR_PUNCH_ITEM_STATE_INVALID")
    item["status"] = "CLOSURE_SUBMITTED"
    item["closure_evidence_ref"] = data["closure_evidence_ref"]
    item["submitted_by_user_id"] = user_id
    store.touch(item)
    return envelope.ok(item)


@bp.post("/solar/punch-list-items/<item_id>/closure-decisions")
def decide_closure(item_id):
    user_id = authorize("OwnerEngineer")
    data = body(e("decision", ("APPROVE", "REJECT", "WAIVE")), s("note", required=False))
    item = store.require_punch_item(item_id)
    if item["status"] != "CLOSURE_SUBMITTED":
        fail("ERR_PUNCH_ITEM_STATE_INVALID")
    if item["submitted_by_user_id"] == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES")

    decision = data["decision"]
    if decision == "APPROVE":
        item["status"] = "CLOSED"
    elif decision == "WAIVE":
        item["status"] = "WAIVED"
    else:
        item["status"] = "OPEN"
        item["rejection_count"] += 1
    item["decided_by_user_id"] = user_id
    store.touch(item)
    project = store.projects.get(item["project_id"])
    if project is not None:
        calc.sync_project(project)
    return envelope.ok(item)
