from datetime import timedelta
import math

from flask import Blueprint, request, g

from errors import (
    raise_error, ERR_NOT_FOUND, ERR_REFERENCED_ENTITY_MISSING,
    ERR_INVALID_RESERVATION_STATE, ERR_INVALID_VISITOR_STATE,
    ERR_ACCESS_POSTURE_DENIES, ERR_FORBIDDEN,
)
from response import success
from middleware import require_roles
from util import parse_iso, bump, now_iso_string
from db import db
from services.pricing import compute_final_fee
from services.bill_service import (
    get_or_create_draft_bill, append_line, recompute_bill_totals,
)
from services.tenant_service import refresh_tenant

bp = Blueprint("access_events", __name__)


VALID_KINDS = {"CHECK_IN", "CHECK_OUT", "VISITOR_CHECK_IN", "VISITOR_CHECK_OUT"}


def _line_kind_for_resource(kind: str) -> str:
    return {
        "WORKSTATION": "WORKSTATION_FEE",
        "MEETING_ROOM": "MEETING_ROOM_FEE",
        "EVENT_AREA": "EVENT_AREA_FEE",
    }.get(kind, "WORKSTATION_FEE")


def _consolidate_reservation(reservation: dict):
    tenant_id = reservation["tenant_id"]
    tenant = db.tenants.get(tenant_id)
    bill = get_or_create_draft_bill(tenant_id)
    reservation["bill_id"] = bill["id"]
    resource = db.resources.get(reservation["resource_id"])
    kind = resource["kind"] if resource else None
    amount = reservation.get("final_fee_cents", 0) or 0
    if amount > 0:
        append_line(bill, _line_kind_for_resource(kind), reservation["id"], amount)
    recompute_bill_totals(bill)
    bump(bill, db.now())
    refresh_tenant(tenant)


def _consolidate_visitor(visitor: dict):
    if (visitor.get("overstay_fee_cents", 0) or 0) <= 0:
        return
    tenant_id = visitor["tenant_id"]
    tenant = db.tenants.get(tenant_id)
    bill = get_or_create_draft_bill(tenant_id)
    visitor["bill_id"] = bill["id"]
    append_line(bill, "VISITOR_OVERSTAY", visitor["id"], visitor["overstay_fee_cents"])
    recompute_bill_totals(bill)
    bump(bill, db.now())
    refresh_tenant(tenant)


@bp.route("/access-events", methods=["POST"])
def record_event():
    require_roles("TenantMember", "TenantAdmin", "Receptionist")
    body = request.get_json(silent=True) or {}
    kind = body.get("kind")
    if kind not in VALID_KINDS:
        raise_error(("ERR_INVALID_INPUT", 422), f"kind must be one of {VALID_KINDS}")

    now = db.now()

    if kind == "CHECK_IN":
        return _handle_reservation_check_in(body, now)
    if kind == "CHECK_OUT":
        return _handle_reservation_check_out(body, now)
    if kind == "VISITOR_CHECK_IN":
        return _handle_visitor_check_in(body, now)
    if kind == "VISITOR_CHECK_OUT":
        return _handle_visitor_check_out(body, now)


def _handle_reservation_check_in(body, now):
    # Role: TenantMember or TenantAdmin
    if g.user_role not in ("TenantMember", "TenantAdmin"):
        raise_error(ERR_FORBIDDEN, "Role not permitted for CHECK_IN")
    reservation_id = body.get("reservation_id")
    badge_id = body.get("badge_id")
    if not reservation_id:
        raise_error(("ERR_INVALID_INPUT", 422), "reservation_id required")
    r = db.reservations.get(reservation_id)
    if not r:
        raise_error(ERR_REFERENCED_ENTITY_MISSING, "Reservation not found")

    actor = g.acting_member
    if not actor or actor["tenant_id"] != r["tenant_id"]:
        raise_error(ERR_FORBIDDEN, "Cannot act on another tenant's reservation")
    if g.user_role == "TenantMember" and actor["id"] != r["member_id"]:
        raise_error(ERR_FORBIDDEN, "Can only check in own reservation")

    if r["status"] != "CONFIRMED":
        raise_error(ERR_INVALID_RESERVATION_STATE, "Reservation is not CONFIRMED")

    # Member's ACTIVE badge
    member = db.members.get(r["member_id"])
    active_badge = None
    if badge_id:
        badge = db.access_badges.get(badge_id)
        if not badge:
            raise_error(ERR_REFERENCED_ENTITY_MISSING, "Badge not found")
        if badge["member_id"] != r["member_id"]:
            raise_error(ERR_INVALID_RESERVATION_STATE, "Badge does not belong to reserving member")
        if badge["status"] != "ACTIVE":
            raise_error(ERR_INVALID_RESERVATION_STATE, "Badge is not ACTIVE")
        active_badge = badge
    else:
        for badge in db.access_badges.values():
            if badge["member_id"] == r["member_id"] and badge["status"] == "ACTIVE":
                active_badge = badge
                break
        if not active_badge:
            raise_error(ERR_INVALID_RESERVATION_STATE, "Member has no ACTIVE badge")

    tenant = db.tenants.get(r["tenant_id"])
    refresh_tenant(tenant)
    if tenant["access_posture"] == "FROZEN":
        raise_error(ERR_ACCESS_POSTURE_DENIES, "Tenant posture FROZEN blocks check-in")

    start_dt = parse_iso(r["start_at"])
    end_dt = parse_iso(r["end_at"])
    if now < (start_dt - timedelta(minutes=15)):
        raise_error(ERR_INVALID_RESERVATION_STATE, "Too early to check in")
    if now >= end_dt:
        raise_error(ERR_INVALID_RESERVATION_STATE, "Too late to check in")

    r["status"] = "IN_USE"
    r["actual_start_at"] = now_iso_string(now)
    bump(r, now)
    active_badge["last_used_at"] = now_iso_string(now)
    bump(active_badge, now)

    from routes.reservations import reservation_view
    return success(reservation_view(r))


def _handle_reservation_check_out(body, now):
    if g.user_role not in ("TenantMember", "TenantAdmin"):
        raise_error(ERR_FORBIDDEN, "Role not permitted for CHECK_OUT")
    reservation_id = body.get("reservation_id")
    if not reservation_id:
        raise_error(("ERR_INVALID_INPUT", 422), "reservation_id required")
    r = db.reservations.get(reservation_id)
    if not r:
        raise_error(ERR_REFERENCED_ENTITY_MISSING, "Reservation not found")
    actor = g.acting_member
    if not actor or actor["tenant_id"] != r["tenant_id"]:
        raise_error(ERR_FORBIDDEN, "Cannot act on another tenant's reservation")
    if g.user_role == "TenantMember" and actor["id"] != r["member_id"]:
        raise_error(ERR_FORBIDDEN, "Can only check out own reservation")
    if r["status"] != "IN_USE":
        raise_error(ERR_INVALID_RESERVATION_STATE, "Reservation is not IN_USE")

    r["status"] = "COMPLETED"
    r["actual_end_at"] = now_iso_string(now)
    resource = db.resources.get(r["resource_id"])
    actual_start = parse_iso(r.get("actual_start_at")) or parse_iso(r["start_at"])
    actual_end = parse_iso(r["actual_end_at"])
    r["_start_at_dt"] = parse_iso(r["start_at"])
    r["_end_at_dt"] = parse_iso(r["end_at"])
    r["final_fee_cents"] = compute_final_fee(r, resource, r["tenant_id"], actual_start, actual_end)
    r.pop("_start_at_dt", None)
    r.pop("_end_at_dt", None)
    bump(r, now)

    _consolidate_reservation(r)

    from routes.reservations import reservation_view
    return success(reservation_view(r))


def _handle_visitor_check_in(body, now):
    if g.user_role != "Receptionist":
        raise_error(ERR_FORBIDDEN, "Only Receptionist may check in a visitor")
    visitor_id = body.get("visitor_id")
    if not visitor_id:
        raise_error(("ERR_INVALID_INPUT", 422), "visitor_id required")
    v = db.visitors.get(visitor_id)
    if not v:
        raise_error(ERR_REFERENCED_ENTITY_MISSING, "Visitor not found")
    if v["status"] != "REGISTERED":
        raise_error(ERR_INVALID_VISITOR_STATE, "Visitor is not REGISTERED")
    host = db.members.get(v["host_member_id"])
    if not host or host["status"] != "ACTIVE":
        raise_error(ERR_INVALID_VISITOR_STATE, "Host member is not ACTIVE")
    tenant = db.tenants.get(v["tenant_id"])
    refresh_tenant(tenant)
    if tenant["access_posture"] == "FROZEN":
        raise_error(ERR_ACCESS_POSTURE_DENIES, "Tenant posture FROZEN blocks visitor check-in")
    expected_arrival = parse_iso(v["expected_arrival_at"])
    expected_departure = parse_iso(v["expected_departure_at"])
    if now < (expected_arrival - timedelta(minutes=30)):
        raise_error(ERR_INVALID_VISITOR_STATE, "Too early to check in visitor")
    if now > (expected_departure + timedelta(hours=6)):
        raise_error(ERR_INVALID_VISITOR_STATE, "Too late to check in visitor")

    v["status"] = "CHECKED_IN"
    v["actual_arrival_at"] = now_iso_string(now)
    # Visitor has no version/updated_at per PRD
    from routes.visitors import visitor_view
    return success(visitor_view(v))


def _handle_visitor_check_out(body, now):
    if g.user_role != "Receptionist":
        raise_error(ERR_FORBIDDEN, "Only Receptionist may check out a visitor")
    visitor_id = body.get("visitor_id")
    if not visitor_id:
        raise_error(("ERR_INVALID_INPUT", 422), "visitor_id required")
    v = db.visitors.get(visitor_id)
    if not v:
        raise_error(ERR_REFERENCED_ENTITY_MISSING, "Visitor not found")
    if v["status"] != "CHECKED_IN":
        raise_error(ERR_INVALID_VISITOR_STATE, "Visitor is not CHECKED_IN")
    v["status"] = "CHECKED_OUT"
    v["actual_departure_at"] = now_iso_string(now)
    # compute overstay
    expected_dep = parse_iso(v["expected_departure_at"])
    actual_dep = parse_iso(v["actual_departure_at"])
    delta = (actual_dep - expected_dep).total_seconds() if actual_dep > expected_dep else 0
    if delta <= 0:
        v["overstay_fee_cents"] = 0
    else:
        minutes = delta / 60
        units = math.ceil(minutes / 30)
        v["overstay_fee_cents"] = units * 500
    if v["overstay_fee_cents"] > 0:
        _consolidate_visitor(v)
    from routes.visitors import visitor_view
    return success(visitor_view(v))
