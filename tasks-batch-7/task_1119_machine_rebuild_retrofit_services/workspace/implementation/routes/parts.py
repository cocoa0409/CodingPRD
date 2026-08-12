"""Part master and ProjectPartLine endpoints (PRD §3.4, stock law §2.9)."""

from flask import Blueprint, request

from db import bump, new_record, sorted_records, store
from errors import ApiError, ERR_INVALID_STATE, bad_request, not_found
from middleware import require_roles
from response import list_response, success
from serializers import serialize, serialize_list
from util import (
    get_body,
    opt_str,
    pagination_params,
    paginate,
    req_enum,
    req_int,
    req_str,
)
from routes.common import get_or_404

bp = Blueprint("parts", __name__)

OEM_STATUSES = ("ACTIVE", "OBSOLETE", "SUPERSEDED")


# ---------------------------------------------------------------------------
# Part catalog
# ---------------------------------------------------------------------------
@bp.post("/api/parts")
@require_roles("PlatformAdmin")
def create_part(user_id, role):
    body = get_body()
    part_number = req_str(body, "part_number")
    description = req_str(body, "description", non_empty=False)
    oem_status = req_enum(body, "oem_status", OEM_STATUSES)
    superseded_by_id = opt_str(body, "superseded_by_id")
    unit_cost_cents = req_int(body, "unit_cost_cents", minimum=1)
    stock_quantity = req_int(body, "stock_quantity", minimum=0)
    lead_time_days = req_int(body, "lead_time_days", minimum=0)
    for p in store.parts.values():
        if p["part_number"] == part_number:
            raise bad_request("part_number must be unique")
    if superseded_by_id is not None and superseded_by_id not in store.parts:
        raise not_found(f"part {superseded_by_id} does not exist")
    rec = new_record(
        {
            "part_number": part_number,
            "description": description,
            "oem_status": oem_status,
            "superseded_by_id": superseded_by_id,
            "unit_cost_cents": unit_cost_cents,
            "stock_quantity": stock_quantity,
            "available_quantity": stock_quantity,
            "reserved_quantity": 0,
            "lead_time_days": lead_time_days,
        }
    )
    store.parts[rec["id"]] = rec
    return success(serialize(rec), status=201)


@bp.get("/api/parts/<pid>")
@require_roles("PlatformAdmin", "ProjectManager", "LogisticsCoordinator", "RebuildEngineer")
def get_part(user_id, role, pid):
    rec = get_or_404(store.parts, pid, "part")
    return success(serialize(rec))


@bp.get("/api/parts")
@require_roles("PlatformAdmin", "ProjectManager", "LogisticsCoordinator", "RebuildEngineer")
def list_parts(user_id, role):
    limit, offset = pagination_params()
    items = sorted_records(store.parts)
    superseded_filter = request.args.get("superseded_by_id")
    if superseded_filter is not None:
        items = [p for p in items if p["superseded_by_id"] == superseded_filter]
    page, meta = paginate(items, limit, offset)
    return list_response(serialize_list(page), meta)


# ---------------------------------------------------------------------------
# Part lines
# ---------------------------------------------------------------------------
@bp.get("/api/part-lines/<lid>")
@require_roles("ProjectManager", "LogisticsCoordinator", "PlatformAdmin")
def get_part_line(user_id, role, lid):
    rec = get_or_404(store.part_lines, lid, "part line")
    return success(serialize(rec))


@bp.get("/api/part-lines")
@require_roles("ProjectManager", "LogisticsCoordinator", "PlatformAdmin")
def list_part_lines(user_id, role):
    limit, offset = pagination_params()
    items = sorted_records(store.part_lines)
    project_filter = request.args.get("project_id")
    part_filter = request.args.get("part_id")
    if project_filter is not None:
        items = [l for l in items if l["project_id"] == project_filter]
    if part_filter is not None:
        items = [l for l in items if l["part_id"] == part_filter]
    page, meta = paginate(items, limit, offset)
    return list_response(serialize_list(page), meta)


@bp.post("/api/part-lines/<lid>/fulfill")
@require_roles("LogisticsCoordinator")
def fulfill_part_line(user_id, role, lid):
    line = get_or_404(store.part_lines, lid, "part line")
    if line["status"] != "RESERVED":
        raise ApiError(
            ERR_INVALID_STATE,
            f"part line in status {line['status']} cannot be fulfilled",
            409,
        )
    part = store.parts[line["part_id"]]
    line["status"] = "FULFILLED"
    bump(line)
    # Conservation ledger: issuance decreases reserved and stock together.
    part["reserved_quantity"] -= line["quantity"]
    part["stock_quantity"] -= line["quantity"]
    part["available_quantity"] = part["stock_quantity"] - part["reserved_quantity"]
    bump(part)
    return success(serialize(line))


@bp.post("/api/part-lines/<lid>/cancel")
@require_roles("ProjectManager")
def cancel_part_line(user_id, role, lid):
    line = get_or_404(store.part_lines, lid, "part line")
    if line["status"] not in ("PENDING", "RESERVED"):
        raise ApiError(
            ERR_INVALID_STATE,
            f"part line in status {line['status']} cannot be cancelled",
            409,
        )
    project = store.projects[line["project_id"]]
    if line["status"] == "PENDING":
        allowed = project["work_status"] == "DECIDED"
    else:  # RESERVED
        allowed = project["work_status"] in ("DECIDED", "PARTS_SOURCING")
    if not allowed:
        raise ApiError(
            ERR_INVALID_STATE,
            f"line cancellation is not allowed while the project is {project['work_status']}",
            409,
        )
    was_reserved = line["status"] == "RESERVED"
    line["status"] = "CANCELLED"
    bump(line)
    if was_reserved:
        part = store.parts[line["part_id"]]
        part["reserved_quantity"] -= line["quantity"]
        part["available_quantity"] = part["stock_quantity"] - part["reserved_quantity"]
        bump(part)
    # Manual line cancellation raises quote_stale once a quote exists (§2.10).
    if project["quote_revision"] >= 1:
        project["quote_stale"] = True
        bump(project)
    return success(serialize(line))
