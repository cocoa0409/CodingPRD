"""Fitness classes, registrations, waitlist promotion, instructor payroll."""

from flask import Blueprint, g, request

import errors as E
from domain import (class_out, registration_out, get_or_404, eligibility_gate,
                    check_booking_fit, instructor_estimate_pay, instructor_final_pay,
                    promote_waitlist_head, overlaps, CLASS_TYPES)
from store import DB
from util import (body_json, req_str, req_int, req_enum, req_dt, envelope_object,
                  list_response, require_role, stamp_new, touch, now)

bp = Blueprint("fitness", __name__)


@bp.route("/v1/fitness-classes", methods=["POST"])
def create_class():
    require_role("RecAdmin")
    body = body_json()
    instructor_id = req_str(body, "instructor_staff_id")
    facility_id = req_str(body, "facility_id")
    instructor = get_or_404(DB.staff, instructor_id)
    facility = get_or_404(DB.facilities, facility_id)
    title = req_str(body, "title")
    class_type = req_enum(body, "class_type", CLASS_TYPES)
    capacity = req_int(body, "capacity")
    if capacity < 1:
        raise E.err_validation("capacity must be >= 1")
    start_at = req_dt(body, "start_at")
    end_at = req_dt(body, "end_at")
    if end_at <= start_at:
        raise E.err_validation("end_at must be strictly after start_at")
    if start_at.date() != end_at.date():
        raise E.err_validation("start_at and end_at must fall on the same local date")
    # Temporal checks (priority 9) run before instructor constraints (priority 10).
    if start_at < now():
        raise E.err_game_in_past()
    check_booking_fit(facility, start_at, end_at)
    if instructor["staff_role"] != "INSTRUCTOR":
        raise E.err_staff_not_instructor()
    if class_type not in (instructor["certified_class_types"] or []):
        raise E.err_instructor_not_certified()
    duration = int((end_at - start_at).total_seconds() // 60)
    fitness_class = stamp_new({
        "title": title,
        "class_type": class_type,
        "instructor_staff_id": instructor_id,
        "facility_id": facility_id,
        "start_at": start_at,
        "end_at": end_at,
        "duration_minutes": duration,
        "capacity": capacity,
        "registered_count": 0,
        "waitlist_count": 0,
        "status": "SCHEDULED",
        "attendance_count": None,
        "instructor_pay_estimate_cents": instructor_estimate_pay(duration, instructor),
        "instructor_pay_cents": None,
    })
    DB.fitness_classes[fitness_class["id"]] = fitness_class
    return envelope_object(class_out(fitness_class), 201)


@bp.route("/v1/fitness-classes/<fitness_class_id>", methods=["GET"])
def get_class(fitness_class_id):
    require_role("RecAdmin", "LeagueCoordinator", "FacilityManager", "Member", "Staff")
    fitness_class = get_or_404(DB.fitness_classes, fitness_class_id)
    return envelope_object(class_out(fitness_class))


@bp.route("/v1/fitness-classes", methods=["GET"])
def list_classes():
    require_role("RecAdmin", "LeagueCoordinator", "FacilityManager", "Member", "Staff")
    instructor = request.args.get("instructor_staff_id")
    facility_id = request.args.get("facility_id")
    status = request.args.get("status")
    class_type = request.args.get("class_type")
    records = [c for c in DB.fitness_classes.values()
               if (instructor is None or c["instructor_staff_id"] == instructor)
               and (facility_id is None or c["facility_id"] == facility_id)
               and (status is None or c["status"] == status)
               and (class_type is None or c["class_type"] == class_type)]
    return list_response(records, class_out)


@bp.route("/v1/fitness-classes/<fitness_class_id>/registrations", methods=["POST"])
def register_for_class(fitness_class_id):
    require_role("Member")
    fitness_class = get_or_404(DB.fitness_classes, fitness_class_id)
    body = body_json()
    if body.get("member_id") is not None and body["member_id"] != g.user_id:
        raise E.err_forbidden("Members may only register themselves")
    member_id = req_str(body, "member_id")
    if member_id != g.user_id:
        raise E.err_forbidden("Members may only register themselves")
    member = get_or_404(DB.members, member_id)
    if fitness_class["status"] != "SCHEDULED":
        raise E.err_invalid_state("Only a SCHEDULED class accepts registrations")
    eligibility_gate(member)
    # Temporal: no overlapping REGISTERED registration in another SCHEDULED class.
    for reg in DB.registrations.values():
        if reg["member_id"] != member_id or reg["status"] != "REGISTERED":
            continue
        if reg["fitness_class_id"] == fitness_class_id:
            continue
        other = DB.fitness_classes.get(reg["fitness_class_id"])
        if other is None or other["status"] != "SCHEDULED":
            continue
        if overlaps(fitness_class["start_at"], fitness_class["end_at"],
                    other["start_at"], other["end_at"]):
            raise E.err_class_time_conflict()
    for reg in DB.registrations.values():
        if reg["member_id"] == member_id and reg["fitness_class_id"] == fitness_class_id \
           and reg["status"] in ("REGISTERED", "WAITLISTED"):
            raise E.err_class_already_registered()
    # A full class is NOT an error: it produces a WAITLISTED registration.
    if fitness_class["registered_count"] < fitness_class["capacity"]:
        status = "REGISTERED"
        fitness_class["registered_count"] += 1
    else:
        status = "WAITLISTED"
        fitness_class["waitlist_count"] += 1
    registration = stamp_new({
        "fitness_class_id": fitness_class_id,
        "member_id": member_id,
        "status": status,
    })
    DB.registrations[registration["id"]] = registration
    touch(fitness_class)
    return envelope_object(registration_out(registration), 201)


@bp.route("/v1/class-registrations/<class_registration_id>", methods=["GET"])
def get_registration(class_registration_id):
    require_role("RecAdmin", "LeagueCoordinator", "FacilityManager", "Member", "Staff")
    registration = get_or_404(DB.registrations, class_registration_id)
    return envelope_object(registration_out(registration))


@bp.route("/v1/class-registrations", methods=["GET"])
def list_registrations():
    require_role("RecAdmin", "LeagueCoordinator", "FacilityManager", "Member", "Staff")
    class_id = request.args.get("fitness_class_id")
    member_id = request.args.get("member_id")
    status = request.args.get("status")
    records = [r for r in DB.registrations.values()
               if (class_id is None or r["fitness_class_id"] == class_id)
               and (member_id is None or r["member_id"] == member_id)
               and (status is None or r["status"] == status)]
    return list_response(records, registration_out)


@bp.route("/v1/class-registrations/<class_registration_id>/cancel", methods=["POST"])
def cancel_registration(class_registration_id):
    require_role("Member", "RecAdmin")
    registration = get_or_404(DB.registrations, class_registration_id)
    if g.role == "Member" and registration["member_id"] != g.user_id:
        raise E.err_forbidden("Members may only cancel their own registrations")
    if registration["status"] not in ("REGISTERED", "WAITLISTED"):
        raise E.err_invalid_state("Only a REGISTERED or WAITLISTED registration can be cancelled")
    was = registration["status"]
    registration["status"] = "CANCELLED"
    touch(registration)
    fitness_class = DB.fitness_classes.get(registration["fitness_class_id"])
    if fitness_class is not None:
        if was == "REGISTERED":
            fitness_class["registered_count"] -= 1
            touch(fitness_class)
            # Seat handoff: promotion re-increments registered_count when a
            # waitlist head exists (conservation invariant).
            promote_waitlist_head(fitness_class)
        else:
            fitness_class["waitlist_count"] -= 1
            touch(fitness_class)
    return envelope_object(registration_out(registration))


@bp.route("/v1/fitness-classes/<fitness_class_id>/complete", methods=["POST"])
def complete_class(fitness_class_id):
    require_role("Staff", "RecAdmin")
    fitness_class = get_or_404(DB.fitness_classes, fitness_class_id)
    if g.role == "Staff" and fitness_class["instructor_staff_id"] != g.user_id:
        raise E.err_forbidden("Only the class instructor may complete the class")
    body = body_json()
    no_show_ids = body.get("no_show_registration_ids")
    if no_show_ids is not None and not isinstance(no_show_ids, list):
        raise E.err_validation("no_show_registration_ids must be an array")
    no_show_ids = set(no_show_ids or [])
    if fitness_class["status"] != "SCHEDULED":
        raise E.err_invalid_state("Only a SCHEDULED class can be completed")
    if now() < fitness_class["end_at"]:
        raise E.err_invalid_state("Class cannot be completed before its end time")
    attendance = 0
    for reg in sorted(DB.registrations.values(), key=lambda r: r["_seq"]):
        if reg["fitness_class_id"] != fitness_class_id:
            continue
        if reg["status"] == "REGISTERED":
            if reg["id"] in no_show_ids:
                reg["status"] = "NO_SHOW"
                member = DB.members.get(reg["member_id"])
                if member is not None:
                    member["no_show_count"] += 1
                    touch(member)
            else:
                reg["status"] = "ATTENDED"
                attendance += 1
            touch(reg)
        elif reg["status"] == "WAITLISTED":
            reg["status"] = "CANCELLED"
            touch(reg)
    instructor = DB.staff.get(fitness_class["instructor_staff_id"])
    pay = instructor_final_pay(fitness_class["duration_minutes"], instructor,
                               attendance, fitness_class["capacity"])
    fitness_class["status"] = "COMPLETED"
    fitness_class["attendance_count"] = attendance
    fitness_class["instructor_pay_cents"] = pay
    touch(fitness_class)
    # Instructor rail pays directly to paid, never through pending.
    instructor["payroll_paid_cents"] += pay
    touch(instructor)
    return envelope_object(class_out(fitness_class))
