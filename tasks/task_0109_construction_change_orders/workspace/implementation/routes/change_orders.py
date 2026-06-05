"""Change-order endpoints (PRD §3.2)."""
from flask import Blueprint, request

import db
import helpers as h
import services
from errors import (
    err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_STALE_PROJECT_VERSION,
    ERR_DUPLICATE_ITEM_NO, ERR_LINE_EDITS_UNBALANCED, ERR_INVALID_REQUEST,
)
from middleware import authenticate, require_role
from response import success

bp = Blueprint("change_orders", __name__)

LINE_EDIT_ACTIONS = {"ADD", "ADJUST"}


def _get_co_or_404(co_id):
    co = db.change_orders.get(co_id)
    if co is None:
        raise err(ERR_NOT_FOUND, "ChangeOrder not found.")
    return co


def _validate_line_edits(value):
    if not isinstance(value, list):
        raise err(ERR_INVALID_REQUEST, "line_edits must be an array.")
    out = []
    for edit in value:
        if not isinstance(edit, dict):
            raise err(ERR_INVALID_REQUEST, "Each line_edit must be an object.")
        if "action" not in edit or "item_no" not in edit \
                or "scheduled_value_delta_cents" not in edit:
            raise err(ERR_INVALID_REQUEST,
                      "line_edit requires action, item_no, scheduled_value_delta_cents.")
        action = h.as_enum(edit["action"], "line_edit.action", LINE_EDIT_ACTIONS)
        item_no = h.as_nonempty_string(edit["item_no"], "line_edit.item_no")
        delta = h.as_int(edit["scheduled_value_delta_cents"], "scheduled_value_delta_cents")
        normalized = {
            "action": action,
            "item_no": item_no,
            "scheduled_value_delta_cents": delta,
        }
        if edit.get("description") is not None:
            normalized["description"] = h.as_string(edit["description"], "line_edit.description")
        if edit.get("retainage_pct") is not None:
            normalized["retainage_pct"] = h.as_number(
                edit["retainage_pct"], "line_edit.retainage_pct", minimum=0, maximum=0.20)
        out.append(normalized)
    return out


@bp.post("/change-orders")
def create_change_order():
    _uid, role = authenticate()
    require_role(role, {"Contractor"})
    body = h.get_json()
    h.require_fields(body, ["project_id", "co_number", "change_order_amount_cents", "line_edits"])

    project_id = h.as_string(body["project_id"], "project_id")
    project = db.projects.get(project_id)
    if project is None:
        raise err(ERR_NOT_FOUND, "Project not found.")

    co_number = h.as_nonempty_string(body["co_number"], "co_number")
    amount = h.as_int(body["change_order_amount_cents"], "change_order_amount_cents")
    line_edits = _validate_line_edits(body["line_edits"])

    record = {
        "project_id": project_id,
        "co_number": co_number,
        "change_order_amount_cents": amount,
        "line_edits": line_edits,
        "status": "DRAFT",
        "submitted_by_user_id": None,
        "approved_by_user_id": None,
    }
    db.stamp_create(record)
    db.change_orders[record["id"]] = record
    return success(h.change_order_out(record), status=201)


@bp.get("/change-orders/<co_id>")
def get_change_order(co_id):
    _uid, role = authenticate()
    require_role(role, {"Owner", "Contractor", "Architect"})
    return success(h.change_order_out(_get_co_or_404(co_id)))


@bp.get("/change-orders")
def list_change_orders():
    _uid, role = authenticate()
    require_role(role, {"Owner", "Contractor", "Architect"})
    limit, offset = h.parse_pagination()
    project_id = request.args.get("project_id")
    status = request.args.get("status")
    records = list(db.change_orders.values())
    if project_id:
        records = [r for r in records if r["project_id"] == project_id]
    if status:
        records = [r for r in records if r["status"] == status]
    page, meta = h.paginate(records, limit, offset)
    return success([h.change_order_out(r) for r in page], pagination=meta)


@bp.post("/change-orders/<co_id>/submit")
def submit_change_order(co_id):
    uid, role = authenticate()
    require_role(role, {"Contractor"})
    co = _get_co_or_404(co_id)
    project = db.projects.get(co["project_id"])
    # State: DRAFT and parent project ACTIVE.
    if co["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "ChangeOrder is not DRAFT.")
    if project is None or project["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Parent project is not ACTIVE.")
    co["status"] = "SUBMITTED"
    co["submitted_by_user_id"] = uid
    db.touch(co)
    return success(h.change_order_out(co))


@bp.post("/change-orders/<co_id>/approve")
def approve_change_order(co_id):
    uid, role = authenticate()
    require_role(role, {"Owner"})
    co = _get_co_or_404(co_id)
    project = db.projects.get(co["project_id"])
    body = h.get_json()

    # Validation priority (PRD §2.10): state -> ... -> duplicate item ->
    # line-edits unbalanced -> stale version. expected_project_version is a
    # required field for this transition (PRD §3.2 / §2.6).
    if co["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "ChangeOrder is not SUBMITTED.")
    if project is None or project["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Parent project is not ACTIVE.")

    # Duplicate-item-no (priority 10) precedes line-edits-unbalanced (11) and
    # stale-version (16) in the ordering; field-shape (ERR_INVALID_REQUEST) is
    # lowest. Validate expected_project_version presence/shape as field-shape.
    h.require_fields(body, ["expected_project_version"])
    expected = h.as_int(body["expected_project_version"], "expected_project_version")

    active = services.active_sov_lines(project["id"])
    active_by_item = {s["item_no"]: s for s in active}
    for edit in co["line_edits"]:
        if edit["action"] == "ADJUST":
            if edit["item_no"] not in active_by_item:
                raise err(ERR_DUPLICATE_ITEM_NO,
                          "ADJUST names an item_no with no ACTIVE SovLine.")
        else:  # ADD
            if edit["item_no"] in active_by_item:
                raise err(ERR_DUPLICATE_ITEM_NO,
                          "ADD item_no already used by an ACTIVE SovLine.")

    # Balance check (priority 11).
    if sum(e["scheduled_value_delta_cents"] for e in co["line_edits"]) \
            != co["change_order_amount_cents"]:
        raise err(ERR_LINE_EDITS_UNBALANCED,
                  "Sum of line_edit deltas != change_order_amount_cents.")

    # OCC stale-version (priority 16).
    if expected != project["version"]:
        raise err(ERR_STALE_PROJECT_VERSION, "expected_project_version is stale.")

    # Apply edits (cascade A->B). ADDs must not collide with each other either;
    # build a working active-item set as we go.
    working_items = set(active_by_item.keys())
    for edit in co["line_edits"]:
        if edit["action"] == "ADD":
            if edit["item_no"] in working_items:
                raise err(ERR_DUPLICATE_ITEM_NO, "Duplicate ADD item_no.")
            new_line = {
                "project_id": project["id"],
                "item_no": edit["item_no"],
                "description": edit.get("description", ""),
                "scheduled_value_cents": edit["scheduled_value_delta_cents"],
                "retainage_pct": edit.get("retainage_pct", project["default_retainage_pct"]),
                "work_completed_to_date_cents": 0,
                "materials_stored_cents": 0,
                "retainage_withheld_to_date_cents": 0,
                "status": "ACTIVE",
            }
            db.stamp_create(new_line)
            db.sov_lines[new_line["id"]] = new_line
            working_items.add(edit["item_no"])
            active_by_item[edit["item_no"]] = new_line
        else:  # ADJUST
            line = active_by_item[edit["item_no"]]
            line["scheduled_value_cents"] += edit["scheduled_value_delta_cents"]
            if line["scheduled_value_cents"] <= 0:
                raise err(ERR_INVALID_REQUEST,
                          "ADJUST would drop scheduled_value_cents to <= 0.")
            db.touch(line)

    co["status"] = "APPROVED"
    co["approved_by_user_id"] = uid
    db.touch(co)

    # Cascade B->C: recompute revised contract sum; bump project version.
    services.recompute_revised_contract_sum(project)
    db.touch(project)
    return success(h.change_order_out(co))


@bp.post("/change-orders/<co_id>/reject")
def reject_change_order(co_id):
    _uid, role = authenticate()
    require_role(role, {"Owner"})
    co = _get_co_or_404(co_id)
    if co["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "ChangeOrder is not SUBMITTED.")
    co["status"] = "REJECTED"
    db.touch(co)
    return success(h.change_order_out(co))
