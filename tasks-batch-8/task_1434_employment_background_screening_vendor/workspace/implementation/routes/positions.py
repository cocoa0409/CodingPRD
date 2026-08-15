"""Position endpoints."""
from flask import Blueprint, request

import db
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_PACKAGE_NOT_ACTIVE, ERR_RULE_NOT_ACTIVE,
    ERR_CREDIT_PROHIBITED,
)
from middleware import (
    auth, require_role, get_body, req_str, req_enum, req_int,
    parse_pagination, sort_key, ALL_ROLES,
)
from response import success_object, success_list
from services import active_rule_for

bp = Blueprint("positions", __name__)

RISK_TIERS = ("TIER_1_STANDARD", "TIER_2_ELEVATED", "TIER_3_HIGH_RISK")


@bp.route("/positions", methods=["POST"])
def create_position():
    auth_uid, role = auth()
    require_role(role, {"HRAdmin"})
    body = get_body()
    # existence (priority 3): body package_id must resolve
    raw_pkg = body.get("package_id")
    if raw_pkg is not None and raw_pkg not in db.packages:
        raise ApiError(ERR_NOT_FOUND, 404, "Package not found")
    # shape (3.8)
    title = req_str(body, "title")
    department = req_str(body, "department")
    risk_tier = req_enum(body, "risk_tier", RISK_TIERS)
    package_id = req_str(body, "package_id")
    jurisdiction_code = req_str(body, "jurisdiction_code")
    salary = req_int(body, "annual_salary_cents", minimum=0)
    # referential (8.1): package ACTIVE, then ACTIVE rule for the code
    pkg = db.packages[package_id]
    if pkg["status"] != "ACTIVE":
        raise ApiError(ERR_PACKAGE_NOT_ACTIVE, 409,
                       "Package must be ACTIVE at position creation")
    rule = active_rule_for(jurisdiction_code)
    if rule is None:
        raise ApiError(ERR_RULE_NOT_ACTIVE, 409,
                       "No ACTIVE jurisdiction rule for jurisdiction_code")
    # business safety (5.3): credit-check prohibition
    if (not rule["credit_check_allowed"]
            and "CREDIT_CHECK" in pkg["check_types"]):
        raise ApiError(ERR_CREDIT_PROHIBITED, 422,
                       "Package contains CREDIT_CHECK but jurisdiction forbids it")
    position = db.new_entity({
        "title": title,
        "department": department,
        "risk_tier": risk_tier,
        "package_id": package_id,
        "jurisdiction_code": jurisdiction_code,
        "annual_salary_cents": salary,
    })
    db.positions[position["id"]] = position
    return success_object(position, 201)


@bp.route("/positions", methods=["GET"])
def list_positions():
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    rows = list(db.positions.values())
    package_id = request.args.get("package_id")
    if package_id is not None:
        rows = [p for p in rows if p["package_id"] == package_id]
    rows.sort(key=sort_key)
    total = len(rows)
    return success_list(rows[offset:offset + limit], limit, offset, total)


@bp.route("/positions/<position_id>", methods=["GET"])
def get_position(position_id):
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    position = db.positions.get(position_id)
    if position is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Position not found")
    return success_object(position, 200)
