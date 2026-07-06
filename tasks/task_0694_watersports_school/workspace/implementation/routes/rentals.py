"""RentalAgreement routes (create/checkout/return/cancel) and CertificationCard reads."""
from datetime import timedelta

from flask import Blueprint, request

import db
from clock import clock
from errors import (
    err, ERR_NOT_FOUND, ERR_VALIDATION, ERR_INVALID_STATE, ERR_NOT_RESOURCE_OWNER,
    ERR_STALE_VERSION, ERR_EQUIPMENT_UNAVAILABLE, ERR_EQUIPMENT_TYPE_MISMATCH,
    ERR_EQUIPMENT_IN_MAINTENANCE,
)
from middleware import get_identity, require_role
from response import success, success_list
from services import derive, calc
from util import (
    parse_dt, require_str, parse_pagination, paginate, touch,
)

bp = Blueprint("rentals", __name__)
READ_ROLES = {"SchoolAdmin", "Instructor", "Student"}
NON_TERMINAL_RENTAL = {"RESERVED", "ACTIVE"}


def _body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise err(ERR_VALIDATION, "request body must be a JSON object")
    return data


@bp.route("/rentals", methods=["POST"])
def create_rental():
    user_id, role = get_identity()
    require_role(role, {"SchoolAdmin", "Student"})
    body = _body()
    school_id = require_str(body, "school_id")
    student_id = require_str(body, "student_id")
    equipment_item_id = require_str(body, "equipment_item_id")
    for f in ("starts_at", "ends_at"):
        if f not in body or body[f] is None:
            raise err(ERR_VALIDATION, f"missing required field: {f}")
    starts_at = parse_dt(body["starts_at"], "starts_at")
    ends_at = parse_dt(body["ends_at"], "ends_at")
    if ends_at <= starts_at:
        raise err(ERR_VALIDATION, "ends_at must be after starts_at")
    if "expected_equipment_version" not in body or body["expected_equipment_version"] is None:
        raise err(ERR_VALIDATION, "missing required field: expected_equipment_version")
    expected = body["expected_equipment_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err(ERR_VALIDATION, "expected_equipment_version must be an integer")
    session_id = body.get("session_id")
    if session_id is not None and not isinstance(session_id, str):
        raise err(ERR_VALIDATION, "session_id must be a string or null")

    with db.lock():
        # FK existence (priority 4).
        if school_id not in db.schools:
            raise err(ERR_NOT_FOUND, "school not found")
        student = db.students.get(student_id)
        if student is None or student["school_id"] != school_id:
            raise err(ERR_NOT_FOUND, "student not found")
        item = db.equipment.get(equipment_item_id)
        if item is None or item["school_id"] != school_id:
            raise err(ERR_NOT_FOUND, "equipment not found")
        session = None
        if session_id is not None:
            session = db.sessions.get(session_id)
            if session is None or session["school_id"] != school_id:
                raise err(ERR_NOT_FOUND, "session not found")

        # Ownership scoping for Student (priority 5).
        if role == "Student" and user_id != student_id:
            raise err(ERR_NOT_RESOURCE_OWNER, "not the owning student")

        # OCC (priority 6).
        if expected != item["version"]:
            raise err(ERR_STALE_VERSION, "equipment version mismatch")

        # Equipment overlap (priority 16): each existing non-terminal agreement on
        # the same item reserves [starts_at, ends_at + 1h] CLOSED-with-buffer.
        for other in db.rentals.values():
            if other["equipment_item_id"] != equipment_item_id:
                continue
            if other["status"] not in NON_TERMINAL_RENTAL:
                continue
            os = parse_dt(other["starts_at"], "starts_at")
            oe = parse_dt(other["ends_at"], "ends_at") + timedelta(hours=1)
            # closed interval [os, oe]; new [starts_at, ends_at). Collision iff
            # starts_at <= oe and os <= ends_at (touching the buffered close counts).
            if starts_at <= oe and os <= ends_at:
                raise err(ERR_EQUIPMENT_UNAVAILABLE, "equipment unavailable for window")

        # Type match when session_id supplied (priority 17).
        if session is not None:
            level = db.levels.get(session["course_level_id"])
            req_type = level["required_equipment_type"] if level else None
            if item["equipment_type"] != req_type:
                raise err(ERR_EQUIPMENT_TYPE_MISMATCH, "equipment type mismatch")

        hours = calc.ceil_hours(starts_at, ends_at)
        fee = calc.rental_fee(hours, item["hourly_rate_cents"])
        now = db.now_iso()
        rid = db.new_id()
        rec = {
            "id": rid, "school_id": school_id, "student_id": student_id,
            "equipment_item_id": equipment_item_id, "session_id": session_id,
            "starts_at": body["starts_at"], "ends_at": body["ends_at"],
            "rental_fee_cents": fee, "deposit_held_cents": item["deposit_cents"],
            "status": "RESERVED",
            "created_at": now, "updated_at": now, "version": 1,
            "_seq": db.next_seq(),
        }
        db.rentals[rid] = rec
        # Creating a rental bumps EquipmentItem.version (PRD §3.9).
        touch(item)
        return success(derive.serialize_rental(rec), 201)


@bp.route("/rentals", methods=["GET"])
def list_rentals():
    _, role = get_identity()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination(request.args)
    school_id = request.args.get("school_id")
    student_id = request.args.get("student_id")
    equipment_item_id = request.args.get("equipment_item_id")
    session_id = request.args.get("session_id")
    rows = [
        r for r in db.rentals.values()
        if (school_id is None or r["school_id"] == school_id)
        and (student_id is None or r["student_id"] == student_id)
        and (equipment_item_id is None or r["equipment_item_id"] == equipment_item_id)
        and (session_id is None or r["session_id"] == session_id)
    ]
    page, total = paginate(rows, limit, offset)
    return success_list([derive.serialize_rental(r) for r in page], limit, offset, total)


@bp.route("/rentals/<rid>", methods=["GET"])
def get_rental(rid):
    _, role = get_identity()
    require_role(role, READ_ROLES)
    rec = db.rentals.get(rid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "rental not found")
    return success(derive.serialize_rental(rec), 200)


def _check_owner(role, user_id, rec):
    if role == "Student" and user_id != rec["student_id"]:
        raise err(ERR_NOT_RESOURCE_OWNER, "not the owning student")


@bp.route("/rentals/<rid>/checkout", methods=["POST"])
def checkout_rental(rid):
    user_id, role = get_identity()
    require_role(role, {"SchoolAdmin", "Student"})
    with db.lock():
        rec = db.rentals.get(rid)
        if rec is None:
            raise err(ERR_NOT_FOUND, "rental not found")
        _check_owner(role, user_id, rec)
        if rec["status"] != "RESERVED":
            raise err(ERR_INVALID_STATE, "rental is not RESERVED")
        item = db.equipment.get(rec["equipment_item_id"])
        # Maintenance block (priority 20).
        if item is not None and derive.equipment_status(item) == "MAINTENANCE":
            raise err(ERR_EQUIPMENT_IN_MAINTENANCE, "equipment in maintenance")
        # clock must be >= starts_at.
        now = clock.get()
        starts = parse_dt(rec["starts_at"], "starts_at")
        if now < starts:
            raise err(ERR_INVALID_STATE, "rental window has not started")
        rec["status"] = "ACTIVE"
        touch(rec)
        # EquipmentItem -> RENTED (derived from ACTIVE rental); bump its version.
        if item is not None:
            touch(item)
        return success(derive.serialize_rental(rec), 200)


@bp.route("/rentals/<rid>/return", methods=["POST"])
def return_rental(rid):
    user_id, role = get_identity()
    require_role(role, {"SchoolAdmin", "Student"})
    with db.lock():
        rec = db.rentals.get(rid)
        if rec is None:
            raise err(ERR_NOT_FOUND, "rental not found")
        _check_owner(role, user_id, rec)
        if rec["status"] != "ACTIVE":
            raise err(ERR_INVALID_STATE, "rental is not ACTIVE")
        rec["status"] = "RETURNED"
        touch(rec)
        # EquipmentItem -> AVAILABLE; bump version (deposit released to student).
        item = db.equipment.get(rec["equipment_item_id"])
        if item is not None:
            touch(item)
        return success(derive.serialize_rental(rec), 200)


@bp.route("/rentals/<rid>/cancel", methods=["POST"])
def cancel_rental(rid):
    user_id, role = get_identity()
    require_role(role, {"SchoolAdmin", "Student"})
    with db.lock():
        rec = db.rentals.get(rid)
        if rec is None:
            raise err(ERR_NOT_FOUND, "rental not found")
        _check_owner(role, user_id, rec)
        if rec["status"] not in ("RESERVED", "ACTIVE"):
            raise err(ERR_INVALID_STATE, "rental not in RESERVED or ACTIVE")
        was_active = rec["status"] == "ACTIVE"
        rec["status"] = "CANCELLED"
        touch(rec)
        # If was ACTIVE: EquipmentItem -> AVAILABLE, bump version. Deposit released.
        if was_active:
            item = db.equipment.get(rec["equipment_item_id"])
            if item is not None:
                touch(item)
        return success(derive.serialize_rental(rec), 200)


# ------------------------- CertificationCard ----------------------
@bp.route("/certification-cards", methods=["GET"])
def list_cards():
    _, role = get_identity()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination(request.args)
    student_id = request.args.get("student_id")
    enrollment_id = request.args.get("enrollment_id")
    course_level_id = request.args.get("course_level_id")
    rows = [
        c for c in db.certification_cards.values()
        if (student_id is None or c["student_id"] == student_id)
        and (enrollment_id is None or c["enrollment_id"] == enrollment_id)
        and (course_level_id is None or c["course_level_id"] == course_level_id)
    ]
    page, total = paginate(rows, limit, offset)
    return success_list([derive.serialize_card(r) for r in page], limit, offset, total)


@bp.route("/certification-cards/<cid>", methods=["GET"])
def get_card(cid):
    _, role = get_identity()
    require_role(role, READ_ROLES)
    rec = db.certification_cards.get(cid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "certification card not found")
    return success(derive.serialize_card(rec), 200)
