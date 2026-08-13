"""ActualCostEntry endpoints: append-only ledger (id + created_at only)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import raise_err, ERR_VALIDATION
from middleware import require_roles
from response import success_object, success_list
from services.serializers import cost_entry_view
from util import (
    get_json_body,
    get_or_404,
    parse_pagination,
    paginate,
    query_arg,
    require_enum,
    require_int,
    require_string,
    require_ts,
    sort_created,
)

bp = Blueprint("cost_entries", __name__, url_prefix="/api/actual-cost-entries")

PM = "ProgramManager"
FA = "FinanceAnalyst"

COST_CODES = {"JOINT_TRENCH", "EXCLUSIVE", "RESTORATION", "PROGRAM_OVERHEAD"}


@bp.route("", methods=["POST"])
@require_roles(FA)
def create_cost_entry(_user_id: str, _role: str):
    body = get_json_body()
    if body.get("project_id") is not None:
        get_or_404(db.projects, body["project_id"], "Project")
    if body.get("participation_id") is not None:
        get_or_404(db.participations, body["participation_id"], "UtilityParticipation")
    project_id = require_string(body, "project_id")
    cost_code = require_enum(body, "cost_code", COST_CODES)
    amount_cents = require_int(body, "amount_cents", minimum=1)
    incurred_on = require_ts(body, "incurred_on")
    participation_id = body.get("participation_id")
    if cost_code == "EXCLUSIVE":
        if participation_id is None:
            raise_err(ERR_VALIDATION,
                      "participation_id is required when cost_code is EXCLUSIVE")
    else:
        if participation_id is not None:
            raise_err(ERR_VALIDATION,
                      "participation_id is omitted unless cost_code is EXCLUSIVE")

    entry = {
        "id": db.new_id(),
        "created_at": db.wall_now_iso(),
        "_seq": db.next_seq(),
        "project_id": project_id,
        "participation_id": participation_id,
        "cost_code": cost_code,
        "amount_cents": amount_cents,
        "incurred_on": incurred_on,
        "submitted_by_user_id": _user_id,
    }
    db.cost_entries[entry["id"]] = entry
    return success_object(cost_entry_view(entry), 201)


@bp.route("", methods=["GET"])
@require_roles(PM, FA)
def list_cost_entries(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = list(db.cost_entries.values())
    project_id = query_arg("project_id")
    cost_code = query_arg("cost_code")
    participation_id = query_arg("participation_id")
    if project_id:
        items = [e for e in items if e["project_id"] == project_id]
    if cost_code:
        items = [e for e in items if e["cost_code"] == cost_code]
    if participation_id:
        items = [e for e in items if e.get("participation_id") == participation_id]
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([cost_entry_view(e) for e in page], limit, offset, total)


@bp.route("/<eid>", methods=["GET"])
@require_roles(PM, FA)
def get_cost_entry(eid: str, _user_id: str, _role: str):
    return success_object(cost_entry_view(get_or_404(db.cost_entries, eid,
                                                     "ActualCostEntry")))
