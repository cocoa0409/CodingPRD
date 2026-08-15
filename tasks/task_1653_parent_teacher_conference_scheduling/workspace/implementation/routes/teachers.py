"""Teacher endpoints."""

from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import db
import errors
import middleware
import response
import serializers
import util
from services import core

bp = Blueprint("teachers", __name__)

ALL_ROLES = {"SchoolAdmin", "FrontOfficeStaff", "Teacher", "FamilyGuardian", "Interpreter"}
STAFF_TEACHER = {"SchoolAdmin", "FrontOfficeStaff", "Teacher"}


@bp.route("/conf/teachers", methods=["POST"])
def create_teacher():
    role, _uid = middleware.get_auth()
    middleware.require_roles(role, {"SchoolAdmin"})
    body = util.get_body()
    util.require_fields(body, ["full_name", "email", "grade_band", "subjects"])
    full_name = util.require_string(body, "full_name")
    email = util.require_string(body, "email")
    grade_band = util.require_enum(body, "grade_band", {"ELEMENTARY", "SECONDARY", "BOTH"})
    subjects = body.get("subjects")
    if not isinstance(subjects, list) or any(not isinstance(s, str) for s in subjects):
        raise errors.validation("subjects must be an array of strings")
    room_location = util.optional_string(body, "room_location", default=None)
    supports_in_person = util.optional_bool(body, "supports_in_person", default=True)
    supports_virtual = util.optional_bool(body, "supports_virtual", default=False)
    cap_override = util.optional_int(body, "daily_conf_cap_override", default=None, min_value=1)

    now = util.now_iso()
    teacher = {
        "id": util.new_id(),
        "full_name": full_name,
        "email": email,
        "grade_band": grade_band,
        "subjects": subjects,
        "room_location": room_location,
        "supports_in_person": supports_in_person,
        "supports_virtual": supports_virtual,
        "daily_conf_cap_override": cap_override,
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.teachers[teacher["id"]] = teacher
    return response.success_object(serializers.teacher_view(teacher), status=201)


@bp.route("/conf/teachers", methods=["GET"])
def list_teachers():
    role, _uid = middleware.get_auth()
    middleware.require_roles(role, ALL_ROLES)
    limit, offset = util.parse_pagination(request.args)
    status = request.args.get("status")
    grade_band = request.args.get("grade_band")
    items = list(db.teachers.values())
    if status is not None:
        items = [t for t in items if t["status"] == status]
    if grade_band is not None:
        items = [t for t in items if t["grade_band"] == grade_band]
    items.sort(key=lambda t: t["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_list([serializers.teacher_view(t) for t in page],
                                 total, limit, offset)


@bp.route("/conf/teachers/<tid>", methods=["GET"])
def get_teacher(tid):
    role, _uid = middleware.get_auth()
    middleware.require_roles(role, ALL_ROLES)
    teacher = core.get_teacher_or_404(tid)
    return response.success_object(serializers.teacher_view(teacher))


@bp.route("/conf/teachers/<tid>", methods=["PATCH"])
def update_teacher(tid):
    role, _uid = middleware.get_auth()
    middleware.require_roles(role, {"SchoolAdmin"})
    body = util.get_body()
    teacher = core.get_teacher_or_404(tid)

    if "full_name" in body and body["full_name"] is not None:
        if not isinstance(body["full_name"], str) or body["full_name"] == "":
            raise errors.validation("full_name must be a non-empty string")
    if "room_location" in body and body["room_location"] is not None:
        if not isinstance(body["room_location"], str):
            raise errors.validation("room_location must be a string")
    for f in ("supports_in_person", "supports_virtual"):
        if f in body and body[f] is not None and not isinstance(body[f], bool):
            raise errors.validation(f"{f} must be a boolean")
    if "daily_conf_cap_override" in body and body["daily_conf_cap_override"] is not None:
        util.require_int(body, "daily_conf_cap_override", min_value=1)
    if "status" in body and body["status"] is not None:
        util.require_enum(body, "status", {"ACTIVE", "INACTIVE"})

    if "full_name" in body and body["full_name"] is not None:
        teacher["full_name"] = body["full_name"]
    if "room_location" in body:
        teacher["room_location"] = body["room_location"]
    for f in ("supports_in_person", "supports_virtual"):
        if f in body and body[f] is not None:
            teacher[f] = body[f]
    if "daily_conf_cap_override" in body:
        teacher["daily_conf_cap_override"] = body["daily_conf_cap_override"]

    new_status = body.get("status")
    if new_status is not None and new_status != teacher["status"]:
        if new_status == "INACTIVE":
            teacher["status"] = "INACTIVE"
            teacher["version"] += 1
            teacher["updated_at"] = util.now_iso()
            core.teacher_deactivation_cascade(teacher)
            return response.success_object(serializers.teacher_view(teacher))
        else:
            teacher["status"] = "ACTIVE"

    teacher["version"] += 1
    teacher["updated_at"] = util.now_iso()
    return response.success_object(serializers.teacher_view(teacher))


@bp.route("/conf/teachers/<tid>/slots", methods=["GET"])
def list_teacher_slots(tid):
    role, _uid = middleware.get_auth()
    middleware.require_roles(role, STAFF_TEACHER)
    teacher = core.get_teacher_or_404(tid)
    middleware.check_teacher_owns(role, _uid, teacher["id"])
    limit, offset = util.parse_pagination(request.args)
    window_id = request.args.get("window_id")
    status = request.args.get("status")
    items = [s for s in db.slots.values() if s["teacher_id"] == tid]
    if window_id is not None:
        items = [s for s in items if s["window_id"] == window_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items.sort(key=lambda s: (s["start_at"], s["created_at"]))
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_list([serializers.slot_view(s) for s in page],
                                 total, limit, offset)


@bp.route("/conf/teachers/<tid>/teacher-links", methods=["GET"])
def list_teacher_links(tid):
    role, _uid = middleware.get_auth()
    middleware.require_roles(role, STAFF_TEACHER)
    teacher = core.get_teacher_or_404(tid)
    middleware.check_teacher_owns(role, _uid, teacher["id"])
    limit, offset = util.parse_pagination(request.args)
    items = [l for l in db.links.values() if l["teacher_id"] == tid]
    items.sort(key=lambda l: l["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_list([serializers.link_view(l) for l in page],
                                 total, limit, offset)


@bp.route("/conf/teachers/<tid>/summary", methods=["GET"])
def teacher_summary(tid):
    role, _uid = middleware.get_auth()
    middleware.require_roles(role, STAFF_TEACHER)
    teacher = core.get_teacher_or_404(tid)
    middleware.check_teacher_owns(role, _uid, teacher["id"])
    window_id = request.args.get("window_id")
    if not window_id:
        raise errors.validation("window_id query parameter is required")
    core.get_window_or_404(window_id)

    slots = [s for s in db.slots.values()
             if s["teacher_id"] == tid and s["window_id"] == window_id
             and s["status"] in ("OPEN", "BLOCKED", "HELD", "BOOKED")]
    bookable = len(slots)
    booked = sum(1 for s in slots if s["status"] == "BOOKED")
    held = sum(1 for s in slots if s["status"] == "HELD")
    open_count = sum(1 for s in slots if s["status"] == "OPEN")
    waiting = sum(1 for e in db.waitlist_entries.values()
                  if e["teacher_id"] == tid and e["window_id"] == window_id
                  and e["status"] == "WAITING")
    if bookable == 0:
        booked_pct = 0.0
        projected_pct = 0.0
    else:
        booked_pct = float(Decimal(100 * booked / bookable).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP))
        expected_claims = util.ceil_div_minutes(waiting, 2)  # ceil(waiting * 0.5)
        projected_pct = float(Decimal(100 * (booked + held + expected_claims) / bookable).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP))
    summary = {
        "teacher_id": tid,
        "window_id": window_id,
        "bookable_slots": bookable,
        "booked_slots": booked,
        "held_slots": held,
        "open_slots": open_count,
        "waiting_entries": waiting,
        "booked_utilization_pct": booked_pct,
        "projected_utilization_pct": projected_pct,
    }
    return response.success_object(summary)
