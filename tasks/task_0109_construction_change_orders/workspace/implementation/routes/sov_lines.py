"""Schedule-of-values line endpoints (PRD §3.1)."""
from flask import Blueprint, request

import db
import helpers as h
from errors import err, ERR_NOT_FOUND, ERR_DUPLICATE_ITEM_NO
from middleware import authenticate, require_role
from response import success

bp = Blueprint("sov_lines", __name__)


@bp.post("/sov-lines")
def create_sov_line():
    _uid, role = authenticate()
    require_role(role, {"Contractor"})
    body = h.get_json()
    h.require_fields(body, ["project_id", "item_no", "description", "scheduled_value_cents"])

    project_id = h.as_string(body["project_id"], "project_id")
    project = db.projects.get(project_id)
    if project is None:
        raise err(ERR_NOT_FOUND, "Project not found.")

    item_no = h.as_nonempty_string(body["item_no"], "item_no")
    description = h.as_string(body["description"], "description")
    scheduled = h.as_int(body["scheduled_value_cents"], "scheduled_value_cents", minimum=1)

    # item_no unique among ACTIVE lines of the project (ERR_DUPLICATE_ITEM_NO).
    for s in db.sov_lines.values():
        if (s["project_id"] == project_id and s["status"] == "ACTIVE"
                and s["item_no"] == item_no):
            raise err(ERR_DUPLICATE_ITEM_NO, "item_no already used by an ACTIVE line.")

    record = {
        "project_id": project_id,
        "item_no": item_no,
        "description": description,
        "scheduled_value_cents": scheduled,
        "retainage_pct": project["default_retainage_pct"],
        "work_completed_to_date_cents": 0,
        "materials_stored_cents": 0,
        "retainage_withheld_to_date_cents": 0,
        "status": "ACTIVE",
    }
    db.stamp_create(record)
    db.sov_lines[record["id"]] = record
    return success(h.sov_line_out(record), status=201)


@bp.get("/sov-lines/<sov_line_id>")
def get_sov_line(sov_line_id):
    _uid, role = authenticate()
    require_role(role, {"Owner", "Contractor", "Architect"})
    s = db.sov_lines.get(sov_line_id)
    if s is None:
        raise err(ERR_NOT_FOUND, "SovLine not found.")
    return success(h.sov_line_out(s))


@bp.get("/sov-lines")
def list_sov_lines():
    _uid, role = authenticate()
    require_role(role, {"Owner", "Contractor", "Architect"})
    limit, offset = h.parse_pagination()
    project_id = request.args.get("project_id")
    status = request.args.get("status")
    records = list(db.sov_lines.values())
    if project_id:
        records = [r for r in records if r["project_id"] == project_id]
    if status:
        records = [r for r in records if r["status"] == status]
    page, meta = h.paginate(records, limit, offset)
    return success([h.sov_line_out(r) for r in page], pagination=meta)
