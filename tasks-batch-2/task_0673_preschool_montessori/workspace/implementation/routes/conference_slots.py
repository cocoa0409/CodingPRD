"""ConferenceSlot endpoints + lifecycle (PRD §3.12)."""
from flask import Blueprint

import errors
from db import db, new_common_fields, parse_iso, touch
from middleware import get_auth, require_role
from response import object_response, array_response
from services.common import (
    get_json_body, require_fields, parse_pagination, sort_created_asc, paginate,
    serialize, serialize_list, str_arg, optional_enum,
)

bp = Blueprint("conference_slots", __name__)

SLOT_STATUSES = {"OPEN", "BOOKED", "COMPLETED", "NO_SHOW", "CANCELLED"}
READ_ROLES = {"Registrar", "Guide", "Parent"}


def _get_slot_or_404(slot_id):
    slot = db.conference_slots.get(slot_id)
    if slot is None:
        raise errors.not_found("Conference slot not found.")
    return slot


def _overlaps_half_open(a_start, a_end, b_start, b_end):
    # Half-open [start, end): overlap iff a_start < b_end and b_start < a_end.
    return a_start < b_end and b_start < a_end


@bp.route("/conference-slots", methods=["POST"])
def create_conference_slot():
    _, role = get_auth()
    require_role(role, {"Guide"})
    body = get_json_body()
    require_fields(body, ["guide_user_id", "classroom_id", "start_at", "end_at"])

    guide_user_id = body["guide_user_id"]
    classroom_id = body["classroom_id"]
    for val, label in ((guide_user_id, "guide_user_id"), (classroom_id, "classroom_id")):
        if not isinstance(val, str) or val.strip() == "":
            raise errors.invalid_request(f"{label} must be a non-empty string.")
    start_at = body["start_at"]
    end_at = body["end_at"]
    for val, label in ((start_at, "start_at"), (end_at, "end_at")):
        if not isinstance(val, str):
            raise errors.invalid_request(f"{label} must be an ISO 8601 string.")
    try:
        start_dt = parse_iso(start_at)
        end_dt = parse_iso(end_at)
    except (ValueError, TypeError):
        raise errors.invalid_request("start_at/end_at must be valid ISO 8601 instants.")

    # Body FK existence (PRD §2.9): classroom.
    if classroom_id not in db.classrooms:
        raise errors.not_found("classroom_id does not exist.")

    # Interval validity (priority 12): end_at > start_at.
    if not (end_dt > start_dt):
        raise errors.invalid_interval()

    slot = new_common_fields()
    slot.update({
        "guide_user_id": guide_user_id,
        "classroom_id": classroom_id,
        "start_at": start_at,
        "end_at": end_at,
        "status": "OPEN",
        "booked_student_id": None,
    })
    db.conference_slots[slot["id"]] = slot
    return object_response(serialize(slot), 201)


@bp.route("/conference-slots/<slot_id>", methods=["GET"])
def get_conference_slot(slot_id):
    _, role = get_auth()
    require_role(role, READ_ROLES)
    return object_response(serialize(_get_slot_or_404(slot_id)), 200)


@bp.route("/conference-slots", methods=["GET"])
def list_conference_slots():
    _, role = get_auth()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    guide_user_id = str_arg("guide_user_id")
    classroom_id = str_arg("classroom_id")
    status = optional_enum(str_arg("status"), SLOT_STATUSES, "status")
    booked_student_id = str_arg("booked_student_id")

    records = list(db.conference_slots.values())
    if guide_user_id is not None:
        records = [s for s in records if s["guide_user_id"] == guide_user_id]
    if classroom_id is not None:
        records = [s for s in records if s["classroom_id"] == classroom_id]
    if status is not None:
        records = [s for s in records if s["status"] == status]
    if booked_student_id is not None:
        records = [s for s in records if s.get("booked_student_id") == booked_student_id]
    records = sort_created_asc(records)
    page, total = paginate(records, limit, offset)
    return array_response(serialize_list(page), limit, offset, total)


@bp.route("/conference-slots/<slot_id>/book", methods=["POST"])
def book(slot_id):
    user_id, role = get_auth()
    require_role(role, {"Parent"})
    body = get_json_body()
    require_fields(body, ["booked_student_id"])
    booked_student_id = body["booked_student_id"]
    if not isinstance(booked_student_id, str):
        raise errors.invalid_request("booked_student_id must be a string.")

    # Path existence (slot) then body FK existence (student).
    slot = _get_slot_or_404(slot_id)
    student = db.students.get(booked_student_id)
    if student is None:
        raise errors.not_found("booked_student_id does not exist.")
    # Ownership (priority 3 semantics): acting parent must own the student.
    if student["parent_user_id"] != user_id:
        raise errors.not_resource_owner()

    # State (priority 5): slot must be OPEN.
    if slot["status"] != "OPEN":
        raise errors.invalid_state()

    # Business: student must have a PLACED enrollment in the slot's classroom.
    has_placed = any(
        e["student_id"] == booked_student_id
        and e["classroom_id"] == slot["classroom_id"]
        and e["placement_status"] == "PLACED"
        for e in db.enrollments.values()
    )
    if not has_placed:
        raise errors.invalid_request(
            "Student has no PLACED enrollment in this classroom."
        )

    # Guide double-booking guard (priority 10): half-open overlap with any other
    # BOOKED slot for the same guide_user_id.
    start_dt = parse_iso(slot["start_at"])
    end_dt = parse_iso(slot["end_at"])
    for other in db.conference_slots.values():
        if other["id"] == slot["id"]:
            continue
        if other["guide_user_id"] != slot["guide_user_id"]:
            continue
        if other["status"] != "BOOKED":
            continue
        if _overlaps_half_open(start_dt, end_dt, parse_iso(other["start_at"]), parse_iso(other["end_at"])):
            raise errors.guide_double_booked()

    slot["status"] = "BOOKED"
    slot["booked_student_id"] = booked_student_id
    touch(slot)
    return object_response(serialize(slot), 200)


@bp.route("/conference-slots/<slot_id>/complete", methods=["POST"])
def complete(slot_id):
    user_id, role = get_auth()
    require_role(role, {"Guide"})
    slot = _get_slot_or_404(slot_id)
    _require_host_guide(user_id, slot)
    if slot["status"] != "BOOKED":
        raise errors.invalid_state()
    slot["status"] = "COMPLETED"
    touch(slot)
    return object_response(serialize(slot), 200)


@bp.route("/conference-slots/<slot_id>/no-show", methods=["POST"])
def no_show(slot_id):
    user_id, role = get_auth()
    require_role(role, {"Guide"})
    slot = _get_slot_or_404(slot_id)
    _require_host_guide(user_id, slot)
    if slot["status"] != "BOOKED":
        raise errors.invalid_state()
    # Temporal precondition: clock must have reached/passed end_at.
    if db.clock_now() < parse_iso(slot["end_at"]):
        raise errors.invalid_state()
    slot["status"] = "NO_SHOW"
    touch(slot)
    return object_response(serialize(slot), 200)


@bp.route("/conference-slots/<slot_id>/cancel", methods=["POST"])
def cancel(slot_id):
    user_id, role = get_auth()
    require_role(role, {"Guide"})
    slot = _get_slot_or_404(slot_id)
    _require_host_guide(user_id, slot)
    if slot["status"] not in ("OPEN", "BOOKED"):
        raise errors.invalid_state()
    slot["status"] = "CANCELLED"
    slot["booked_student_id"] = None
    touch(slot)
    return object_response(serialize(slot), 200)


def _require_host_guide(user_id, slot):
    """Complete/no-show/cancel require acting Guide's X-User-ID == guide_user_id.

    A non-host guide is forbidden from acting on the slot (PRD §2.1, §3.12).
    """
    if slot["guide_user_id"] != user_id:
        raise errors.forbidden_role()
