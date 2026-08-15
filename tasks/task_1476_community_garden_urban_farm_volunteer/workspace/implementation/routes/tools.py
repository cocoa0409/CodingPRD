"""Tool pools: registration, restore from maintenance, retirement (PRD 3.7)."""
from flask import Blueprint, request

import db
import services
from app_util import body
from errors import err, err_invalid_request, err_not_found, err_state
from middleware import ALL_ROLES, require_auth, require_role
from response import ok
from util import pagination_args, req_enum, req_int, req_str

bp = Blueprint("tools", __name__)

CATEGORIES = {"HAND", "POWER", "IRRIGATION", "SAFETY", "OTHER"}
STAFF = ["GardenAdmin", "Coordinator"]


@bp.post("/api/tools")
def create_tool():
    ctx = require_auth()
    require_role(ctx, STAFF)
    data = body()
    name = req_str(data, "tool_name")
    category = req_enum(data, "category", CATEGORIES)
    total = req_int(data, "total_count")
    if total <= 0:
        raise err_invalid_request("total_count must be > 0")
    rec = services.create_record({
        "tool_name": name,
        "category": category,
        "total_count": total,
        "in_maintenance_count": 0,
        "written_off_count": 0,
        "status": "IN_SERVICE",
    })
    db.tools[rec["id"]] = rec
    return ok(services.tool_view(rec), status=201)


@bp.get("/api/tools")
def list_tools():
    ctx = require_auth()
    require_role(ctx, ALL_ROLES)
    limit, offset = pagination_args(request.args)
    items = services.list_view(db.tools.values(),
                               {"category": "category", "status": "status"},
                               request.args, services.tool_view)
    total = len(items)
    return ok([services.tool_view(t) for t in items[offset:offset + limit]],
              pagination=(limit, offset, total))


def _get_tool(tool_id):
    tool = db.tools.get(tool_id)
    if tool is None:
        raise err_not_found("tool")
    return tool


@bp.get("/api/tools/<toolId>")
def get_tool(toolId):
    ctx = require_auth()
    require_role(ctx, ALL_ROLES)
    return ok(services.tool_view(_get_tool(toolId)))


@bp.post("/api/tools/<toolId>/restore")
def restore_tool(toolId):
    ctx = require_auth()
    require_role(ctx, STAFF)
    tool = _get_tool(toolId)
    data = body()
    qty = req_int(data, "qty")
    if qty <= 0 or qty > tool["in_maintenance_count"]:
        raise err("ERR_QUANTITY_INVALID", "restore qty must be > 0 and <= in_maintenance_count")
    tool["in_maintenance_count"] -= qty
    services.bump(tool)
    return ok(services.tool_view(tool))


@bp.post("/api/tools/<toolId>/retire")
def retire_tool(toolId):
    ctx = require_auth()
    require_role(ctx, ["GardenAdmin"])
    tool = _get_tool(toolId)
    if tool["status"] != "IN_SERVICE":
        raise err_state("TOOL")
    if services.tool_checked_out_count(tool["id"]) != 0:
        raise err("ERR_TOOL_UNITS_OUTSTANDING", "tool has checked-out units")
    tool["status"] = "RETIRED"
    services.bump(tool)
    return ok(services.tool_view(tool))
