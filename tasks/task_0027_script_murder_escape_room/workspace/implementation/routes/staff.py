"""Staff member and staff assignment routes."""
from flask import Blueprint

from db import store, make_common, bump, parse_iso
from middleware import require_role
from response import success_object
from validators import (
    get_json_body, require_string, require_int, optional_int, require_list,
    require_enum,
)
from errors import (
    raise_error,
    ERR_STAFF_MEMBER_NOT_FOUND, ERR_STAFF_ASSIGNMENT_NOT_FOUND, ERR_SLOT_NOT_FOUND,
    ERR_INVALID_REQUEST, ERR_INSUFFICIENT_PERMISSIONS,
    ERR_HANDOFF_AFTER_LIVE, ERR_VENUE_NOT_ACTIVE,
)
from services import staff_service

staff_bp = Blueprint("staff", __name__)


ROLE_TYPES = ["HOST", "NPC"]


def staff_view(s: dict) -> dict:
    return {
        "id": s["id"],
        "chain_id": s["chain_id"],
        "display_name": s["display_name"],
        "roles_held": s["roles_held"],
        "qualifications": s["qualifications"],
        "max_weekly_minutes": s["max_weekly_minutes"],
        "commission_bps_override": s.get("commission_bps_override"),
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def assignment_view(a: dict) -> dict:
    return {
        "id": a["id"],
        "slot_id": a["slot_id"],
        "staff_member_id": a["staff_member_id"],
        "role_type": a["role_type"],
        "assignment_minutes": a["assignment_minutes"],
        "substitute_of_assignment_id": a.get("substitute_of_assignment_id"),
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


@staff_bp.route("/staff-members", methods=["POST"])
def create_staff_member():
    user_id, role = require_role("PlatformAdmin")
    body = get_json_body()
    chain_id = require_string(body, "chain_id")
    display_name = require_string(body, "display_name", 1, 200)
    roles_held = require_list(body, "roles_held")
    if not roles_held:
        raise_error(ERR_INVALID_REQUEST, "roles_held must be non-empty")
    for r in roles_held:
        if r not in ("HOST", "NPC"):
            raise_error(ERR_INVALID_REQUEST, "roles_held must be subset of {HOST, NPC}")
    qualifications = body.get("qualifications") or []
    if not isinstance(qualifications, list):
        raise_error(ERR_INVALID_REQUEST, "qualifications must be array")
    max_weekly_minutes = optional_int(body, "max_weekly_minutes", 1, 10080, default=2400)
    commission_override = optional_int(body, "commission_bps_override", 0, 10000, default=None)
    s = make_common({
        "chain_id": chain_id,
        "display_name": display_name,
        "roles_held": roles_held,
        "qualifications": qualifications,
        "max_weekly_minutes": max_weekly_minutes,
        "commission_bps_override": commission_override,
        "status": "ACTIVE",
    })
    store.staff_members[s["id"]] = s
    return success_object(staff_view(s), 201)


@staff_bp.route("/staff-members/<staff_id>", methods=["GET"])
def get_staff_member(staff_id):
    user_id, role = require_role("PlatformAdmin", "VenueOperator", "Host", "NPC")
    s = store.staff_members.get(staff_id)
    if not s:
        raise_error(ERR_STAFF_MEMBER_NOT_FOUND, "staff not found")
    # Host/NPC: only own
    if role in ("Host", "NPC") and user_id != staff_id:
        raise_error(ERR_INSUFFICIENT_PERMISSIONS, "not own staff record")
    return success_object(staff_view(s))


@staff_bp.route("/staff-assignments", methods=["POST"])
def create_assignment():
    user_id, role = require_role("VenueOperator")
    body = get_json_body()
    slot_id = require_string(body, "slot_id")
    staff_member_id = require_string(body, "staff_member_id")
    role_type = require_enum(body, "role_type", ROLE_TYPES)
    slot = store.session_slots.get(slot_id)
    if not slot:
        raise_error(ERR_SLOT_NOT_FOUND, "slot not found")
    staff = store.staff_members.get(staff_member_id)
    if not staff:
        raise_error(ERR_STAFF_MEMBER_NOT_FOUND, "staff not found")
    venue = store.venues.get(slot["venue_id"])
    if not venue:
        raise_error(ERR_INVALID_REQUEST, "venue not found")
    if user_id != venue["id"]:
        raise_error(ERR_INSUFFICIENT_PERMISSIONS, "venue ownership mismatch")
    if venue["status"] != "ACTIVE":
        raise_error(ERR_VENUE_NOT_ACTIVE, "venue not active")

    # Validations in order
    staff_service.chain_for_staff_check(staff, slot)
    staff_service.staff_overlap_check(staff_member_id, slot)
    staff_service.qualification_check(staff, slot, role_type)
    starts = parse_iso(slot["starts_at"])
    ends = parse_iso(slot["ends_at"])
    minutes = int((ends - starts).total_seconds() // 60)
    staff_service.weekly_minutes_check(staff, slot, minutes)

    a = make_common({
        "slot_id": slot_id,
        "staff_member_id": staff_member_id,
        "role_type": role_type,
        "assignment_minutes": minutes,
        "substitute_of_assignment_id": None,
        "status": "SCHEDULED",
    })
    store.staff_assignments[a["id"]] = a
    return success_object(assignment_view(a), 201)


@staff_bp.route("/staff-assignments/<assignment_id>/handoff", methods=["POST"])
def handoff_assignment(assignment_id):
    user_id, role = require_role("VenueOperator")
    a = store.staff_assignments.get(assignment_id)
    if not a:
        raise_error(ERR_STAFF_ASSIGNMENT_NOT_FOUND, "assignment not found")
    slot = store.session_slots.get(a["slot_id"])
    if not slot:
        raise_error(ERR_SLOT_NOT_FOUND, "slot not found")
    venue = store.venues.get(slot["venue_id"])
    if user_id != venue["id"]:
        raise_error(ERR_INSUFFICIENT_PERMISSIONS, "venue ownership mismatch")
    if a["status"] != "SCHEDULED":
        raise_error(ERR_HANDOFF_AFTER_LIVE, "assignment not SCHEDULED")
    if slot["schedule_status"] != "SCHEDULED":
        raise_error(ERR_HANDOFF_AFTER_LIVE, "slot not SCHEDULED")
    # Depth check
    staff_service.depth_check(a)

    body = get_json_body()
    substitute_id = require_string(body, "substitute_staff_member_id")
    sub = store.staff_members.get(substitute_id)
    if not sub:
        raise_error(ERR_STAFF_MEMBER_NOT_FOUND, "substitute not found")

    # Substitute validations
    staff_service.chain_for_staff_check(sub, slot)
    staff_service.staff_overlap_check(substitute_id, slot)
    staff_service.qualification_check(sub, slot, a["role_type"])
    starts = parse_iso(slot["starts_at"])
    ends = parse_iso(slot["ends_at"])
    minutes = int((ends - starts).total_seconds() // 60)
    staff_service.weekly_minutes_check(sub, slot, minutes)

    # Original moves to HANDED_OFF
    a["status"] = "HANDED_OFF"
    bump(a)
    # New SCHEDULED assignment
    new_a = make_common({
        "slot_id": slot["id"],
        "staff_member_id": substitute_id,
        "role_type": a["role_type"],
        "assignment_minutes": minutes,
        "substitute_of_assignment_id": a["id"],
        "status": "SCHEDULED",
    })
    store.staff_assignments[new_a["id"]] = new_a
    # Per PRD §3.8 the handoff produces "a new `StaffAssignment` row" — return
    # that fresh substitute so callers can chain on it. The original is still
    # HANDED_OFF and discoverable via GET.
    return success_object(assignment_view(new_a))


@staff_bp.route("/staff-assignments/<assignment_id>", methods=["GET"])
def get_assignment(assignment_id):
    user_id, role = require_role("VenueOperator", "Host", "NPC", "PlatformAdmin")
    a = store.staff_assignments.get(assignment_id)
    if not a:
        raise_error(ERR_STAFF_ASSIGNMENT_NOT_FOUND, "assignment not found")
    if role in ("Host", "NPC"):
        if user_id != a["staff_member_id"]:
            raise_error(ERR_INSUFFICIENT_PERMISSIONS, "not own assignment")
    elif role == "VenueOperator":
        slot = store.session_slots.get(a["slot_id"])
        if slot:
            v = store.venues.get(slot["venue_id"])
            if not v or user_id != v["id"]:
                raise_error(ERR_INSUFFICIENT_PERMISSIONS, "venue ownership mismatch")
    return success_object(assignment_view(a))
