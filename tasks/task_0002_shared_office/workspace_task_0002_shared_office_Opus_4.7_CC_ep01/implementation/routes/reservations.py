from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request, g

from errors import (
    raise_error, ERR_NOT_FOUND, ERR_REFERENCED_ENTITY_MISSING, ERR_TENANT_MISMATCH,
    ERR_INVALID_TIME_WINDOW, ERR_RESERVATION_GRANULARITY, ERR_CAPACITY_EXCEEDED,
    ERR_RESERVATION_CONFLICT, ERR_INVALID_RESERVATION_STATE, ERR_ACCESS_POSTURE_DENIES,
    ERR_FORBIDDEN,
)
from response import success
from middleware import require_roles
from util import (
    parse_iso, now_iso_string, add_common_fields, bump, check_version,
    is_minute_aligned, fractional_hours,
)
from util_pagination import parse_pagination, paginate
from db import db
from services.pricing import compute_provisional_fee
from services.tenant_service import refresh_tenant

bp = Blueprint("reservations", __name__)


def reservation_view(r: dict) -> dict:
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "tenant_id": r["tenant_id"],
        "member_id": r["member_id"],
        "resource_id": r["resource_id"],
        "start_at": r["start_at"],
        "end_at": r["end_at"],
        "status": r["status"],
        "headcount": r.get("headcount", 1),
        "provisional_fee_cents": r.get("provisional_fee_cents", 0),
        "final_fee_cents": r.get("final_fee_cents"),
        "actual_start_at": r.get("actual_start_at"),
        "actual_end_at": r.get("actual_end_at"),
        "bill_id": r.get("bill_id"),
    }


def _validate_time_window(start_dt, end_dt, now):
    if start_dt is None or end_dt is None:
        raise_error(ERR_INVALID_TIME_WINDOW, "Invalid start_at or end_at")
    if not is_minute_aligned(start_dt) or not is_minute_aligned(end_dt):
        raise_error(ERR_INVALID_TIME_WINDOW, "Times must be minute-aligned")
    if start_dt >= end_dt:
        raise_error(ERR_INVALID_TIME_WINDOW, "start_at must be strictly earlier than end_at")
    window_start = now - timedelta(hours=1)
    window_end = now + timedelta(days=180)
    if start_dt < window_start or end_dt > window_end:
        raise_error(ERR_INVALID_TIME_WINDOW, "Reservation window out of bounds")


def _validate_granularity(kind: str, start_dt, end_dt):
    seconds = (end_dt - start_dt).total_seconds()
    if kind == "EVENT_AREA":
        if seconds % (4 * 3600) != 0:
            raise_error(ERR_RESERVATION_GRANULARITY, "Event area must be in 4-hour blocks")
    elif kind == "MEETING_ROOM":
        if seconds % (30 * 60) != 0:
            raise_error(ERR_RESERVATION_GRANULARITY, "Meeting room must be in half-hour blocks")
    elif kind == "WORKSTATION":
        if seconds % 3600 != 0:
            raise_error(ERR_RESERVATION_GRANULARITY, "Workstation must be in 1-hour blocks")


def _overlap(a_start, a_end, b_start, b_end) -> bool:
    """Half-open overlap check."""
    return a_start < b_end and b_start < a_end


def _check_overlap(resource_id: str, start_dt, end_dt, exclude_id: str | None = None,
                    statuses=("PENDING", "CONFIRMED", "IN_USE")):
    for r in db.reservations.values():
        if r["id"] == exclude_id:
            continue
        if r["resource_id"] != resource_id:
            continue
        if r["status"] not in statuses:
            continue
        rs = parse_iso(r["start_at"])
        re = parse_iso(r["end_at"])
        if _overlap(start_dt, end_dt, rs, re):
            raise_error(ERR_RESERVATION_CONFLICT, "Reservation overlaps an existing reservation")


@bp.route("/reservations", methods=["POST"])
def create_reservation():
    require_roles("TenantMember", "TenantAdmin")
    body = request.get_json(silent=True) or {}
    tenant_id = body.get("tenant_id")
    member_id = body.get("member_id")
    resource_id = body.get("resource_id")
    start_at = body.get("start_at")
    end_at = body.get("end_at")
    headcount = body.get("headcount", 1)

    if not tenant_id or not member_id or not resource_id:
        raise_error(("ERR_INVALID_INPUT", 422), "tenant_id, member_id, resource_id are required")
    if not isinstance(headcount, int) or headcount < 1:
        raise_error(("ERR_INVALID_INPUT", 422), "headcount must be >= 1")

    # FK existence
    tenant = db.tenants.get(tenant_id)
    member = db.members.get(member_id)
    resource = db.resources.get(resource_id)
    if not tenant or not member or not resource:
        raise_error(ERR_REFERENCED_ENTITY_MISSING, "Referenced entity missing")

    # Actor scope: acting member must belong to this tenant
    actor = g.acting_member
    if not actor or actor["tenant_id"] != tenant_id:
        raise_error(ERR_FORBIDDEN, "Cannot create reservation for another tenant")
    # TenantMember can only create for themselves
    if g.user_role == "TenantMember" and actor["id"] != member_id:
        raise_error(ERR_FORBIDDEN, "TenantMember can only reserve for themselves")

    # Cross-tenant: member must belong to tenant_id
    if member["tenant_id"] != tenant_id:
        raise_error(ERR_TENANT_MISMATCH, "Member does not belong to tenant")

    start_dt = parse_iso(start_at)
    end_dt = parse_iso(end_at)
    _validate_time_window(start_dt, end_dt, db.now())
    _validate_granularity(resource["kind"], start_dt, end_dt)

    # Capacity
    if headcount > resource["capacity"]:
        raise_error(ERR_CAPACITY_EXCEEDED, "Headcount exceeds resource capacity")

    # Overlap guard
    _check_overlap(resource_id, start_dt, end_dt)

    reservation = {
        "tenant_id": tenant_id,
        "member_id": member_id,
        "resource_id": resource_id,
        "start_at": now_iso_string(start_dt),
        "end_at": now_iso_string(end_dt),
        "status": "PENDING",
        "headcount": headcount,
        "provisional_fee_cents": 0,
        "final_fee_cents": None,
        "actual_start_at": None,
        "actual_end_at": None,
        "bill_id": None,
    }
    add_common_fields(reservation, db.now(), db.new_id())
    db.reservations[reservation["id"]] = reservation
    return success(reservation_view(reservation), 201)


@bp.route("/reservations/<reservation_id>/confirm", methods=["POST"])
def confirm_reservation(reservation_id):
    require_roles("TenantMember", "TenantAdmin")
    r = db.reservations.get(reservation_id)
    if not r:
        raise_error(ERR_NOT_FOUND, "Reservation not found")
    body = request.get_json(silent=True) or {}
    check_version(r, body.get("version"))

    actor = g.acting_member
    if not actor or actor["tenant_id"] != r["tenant_id"]:
        raise_error(ERR_FORBIDDEN, "Cannot act on another tenant's reservation")
    if g.user_role == "TenantMember" and actor["id"] != r["member_id"]:
        raise_error(ERR_FORBIDDEN, "Can only confirm own reservation")

    if r["status"] != "PENDING":
        raise_error(ERR_INVALID_RESERVATION_STATE, "Reservation not PENDING")

    tenant = db.tenants.get(r["tenant_id"])
    refresh_tenant(tenant)
    if tenant["access_posture"] != "OPEN":
        raise_error(ERR_ACCESS_POSTURE_DENIES, "Tenant access posture is not OPEN")

    resource = db.resources.get(r["resource_id"])
    if resource["status"] != "AVAILABLE":
        raise_error(ERR_INVALID_RESERVATION_STATE, "Resource not AVAILABLE")

    member = db.members.get(r["member_id"])
    if member["status"] != "ACTIVE":
        raise_error(ERR_INVALID_RESERVATION_STATE, "Member not ACTIVE")

    start_dt = parse_iso(r["start_at"])
    end_dt = parse_iso(r["end_at"])
    # Overlap check against CONFIRMED/IN_USE (other reservations)
    _check_overlap(r["resource_id"], start_dt, end_dt,
                    exclude_id=r["id"], statuses=("CONFIRMED", "IN_USE"))

    # Compute provisional fee
    r["_start_at_dt"] = start_dt
    r["_end_at_dt"] = end_dt
    fee = compute_provisional_fee(r, resource, r["tenant_id"])
    r.pop("_start_at_dt", None)
    r.pop("_end_at_dt", None)
    r["status"] = "CONFIRMED"
    r["provisional_fee_cents"] = fee
    bump(r, db.now())
    return success(reservation_view(r))


@bp.route("/reservations/<reservation_id>/cancel", methods=["POST"])
def cancel_reservation(reservation_id):
    require_roles("TenantMember", "TenantAdmin")
    r = db.reservations.get(reservation_id)
    if not r:
        raise_error(ERR_NOT_FOUND, "Reservation not found")
    body = request.get_json(silent=True) or {}
    check_version(r, body.get("version"))

    actor = g.acting_member
    if not actor or actor["tenant_id"] != r["tenant_id"]:
        raise_error(ERR_FORBIDDEN, "Cannot act on another tenant's reservation")
    if g.user_role == "TenantMember" and actor["id"] != r["member_id"]:
        raise_error(ERR_FORBIDDEN, "Can only cancel own reservation")

    if r["status"] == "PENDING":
        r["status"] = "CANCELLED"
        r["provisional_fee_cents"] = 0
        bump(r, db.now())
        return success(reservation_view(r))
    if r["status"] == "CONFIRMED":
        start_dt = parse_iso(r["start_at"])
        now = db.now()
        if now >= start_dt:
            raise_error(ERR_INVALID_RESERVATION_STATE, "Cannot cancel a CONFIRMED reservation at/after start_at")
        r["status"] = "CANCELLED"
        r["provisional_fee_cents"] = 0
        bump(r, now)
        return success(reservation_view(r))
    raise_error(ERR_INVALID_RESERVATION_STATE, f"Cannot cancel reservation in status {r['status']}")


@bp.route("/reservations/<reservation_id>", methods=["GET"])
def get_reservation(reservation_id):
    require_roles("PlatformAdmin", "TenantAdmin", "TenantMember")
    r = db.reservations.get(reservation_id)
    if not r:
        raise_error(ERR_NOT_FOUND, "Reservation not found")
    if g.user_role in ("TenantAdmin", "TenantMember"):
        actor = g.acting_member
        if not actor or actor["tenant_id"] != r["tenant_id"]:
            raise_error(ERR_FORBIDDEN, "Reservation not accessible")
    return success(reservation_view(r))


@bp.route("/reservations", methods=["GET"])
def list_reservations():
    require_roles("PlatformAdmin", "TenantAdmin", "TenantMember", "BillingOfficer")
    tenant_id = request.args.get("tenant_id")
    resource_id = request.args.get("resource_id")
    status = request.args.get("status")
    start_after = request.args.get("start_after")
    start_before = request.args.get("start_before")
    limit, offset = parse_pagination()

    items = list(db.reservations.values())
    # Tenant scoping for role
    if g.user_role in ("TenantAdmin", "TenantMember"):
        actor = g.acting_member
        if not actor:
            raise_error(ERR_FORBIDDEN, "No acting tenant")
        items = [r for r in items if r["tenant_id"] == actor["tenant_id"]]
    if tenant_id:
        items = [r for r in items if r["tenant_id"] == tenant_id]
    if resource_id:
        items = [r for r in items if r["resource_id"] == resource_id]
    if status:
        items = [r for r in items if r["status"] == status]
    if start_after:
        sa_dt = parse_iso(start_after)
        if sa_dt:
            items = [r for r in items if parse_iso(r["start_at"]) > sa_dt]
    if start_before:
        sb_dt = parse_iso(start_before)
        if sb_dt:
            items = [r for r in items if parse_iso(r["start_at"]) < sb_dt]

    items.sort(key=lambda r: r["created_at"])
    page, meta = paginate(items, limit, offset)
    return success([reservation_view(r) for r in page], pagination=meta)
