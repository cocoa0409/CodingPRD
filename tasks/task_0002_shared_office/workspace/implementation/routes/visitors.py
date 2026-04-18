"""Visitor routes."""
from datetime import timedelta

from flask import Blueprint

from clock import get_now, parse_iso, format_iso
from common import get_json_body, check_version
from db import db, new_id
from errors import api_error
from middleware import require_roles
from response import success

bp = Blueprint("visitors", __name__)


@bp.route("/visitors", methods=["POST"])
def create_visitor():
    user_id, role = require_roles(["TenantMember", "TenantAdmin"])
    body = get_json_body()

    host_member_id = body.get("host_member_id")
    visitor_name = body.get("visitor_name")
    exp_arr = body.get("expected_arrival_at")
    exp_dep = body.get("expected_departure_at")

    # FK existence
    host = db.members.get(host_member_id) if host_member_id else None
    if not host:
        raise api_error("ERR_REFERENCED_ENTITY_MISSING", "host_member not found")

    if not visitor_name:
        raise api_error("ERR_INVALID_VISITOR_WINDOW", "visitor_name required")

    # Caller ownership
    caller = db.members.get(user_id)
    if not caller:
        raise api_error("ERR_FORBIDDEN", "caller not found")
    if role == "TenantMember" and host_member_id != user_id:
        raise api_error("ERR_FORBIDDEN", "TenantMember must host self")
    if role == "TenantAdmin" and caller["tenant_id"] != host["tenant_id"]:
        raise api_error("ERR_FORBIDDEN", "TenantAdmin may only act on own tenant")

    # Host tenant_id derives to visitor tenant_id
    tenant_id = host["tenant_id"]

    # Window validation
    if not exp_arr or not exp_dep:
        raise api_error("ERR_INVALID_VISITOR_WINDOW", "arrival/departure required")
    try:
        arr_dt = parse_iso(exp_arr)
        dep_dt = parse_iso(exp_dep)
    except Exception:
        raise api_error("ERR_INVALID_VISITOR_WINDOW", "invalid timestamps")
    if arr_dt >= dep_dt:
        raise api_error("ERR_INVALID_VISITOR_WINDOW", "arrival must be before departure")
    if (dep_dt - arr_dt) > timedelta(hours=24):
        raise api_error("ERR_INVALID_VISITOR_WINDOW", "span exceeds 24 hours")

    visitor = {
        "id": new_id(),
        "host_member_id": host_member_id,
        "tenant_id": tenant_id,
        "visitor_name": visitor_name,
        "expected_arrival_at": exp_arr,
        "expected_departure_at": exp_dep,
        "actual_arrival_at": None,
        "actual_departure_at": None,
        "status": "REGISTERED",
        "overstay_fee_cents": 0,
        "bill_id": None,
        "created_at": format_iso(get_now()),
    }
    db.visitors[visitor["id"]] = visitor
    return success(visitor, status=201)


@bp.route("/visitors/<visitor_id>", methods=["GET"])
def get_visitor(visitor_id):
    require_roles(["PlatformAdmin", "TenantAdmin", "TenantMember", "Receptionist"])
    v = db.visitors.get(visitor_id)
    if not v:
        raise api_error("ERR_NOT_FOUND", "visitor not found")
    return success(v)


@bp.route("/visitors/<visitor_id>/revoke", methods=["POST"])
def revoke_visitor(visitor_id):
    user_id, role = require_roles(["TenantMember", "TenantAdmin"])
    v = db.visitors.get(visitor_id)
    if not v:
        raise api_error("ERR_NOT_FOUND", "visitor not found")
    body = get_json_body()
    # Visitor has no version — skip check_version (visitors lack version field)

    caller = db.members.get(user_id)
    if not caller:
        raise api_error("ERR_FORBIDDEN", "caller not found")
    if role == "TenantMember" and v["host_member_id"] != user_id:
        raise api_error("ERR_FORBIDDEN", "not the host")
    if role == "TenantAdmin" and caller["tenant_id"] != v["tenant_id"]:
        raise api_error("ERR_FORBIDDEN", "tenant mismatch")

    if v["status"] != "REGISTERED":
        raise api_error("ERR_INVALID_VISITOR_STATE", "visitor not REGISTERED")
    v["status"] = "REVOKED"
    return success(v)
