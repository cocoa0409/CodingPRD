from datetime import timedelta

from flask import Blueprint, request, g

from errors import (
    raise_error, ERR_NOT_FOUND, ERR_REFERENCED_ENTITY_MISSING, ERR_TENANT_MISMATCH,
    ERR_INVALID_VISITOR_WINDOW, ERR_INVALID_VISITOR_STATE, ERR_FORBIDDEN,
)
from response import success
from middleware import require_roles
from util import parse_iso, now_iso_string
from db import db

bp = Blueprint("visitors", __name__)


def visitor_view(v: dict) -> dict:
    return {
        "id": v["id"],
        "created_at": v["created_at"],
        "tenant_id": v["tenant_id"],
        "host_member_id": v["host_member_id"],
        "visitor_name": v["visitor_name"],
        "expected_arrival_at": v["expected_arrival_at"],
        "expected_departure_at": v["expected_departure_at"],
        "status": v["status"],
        "actual_arrival_at": v.get("actual_arrival_at"),
        "actual_departure_at": v.get("actual_departure_at"),
        "overstay_fee_cents": v.get("overstay_fee_cents"),
        "bill_id": v.get("bill_id"),
    }


@bp.route("/visitors", methods=["POST"])
def register_visitor():
    require_roles("TenantMember", "TenantAdmin")
    body = request.get_json(silent=True) or {}
    host_member_id = body.get("host_member_id")
    visitor_name = body.get("visitor_name")
    expected_arrival_at = body.get("expected_arrival_at")
    expected_departure_at = body.get("expected_departure_at")
    # tenant_id may be provided or inferred from host
    tenant_id = body.get("tenant_id")

    if not host_member_id or not visitor_name or not expected_arrival_at or not expected_departure_at:
        raise_error(("ERR_INVALID_INPUT", 422), "Missing fields")

    host = db.members.get(host_member_id)
    if not host:
        raise_error(ERR_REFERENCED_ENTITY_MISSING, "Host member not found")

    # Derive/validate tenant_id
    if tenant_id is None:
        tenant_id = host["tenant_id"]
    else:
        if host["tenant_id"] != tenant_id:
            raise_error(ERR_TENANT_MISMATCH, "Host does not belong to tenant")

    actor = g.acting_member
    if not actor or actor["tenant_id"] != tenant_id:
        raise_error(ERR_FORBIDDEN, "Cannot register visitor for another tenant")

    arrival = parse_iso(expected_arrival_at)
    departure = parse_iso(expected_departure_at)
    if arrival is None or departure is None:
        raise_error(ERR_INVALID_VISITOR_WINDOW, "Invalid visitor window")
    if arrival >= departure:
        raise_error(ERR_INVALID_VISITOR_WINDOW, "arrival must be before departure")
    if (departure - arrival) > timedelta(hours=24):
        raise_error(ERR_INVALID_VISITOR_WINDOW, "Visit exceeds 24 hours")

    v = {
        "tenant_id": tenant_id,
        "host_member_id": host_member_id,
        "visitor_name": visitor_name,
        "expected_arrival_at": now_iso_string(arrival),
        "expected_departure_at": now_iso_string(departure),
        "status": "REGISTERED",
        "actual_arrival_at": None,
        "actual_departure_at": None,
        "overstay_fee_cents": None,
        "bill_id": None,
    }
    v["id"] = db.new_id()
    v["created_at"] = now_iso_string(db.now())
    db.visitors[v["id"]] = v
    return success(visitor_view(v), 201)


@bp.route("/visitors/<visitor_id>/revoke", methods=["POST"])
def revoke_visitor(visitor_id):
    require_roles("TenantMember", "TenantAdmin")
    v = db.visitors.get(visitor_id)
    if not v:
        raise_error(ERR_NOT_FOUND, "Visitor not found")
    actor = g.acting_member
    if not actor or actor["tenant_id"] != v["tenant_id"]:
        raise_error(ERR_FORBIDDEN, "Cannot act on another tenant's visitor")
    if g.user_role == "TenantMember" and actor["id"] != v["host_member_id"]:
        raise_error(ERR_FORBIDDEN, "Only host member may revoke")
    if v["status"] != "REGISTERED":
        raise_error(ERR_INVALID_VISITOR_STATE, "Visitor is not REGISTERED")
    v["status"] = "REVOKED"
    return success(visitor_view(v))


@bp.route("/visitors/<visitor_id>", methods=["GET"])
def get_visitor(visitor_id):
    require_roles("PlatformAdmin", "TenantAdmin", "TenantMember", "Receptionist")
    v = db.visitors.get(visitor_id)
    if not v:
        raise_error(ERR_NOT_FOUND, "Visitor not found")
    if g.user_role in ("TenantAdmin", "TenantMember"):
        actor = g.acting_member
        if not actor or actor["tenant_id"] != v["tenant_id"]:
            raise_error(ERR_FORBIDDEN, "Visitor not accessible")
    return success(visitor_view(v))
