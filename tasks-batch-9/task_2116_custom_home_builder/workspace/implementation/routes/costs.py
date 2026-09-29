"""Capturing cost: posting entries and the controller's review."""
from decimal import Decimal

from flask import Blueprint

from errors import AppError
from store import db, base_row, now, bump, ordered
from util import (
    authorize, check_staff_identity, parse_body, ok, ok_list, paginate, qfilter,
    req_str, opt_id, req_enum, req_money, req_dt, q2,
)
from routes.common import fetch
from services.constants import COST_ENTRY_TYPES
from services.ledger import recompute_project

bp = Blueprint("costs", __name__)

COST_READ_ROLES = ["PlatformAdmin", "ProjectManager", "Estimator", "Controller",
                   "Client", "Lender"]
REVIEW_DECISIONS = ("APPROVE", "REJECT")


@bp.post("/cost-entries")
def create_cost_entry():
    user_id, role = authorize(["ProjectManager"])
    body = parse_body()
    project_id = req_str(body, "project_id")
    entry_type = req_enum(body, "entry_type", COST_ENTRY_TYPES)
    cost_code = req_str(body, "cost_code")
    amount = req_money(body, "amount", minimum=Decimal("0"), exclusive_min=True)
    incurred_at = req_dt(body, "incurred_at")
    subcontractor_id = opt_id(body, "subcontractor_id")
    source_allowance_item_id = opt_id(body, "source_allowance_item_id")

    if entry_type == "ALLOWANCE_ACTUAL" and source_allowance_item_id is None:
        raise AppError("ERR_INVALID_REQUEST",
                       "source_allowance_item_id is required for an ALLOWANCE_ACTUAL entry.")

    # ladder step 6
    project = db.projects.get(project_id)
    if project is None:
        raise AppError("ERR_PROJECT_NOT_FOUND")
    if subcontractor_id is not None and subcontractor_id not in db.subcontractors:
        raise AppError("ERR_SUBCONTRACTOR_NOT_FOUND")
    source_item = None
    if source_allowance_item_id is not None:
        source_item = db.allowance_items.get(source_allowance_item_id)
        if source_item is None:
            raise AppError("ERR_ALLOWANCE_ITEM_NOT_FOUND")

    check_staff_identity(user_id, role)

    # ladder step 22
    if source_item is not None and source_item["project_id"] != project_id:
        raise AppError("ERR_ALLOWANCE_PROJECT_MISMATCH")

    row = base_row()
    row.update({
        "project_id": project_id,
        "subcontractor_id": subcontractor_id,
        "source_allowance_item_id": source_allowance_item_id,
        "draw_request_id": None,
        "approved_by_staff_id": None,
        "entry_type": entry_type,
        "cost_code": cost_code,
        "amount": q2(amount),
        "incurred_at": incurred_at,
        "status": "PENDING",
        "approved_at": None,
        "paid_at": None,
    })
    db.cost_entries[row["id"]] = row
    return ok(row, 201)


@bp.get("/cost-entries/<entry_id>")
def get_cost_entry(entry_id):
    user_id, role = authorize(COST_READ_ROLES)
    entry = fetch("cost_entries", entry_id)
    check_staff_identity(user_id, role)
    return ok(entry, 200)


@bp.get("/cost-entries")
def list_cost_entries():
    user_id, role = authorize(COST_READ_ROLES)
    check_staff_identity(user_id, role)
    rows = ordered(db.cost_entries.values())
    for name in ("project_id", "subcontractor_id", "source_allowance_item_id",
                 "draw_request_id", "approved_by_staff_id", "status"):
        value = qfilter(name)
        if value:
            rows = [r for r in rows if r.get(name) == value]
    page, meta = paginate(rows)
    return ok_list(page, meta)


@bp.post("/cost-entries/<entry_id>/review")
def review_cost_entry(entry_id):
    user_id, role = authorize(["Controller"])
    entry = fetch("cost_entries", entry_id)
    body = parse_body()
    decision = req_enum(body, "decision", REVIEW_DECISIONS)
    check_staff_identity(user_id, role)

    # ladder step 10
    if entry["status"] != "PENDING":
        raise AppError("ERR_COST_ENTRY_INVALID_STATE")

    project = db.projects.get(entry["project_id"])

    if decision == "REJECT":
        entry["status"] = "REJECTED"
        bump(entry)
        return ok(entry, 200)

    entry["status"] = "APPROVED"
    entry["approved_by_staff_id"] = user_id
    entry["approved_at"] = now()
    bump(entry)
    if project is not None:
        recompute_project(project)
    return ok(entry, 200)
