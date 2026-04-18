"""Access events: drive check-in/check-out on reservations and visitors."""
from datetime import timedelta
from decimal import Decimal
import math

from flask import Blueprint

from clock import get_now, parse_iso, format_iso, iso_now
from common import stamp_update, get_json_body
from db import db, new_id
from errors import api_error
from middleware import require_roles
from response import success
from services.pricing import final_fee
from services.bill import get_or_create_draft_bill, add_bill_line, recompute_bill_totals
from services.tenant import recompute_tenant

bp = Blueprint("access_events", __name__)

OVERSTAY_RATE_CENTS_PER_30MIN = 500


def _reservation_line_kind(reservation):
    resource = db.resources.get(reservation["resource_id"])
    kind = resource["kind"] if resource else "WORKSTATION"
    mapping = {
        "WORKSTATION": "WORKSTATION_FEE",
        "MEETING_ROOM": "MEETING_ROOM_FEE",
        "EVENT_AREA": "EVENT_AREA_FEE",
    }
    return mapping.get(kind, "WORKSTATION_FEE")


@bp.route("/access-events", methods=["POST"])
def create_access_event():
    user_id, role = require_roles(["TenantMember", "TenantAdmin", "Receptionist"])
    body = get_json_body()
    kind = body.get("kind")
    reservation_id = body.get("reservation_id")
    visitor_id = body.get("visitor_id")
    badge_id = body.get("badge_id")

    if kind not in ("CHECK_IN", "CHECK_OUT", "VISITOR_CHECK_IN", "VISITOR_CHECK_OUT"):
        raise api_error("ERR_INVALID_TIME_WINDOW", "invalid kind")

    if kind in ("CHECK_IN", "CHECK_OUT"):
        if role == "Receptionist":
            raise api_error("ERR_FORBIDDEN", "Receptionist cannot drive reservation events")
        return _handle_reservation_event(user_id, role, kind, reservation_id, badge_id)

    if kind in ("VISITOR_CHECK_IN", "VISITOR_CHECK_OUT"):
        # Receptionist primary; TenantAdmin/TenantMember also allowed per scaffold
        return _handle_visitor_event(user_id, role, kind, visitor_id)

    raise api_error("ERR_INVALID_TIME_WINDOW", "unsupported kind")


def _handle_reservation_event(user_id, role, kind, reservation_id, badge_id):
    r = db.reservations.get(reservation_id) if reservation_id else None
    if not r:
        raise api_error("ERR_REFERENCED_ENTITY_MISSING", "reservation not found")

    # Ownership
    caller = db.members.get(user_id)
    if not caller:
        raise api_error("ERR_FORBIDDEN", "caller not found")
    if role == "TenantMember" and r["member_id"] != user_id:
        raise api_error("ERR_FORBIDDEN", "not owner of reservation")
    if role == "TenantAdmin" and caller["tenant_id"] != r["tenant_id"]:
        raise api_error("ERR_FORBIDDEN", "tenant mismatch")

    now = get_now()

    if kind == "CHECK_IN":
        if r["status"] != "CONFIRMED":
            raise api_error("ERR_INVALID_RESERVATION_STATE", "reservation not CONFIRMED")

        # badge
        badge = None
        if badge_id:
            badge = db.badges.get(badge_id)
            if not badge:
                raise api_error("ERR_REFERENCED_ENTITY_MISSING", "badge not found")
        else:
            # find an ACTIVE badge for this member
            for b in db.badges.values():
                if b["member_id"] == r["member_id"] and b["status"] == "ACTIVE":
                    badge = b
                    break
        if not badge or badge["status"] != "ACTIVE":
            raise api_error("ERR_INVALID_RESERVATION_STATE", "badge not ACTIVE")

        tenant = db.tenants.get(r["tenant_id"])
        if tenant and tenant.get("access_posture") == "FROZEN":
            raise api_error("ERR_ACCESS_POSTURE_DENIES", "tenant FROZEN")

        start_at = parse_iso(r["start_at"])
        end_at = parse_iso(r["end_at"])
        window_start = start_at - timedelta(minutes=15)
        if now < window_start or now >= end_at:
            raise api_error("ERR_INVALID_RESERVATION_STATE", "not within check-in window")

        r["status"] = "IN_USE"
        r["actual_start_at"] = format_iso(now)
        stamp_update(r)
        badge["last_used_at"] = format_iso(now)
        stamp_update(badge)
        return success({
            "event_id": new_id(),
            "accepted": True,
        }, status=201)

    if kind == "CHECK_OUT":
        if r["status"] != "IN_USE":
            raise api_error("ERR_INVALID_RESERVATION_STATE", "reservation not IN_USE")
        r["actual_end_at"] = format_iso(now)
        r["status"] = "COMPLETED"
        r["final_fee_cents"] = final_fee(r, "COMPLETED")
        stamp_update(r)
        # Consolidate
        bill = get_or_create_draft_bill(r["tenant_id"])
        r["bill_id"] = bill["id"]
        add_bill_line(bill, _reservation_line_kind(r), r["id"], r["final_fee_cents"])
        recompute_bill_totals(bill)
        return success({
            "event_id": new_id(),
            "accepted": True,
        }, status=201)

    raise api_error("ERR_INVALID_TIME_WINDOW", "unsupported reservation event kind")


def _handle_visitor_event(user_id, role, kind, visitor_id):
    v = db.visitors.get(visitor_id) if visitor_id else None
    if not v:
        raise api_error("ERR_REFERENCED_ENTITY_MISSING", "visitor not found")

    now = get_now()
    if kind == "VISITOR_CHECK_IN":
        if v["status"] != "REGISTERED":
            raise api_error("ERR_INVALID_VISITOR_STATE", "visitor not REGISTERED")
        host = db.members.get(v["host_member_id"])
        if not host or host["status"] != "ACTIVE":
            raise api_error("ERR_INVALID_VISITOR_STATE", "host not ACTIVE")
        tenant = db.tenants.get(v["tenant_id"])
        if tenant and tenant.get("access_posture") == "FROZEN":
            raise api_error("ERR_ACCESS_POSTURE_DENIES", "tenant FROZEN")
        exp_arr = parse_iso(v["expected_arrival_at"])
        exp_dep = parse_iso(v["expected_departure_at"])
        window_start = exp_arr - timedelta(minutes=30)
        window_end = exp_dep + timedelta(hours=6)
        if now < window_start or now > window_end:
            raise api_error("ERR_INVALID_VISITOR_STATE", "not within visitor check-in window")

        v["status"] = "CHECKED_IN"
        v["actual_arrival_at"] = format_iso(now)
        return success({
            "event_id": new_id(),
            "accepted": True,
        }, status=201)

    if kind == "VISITOR_CHECK_OUT":
        if v["status"] != "CHECKED_IN":
            raise api_error("ERR_INVALID_VISITOR_STATE", "visitor not CHECKED_IN")
        v["actual_departure_at"] = format_iso(now)
        # Compute overstay fee
        exp_dep = parse_iso(v["expected_departure_at"])
        overstay_seconds = max(0, (now - exp_dep).total_seconds())
        overstay_minutes = overstay_seconds / 60
        if overstay_minutes <= 0:
            fee = 0
        else:
            units = math.ceil(overstay_minutes / 30)
            fee = units * OVERSTAY_RATE_CENTS_PER_30MIN
        v["overstay_fee_cents"] = fee
        v["status"] = "CHECKED_OUT"
        if fee > 0:
            bill = get_or_create_draft_bill(v["tenant_id"])
            v["bill_id"] = bill["id"]
            add_bill_line(bill, "VISITOR_OVERSTAY", v["id"], fee)
            recompute_bill_totals(bill)
        return success({
            "event_id": new_id(),
            "accepted": True,
        }, status=201)

    raise api_error("ERR_INVALID_TIME_WINDOW", "unsupported visitor event kind")
