"""Reservation routes."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from clock import get_now, parse_iso
from common import stamp_new, stamp_update, get_json_body, check_version, paginate
from db import db
from errors import api_error
from middleware import require_roles
from response import success
from services.pricing import provisional_fee

bp = Blueprint("reservations", __name__)


GRANULARITY_BY_KIND = {
    "WORKSTATION": 60 * 60,     # 1 hour in seconds
    "MEETING_ROOM": 30 * 60,    # 0.5 hour
    "EVENT_AREA": 4 * 60 * 60,  # 4 hours
}


def _overlaps(r1_start, r1_end, r2_start, r2_end) -> bool:
    """Half-open intervals [start, end) overlap iff start1 < end2 AND start2 < end1."""
    return r1_start < r2_end and r2_start < r1_end


@bp.route("/reservations", methods=["POST"])
def create_reservation():
    user_id, role = require_roles(["TenantMember", "TenantAdmin"])
    body = get_json_body()
    tenant_id = body.get("tenant_id")
    member_id = body.get("member_id")
    resource_id = body.get("resource_id")
    start_at_s = body.get("start_at")
    end_at_s = body.get("end_at")

    # Existence checks (body-level FKs)
    if not tenant_id or tenant_id not in db.tenants:
        raise api_error("ERR_REFERENCED_ENTITY_MISSING", "tenant not found")
    member = db.members.get(member_id) if member_id else None
    if not member:
        raise api_error("ERR_REFERENCED_ENTITY_MISSING", "member not found")
    resource = db.resources.get(resource_id) if resource_id else None
    if not resource:
        raise api_error("ERR_REFERENCED_ENTITY_MISSING", "resource not found")

    # Ownership for TenantMember: must reserve for self (PRD §3.3 RBAC scoping)
    caller = db.members.get(user_id)
    if not caller:
        raise api_error("ERR_FORBIDDEN", "caller member not found")
    if role == "TenantMember":
        if member_id != user_id:
            raise api_error("ERR_FORBIDDEN", "TenantMember may only reserve for self")

    # Cross-tenant referential check (PRD §3.3 first-evaluated rule)
    if member["tenant_id"] != tenant_id:
        raise api_error("ERR_TENANT_MISMATCH", "member does not belong to tenant")

    # TenantAdmin ownership: must act on own tenant (after cross-tenant referential)
    if role == "TenantAdmin" and caller["tenant_id"] != tenant_id:
        raise api_error("ERR_FORBIDDEN", "TenantAdmin can only act on own tenant")

    # Temporal validation
    if not start_at_s or not end_at_s:
        raise api_error("ERR_INVALID_TIME_WINDOW", "start_at and end_at required")
    try:
        start_at = parse_iso(start_at_s)
        end_at = parse_iso(end_at_s)
    except Exception:
        raise api_error("ERR_INVALID_TIME_WINDOW", "invalid timestamp")
    if start_at >= end_at:
        raise api_error("ERR_INVALID_TIME_WINDOW", "start_at must be < end_at")
    # integer-minute boundary
    if start_at.second != 0 or start_at.microsecond != 0:
        raise api_error("ERR_INVALID_TIME_WINDOW", "start_at must be on integer-minute boundary")
    if end_at.second != 0 or end_at.microsecond != 0:
        raise api_error("ERR_INVALID_TIME_WINDOW", "end_at must be on integer-minute boundary")
    now = get_now()
    lower = now - timedelta(hours=1)
    upper = now + timedelta(days=180)
    if start_at < lower or start_at > upper or end_at < lower or end_at > upper:
        raise api_error("ERR_INVALID_TIME_WINDOW", "timestamps outside allowed horizon")

    # Granularity
    gran = GRANULARITY_BY_KIND.get(resource["kind"])
    duration = int((end_at - start_at).total_seconds())
    if gran is None or duration % gran != 0:
        raise api_error("ERR_RESERVATION_GRANULARITY", "duration does not match resource kind granularity")

    # Capacity
    headcount = body.get("headcount", 1)
    if resource["capacity"] < headcount:
        raise api_error("ERR_CAPACITY_EXCEEDED", "requested headcount exceeds capacity")

    # Overlap guard
    for r in db.reservations.values():
        if r["resource_id"] == resource_id and r["status"] in ("PENDING", "CONFIRMED", "IN_USE"):
            r_start = parse_iso(r["start_at"])
            r_end = parse_iso(r["end_at"])
            if _overlaps(start_at, end_at, r_start, r_end):
                raise api_error("ERR_RESERVATION_CONFLICT", "overlapping reservation on same resource")

    reservation = {
        "tenant_id": tenant_id,
        "member_id": member_id,
        "resource_id": resource_id,
        "start_at": start_at_s,
        "end_at": end_at_s,
        "status": "PENDING",
        "provisional_fee_cents": 0,
        "final_fee_cents": 0,
        "actual_start_at": None,
        "actual_end_at": None,
        "bill_id": None,
    }
    stamp_new(reservation)
    db.reservations[reservation["id"]] = reservation
    return success(reservation, status=201)


@bp.route("/reservations/<reservation_id>", methods=["GET"])
def get_reservation(reservation_id):
    require_roles(["PlatformAdmin", "TenantAdmin", "TenantMember"])
    r = db.reservations.get(reservation_id)
    if not r:
        raise api_error("ERR_NOT_FOUND", "reservation not found")
    return success(r)


@bp.route("/reservations", methods=["GET"])
def list_reservations():
    require_roles(["PlatformAdmin", "TenantAdmin", "TenantMember", "BillingOfficer"])
    items = list(db.reservations.values())
    tenant_id = request.args.get("tenant_id")
    resource_id = request.args.get("resource_id")
    status = request.args.get("status")
    start_after = request.args.get("start_after")
    start_before = request.args.get("start_before")
    if tenant_id:
        items = [r for r in items if r["tenant_id"] == tenant_id]
    if resource_id:
        items = [r for r in items if r["resource_id"] == resource_id]
    if status:
        items = [r for r in items if r["status"] == status]
    if start_after:
        try:
            sa = parse_iso(start_after)
            items = [r for r in items if parse_iso(r["start_at"]) >= sa]
        except Exception:
            pass
    if start_before:
        try:
            sb = parse_iso(start_before)
            items = [r for r in items if parse_iso(r["start_at"]) < sb]
        except Exception:
            pass
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)


@bp.route("/reservations/<reservation_id>/confirm", methods=["POST"])
def confirm_reservation(reservation_id):
    user_id, role = require_roles(["TenantMember", "TenantAdmin"])
    r = db.reservations.get(reservation_id)
    if not r:
        raise api_error("ERR_NOT_FOUND", "reservation not found")
    body = get_json_body()
    check_version(r, body)

    # ownership
    caller = db.members.get(user_id)
    if not caller:
        raise api_error("ERR_FORBIDDEN", "caller not found")
    if role == "TenantMember" and r["member_id"] != user_id:
        raise api_error("ERR_FORBIDDEN", "not owner of reservation")
    if role == "TenantAdmin" and caller["tenant_id"] != r["tenant_id"]:
        raise api_error("ERR_FORBIDDEN", "tenant mismatch")

    if r["status"] != "PENDING":
        raise api_error("ERR_INVALID_RESERVATION_STATE", "reservation not in PENDING")

    tenant = db.tenants.get(r["tenant_id"])
    if tenant and tenant.get("access_posture") != "OPEN":
        raise api_error("ERR_ACCESS_POSTURE_DENIES", "tenant access_posture denies confirmation")

    resource = db.resources.get(r["resource_id"])
    if not resource or resource["status"] != "AVAILABLE":
        raise api_error("ERR_INVALID_RESERVATION_STATE", "resource not available")

    member = db.members.get(r["member_id"])
    if not member or member["status"] != "ACTIVE":
        raise api_error("ERR_INVALID_RESERVATION_STATE", "member not active")

    # overlap guard (with CONFIRMED/IN_USE)
    start_at = parse_iso(r["start_at"])
    end_at = parse_iso(r["end_at"])
    for other in db.reservations.values():
        if other["id"] == r["id"]:
            continue
        if other["resource_id"] == r["resource_id"] and other["status"] in ("CONFIRMED", "IN_USE"):
            o_s = parse_iso(other["start_at"])
            o_e = parse_iso(other["end_at"])
            if _overlaps(start_at, end_at, o_s, o_e):
                raise api_error("ERR_RESERVATION_CONFLICT", "conflicts with existing reservation")

    r["status"] = "CONFIRMED"
    r["provisional_fee_cents"] = provisional_fee(r)
    stamp_update(r)
    return success(r)


@bp.route("/reservations/<reservation_id>/cancel", methods=["POST"])
def cancel_reservation(reservation_id):
    user_id, role = require_roles(["TenantMember", "TenantAdmin"])
    r = db.reservations.get(reservation_id)
    if not r:
        raise api_error("ERR_NOT_FOUND", "reservation not found")
    body = get_json_body()
    check_version(r, body)

    caller = db.members.get(user_id)
    if not caller:
        raise api_error("ERR_FORBIDDEN", "caller not found")
    if role == "TenantMember" and r["member_id"] != user_id:
        raise api_error("ERR_FORBIDDEN", "not owner of reservation")
    if role == "TenantAdmin" and caller["tenant_id"] != r["tenant_id"]:
        raise api_error("ERR_FORBIDDEN", "tenant mismatch")

    if r["status"] == "PENDING":
        r["status"] = "CANCELLED"
        stamp_update(r)
        return success(r)
    if r["status"] == "CONFIRMED":
        now = get_now()
        start_at = parse_iso(r["start_at"])
        if now >= start_at:
            raise api_error("ERR_INVALID_RESERVATION_STATE", "cannot cancel after start_at")
        r["status"] = "CANCELLED"
        r["provisional_fee_cents"] = 0
        stamp_update(r)
        return success(r)
    raise api_error("ERR_INVALID_RESERVATION_STATE", "reservation not cancellable in current state")
