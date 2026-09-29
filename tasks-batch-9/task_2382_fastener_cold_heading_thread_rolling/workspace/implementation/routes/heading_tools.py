"""Heading tool sets (PRD 3.3)."""

from flask import Blueprint, g

from db import db, new_record, touch
from errors import ApiError
from middleware import ANY_ROLE, endpoint
from response import created, ok
from services import calc
from services.cascades import cascade_tool_worn
from services.lookup import heading_tool_or_404, require_unique
from validate import field_int, field_str

bp = Blueprint("heading_tools", __name__)

CREATE_ROLES = ("ProcessEngineer", "PlantAdmin")


@bp.post("/heading-tools")
@endpoint(CREATE_ROLES)
def create_heading_tool():
    body = g.body
    tool_code = field_str(body, "tool_code")
    station_count = field_int(body, "station_count", minimum=1)
    rated_life_pieces = field_int(body, "rated_life_pieces", minimum=1)
    max_regrinds = field_int(body, "max_regrinds", required=False, default=None, minimum=0)
    if max_regrinds is None:
        max_regrinds = 3

    require_unique("heading_tools", "tool_code", tool_code)

    tool = new_record(
        {
            "tool_code": tool_code,
            "station_count": station_count,
            "rated_life_pieces": rated_life_pieces,
            "max_regrinds": max_regrinds,
            "regrind_count": 0,
            "cumulative_pieces_current_cycle": 0,
            "cycle_pieces_history": [],
            "completed_cycle_count": 0,
            "lifetime_pieces": 0,
            "observed_avg_cycle_pieces": None,
            "rated_derated_life_pieces": 0,
            "conservative_life_pieces": 0,
            "status": "AVAILABLE",
            "mounted_press_code": None,
            "condemn_reason": None,
        }
    )
    calc.refresh_tool_life(tool)
    db.heading_tools[tool["id"]] = tool
    return created(tool)


@bp.get("/heading-tools/<tool_id>")
@endpoint(ANY_ROLE)
def get_heading_tool(tool_id):
    return ok(heading_tool_or_404(tool_id))


@bp.post("/heading-tools/<tool_id>/mount")
@endpoint("ProcessEngineer")
def mount_tool(tool_id):
    press_code = field_str(g.body, "press_code")
    tool = heading_tool_or_404(tool_id)
    if tool["status"] != "AVAILABLE":
        raise ApiError("ERR_INVALID_TOOL_STATE")
    tool["status"] = "MOUNTED"
    tool["mounted_press_code"] = press_code
    touch(tool)
    return ok(tool)


@bp.post("/heading-tools/<tool_id>/condemn")
@endpoint("ProcessEngineer", "QualityInspector")
def condemn_tool(tool_id):
    reason = field_str(g.body, "reason", allow_empty=True)
    tool = heading_tool_or_404(tool_id)
    if tool["status"] != "MOUNTED":
        raise ApiError("ERR_INVALID_TOOL_STATE")
    tool["status"] = "WORN"
    tool["condemn_reason"] = reason
    tool["mounted_press_code"] = None
    touch(tool)
    cascade_tool_worn(tool)
    return ok(tool)


@bp.post("/heading-tools/<tool_id>/regrind")
@endpoint("ProcessEngineer")
def regrind_tool(tool_id):
    tool = heading_tool_or_404(tool_id)
    if tool["status"] != "WORN":
        raise ApiError("ERR_INVALID_TOOL_STATE")

    open_cycle = int(tool["cumulative_pieces_current_cycle"] or 0)
    if int(tool["regrind_count"]) < int(tool["max_regrinds"]):
        tool["cycle_pieces_history"] = list(tool["cycle_pieces_history"]) + [open_cycle]
        tool["completed_cycle_count"] = int(tool["completed_cycle_count"]) + 1
        tool["regrind_count"] = int(tool["regrind_count"]) + 1
        tool["cumulative_pieces_current_cycle"] = 0
        tool["status"] = "AVAILABLE"
        tool["condemn_reason"] = None
        calc.refresh_tool_life(tool)
    else:
        tool["cycle_pieces_history"] = list(tool["cycle_pieces_history"]) + [open_cycle]
        tool["completed_cycle_count"] = int(tool["completed_cycle_count"]) + 1
        tool["status"] = "SCRAPPED"
    touch(tool)
    return ok(tool)
