"""Tool endpoints (PRD §3.3)."""

from flask import request

from db import STORE, new_record, bump
from errors import ApiError
from middleware import endpoint, ANY_ROLE
from response import ok_object, list_response
from serializers import ser_tool
from services import get_tool, valid_cert_at_grade
from util import (
    GRADES,
    PROTO_SHOT_LIMIT,
    as_enum,
    as_positive_decimal,
    as_positive_int,
    as_string,
    body_dict,
    req_present,
)

from routes import bp

TOOL_TYPES = {"FORM_MOLD", "TRIM_FIXTURE", "MATCHED_SET"}


@bp.route("/tools", methods=["POST"])
@endpoint({"ToolingEngineer"})
def create_tool(user_id, role):
    body = body_dict(request.get_json(silent=True))
    tool_code = as_string(req_present(body, "tool_code"), "tool_code")
    part_number = as_string(req_present(body, "part_number"), "part_number")
    tool_type = as_enum(req_present(body, "tool_type"), "tool_type", TOOL_TYPES)
    min_gauge = as_positive_decimal(req_present(body, "min_gauge_mm"), "min_gauge_mm")
    max_gauge = as_positive_decimal(req_present(body, "max_gauge_mm"), "max_gauge_mm")
    if max_gauge < min_gauge:
        raise ApiError("ERR_INVALID_REQUEST", "max_gauge_mm must be >= min_gauge_mm")
    grade = as_enum(req_present(body, "cleanliness_grade"), "cleanliness_grade", GRADES)
    proto_cost = as_positive_decimal(req_present(body, "prototype_cost"), "prototype_cost")

    rec = new_record()
    rec.update({
        "tool_code": tool_code,
        "part_number": part_number,
        "tool_type": tool_type,
        "min_gauge_mm": min_gauge,
        "max_gauge_mm": max_gauge,
        "cleanliness_grade": grade,
        "prototype_cost": proto_cost,
        "production_cost": None,
        "rated_lifetime_shots": None,
        "shots_used": 0,
        "drawing_revision": 1,
        "qualified_drawing_revision": None,
        "proto_shot_limit": None,  # materialized at complete-prototype
        "status": "DRAFT",
    })
    STORE["tools"][rec["id"]] = rec
    return ok_object(ser_tool(rec), 201)


@bp.route("/tools", methods=["GET"])
@endpoint(ANY_ROLE)
def list_tools(user_id, role):
    items = list(STORE["tools"].values())
    status = request.args.get("status")
    if status is not None:
        items = [t for t in items if t["status"] == status]
    return list_response(items, ser_tool)


@bp.route("/tools/<toolId>", methods=["GET"])
@endpoint(ANY_ROLE)
def get_one_tool(user_id, role, toolId):
    return ok_object(ser_tool(get_tool(toolId)))


@bp.route("/tools/<toolId>/complete-prototype", methods=["POST"])
@endpoint({"ToolingEngineer"})
def complete_prototype(user_id, role, toolId):
    tool = get_tool(toolId)
    if tool["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_TOOL_TRANSITION", "complete-prototype requires status DRAFT")
    tool["status"] = "PROTOTYPE"
    tool["proto_shot_limit"] = PROTO_SHOT_LIMIT
    bump(tool)
    return ok_object(ser_tool(tool))


@bp.route("/tools/<toolId>/submit-qualification", methods=["POST"])
@endpoint({"ToolingEngineer"})
def submit_qualification(user_id, role, toolId):
    tool = get_tool(toolId)
    if tool["status"] not in ("PROTOTYPE", "UNDER_REVISION"):
        raise ApiError(
            "ERR_INVALID_TOOL_TRANSITION",
            "submit-qualification requires status PROTOTYPE or UNDER_REVISION",
        )
    tool["status"] = "QUALIFICATION"
    bump(tool)
    return ok_object(ser_tool(tool))


@bp.route("/tools/<toolId>/approve-production", methods=["POST"])
@endpoint({"ToolingEngineer"})
def approve_production(user_id, role, toolId):
    body = body_dict(request.get_json(silent=True))
    production_cost = as_positive_decimal(req_present(body, "production_cost"), "production_cost")
    rated_shots = as_positive_int(req_present(body, "rated_lifetime_shots"), "rated_lifetime_shots")

    tool = get_tool(toolId)
    if tool["status"] != "QUALIFICATION":
        raise ApiError("ERR_INVALID_TOOL_TRANSITION", "approve-production requires status QUALIFICATION")
    # Certificate gate: currently valid TOOL cert at grade >= tool.cleanliness_grade
    if not valid_cert_at_grade("TOOL", tool["id"], tool["cleanliness_grade"]):
        raise ApiError(
            "ERR_CERTIFICATE_INVALID",
            "No currently valid cleanliness certificate at the tool's grade",
        )
    tool["production_cost"] = production_cost
    tool["rated_lifetime_shots"] = rated_shots
    tool["qualified_drawing_revision"] = tool["drawing_revision"]  # version pin at approval
    tool["status"] = "PRODUCTION"
    bump(tool)
    return ok_object(ser_tool(tool))


@bp.route("/tools/<toolId>/revise", methods=["POST"])
@endpoint({"ToolingEngineer"})
def revise_tool(user_id, role, toolId):
    tool = get_tool(toolId)
    if tool["status"] != "PRODUCTION":
        raise ApiError("ERR_INVALID_TOOL_TRANSITION", "revise requires status PRODUCTION")
    tool["status"] = "UNDER_REVISION"
    tool["drawing_revision"] += 1
    bump(tool)
    # Cascade hop 1: orders on this tool in STAGED or RUNNING -> ON_HOLD
    held = [
        o for o in STORE["production_orders"].values()
        if o["tool_id"] == tool["id"] and o["schedule_status"] in ("STAGED", "RUNNING")
    ]
    for order in held:
        order["schedule_status"] = "ON_HOLD"
        bump(order)
        # Cascade hop 2: each held order's RESERVED allocations -> REVIEW
        for alloc in STORE["material_allocations"].values():
            if alloc["production_order_id"] == order["id"] and alloc["status"] == "RESERVED":
                alloc["status"] = "REVIEW"
                bump(alloc)
    return ok_object(ser_tool(tool))
