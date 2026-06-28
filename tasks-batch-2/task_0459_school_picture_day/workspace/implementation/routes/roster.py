"""Student (roster) and PackageItem (catalog) routes."""
from flask import Blueprint, request

import db
import store
from common import (
    get_body,
    paginate,
    parse_pagination,
    require_enum,
    require_fields,
    require_int,
    require_str,
    optional_bool,
    sort_by_creation,
)
from errors import err
from middleware import get_user_context, require_role
from response import array_response, object_response

bp = Blueprint("roster", __name__)

ALL_OPERATORS = ["SchoolCoordinator", "StudioPhotographer", "FulfillmentClerk"]


# ---------------------------------------------------------------------------
# Students
# ---------------------------------------------------------------------------
@bp.route("/api/students", methods=["POST"])
def create_student():
    _uid, role = get_user_context()
    require_role(role, ["SchoolCoordinator"])
    body = get_body()
    require_fields(body, ["picture_day_session_id", "full_name", "grade", "homeroom", "guardian_user_id"])
    sid = require_str(body, "picture_day_session_id")
    full_name = require_str(body, "full_name")
    grade = require_str(body, "grade")
    homeroom = require_str(body, "homeroom")
    guardian = require_str(body, "guardian_user_id")

    with db.LOCK:
        session = store.get_session(sid)
        # Roster is immutable once locked (PRD §3.1): no further student create.
        if session["status"] != "DRAFT":
            raise err("ERR_INVALID_SESSION_TRANSITION", "Roster is locked; cannot add students")
        row = store.new_row("student", {
            "picture_day_session_id": sid,
            "guardian_user_id": guardian,
            "full_name": full_name,
            "grade": grade,
            "homeroom": homeroom,
            "status": "ENROLLED",
        })
        db.students[row["id"]] = row
    return object_response(store.serialize(row), 201)


@bp.route("/api/students", methods=["GET"])
def list_students():
    _uid, role = get_user_context()
    require_role(role, ALL_OPERATORS)
    limit, offset = parse_pagination()
    sid = request.args.get("picture_day_session_id")
    status = request.args.get("status")
    rows = list(db.students.values())
    if sid is not None:
        rows = [r for r in rows if r["picture_day_session_id"] == sid]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sort_by_creation(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([store.serialize(r) for r in page], limit, offset, total)


@bp.route("/api/students/<rid>", methods=["GET"])
def get_student(rid):
    uid, role = get_user_context()
    require_role(role, ALL_OPERATORS + ["Guardian"])
    row = store.get_student(rid)
    # Guardian may only read their own student (PRD §2.1).
    if role == "Guardian" and row["guardian_user_id"] != uid:
        raise err("ERR_NOT_OWNER", "Guardian does not own this student")
    return object_response(store.serialize(row))


@bp.route("/api/students/<rid>/mark-absent", methods=["POST"])
def mark_absent(rid):
    _uid, role = get_user_context()
    require_role(role, ["StudioPhotographer"])
    with db.LOCK:
        student = store.get_student(rid)
        session = store.get_session(student["picture_day_session_id"])
        if session["status"] != "CAPTURE_OPEN":
            raise err("ERR_SESSION_NOT_CAPTURING", "Session is not capturing")
        if student["status"] != "ENROLLED":
            raise err("ERR_STUDENT_ALREADY_PHOTOGRAPHED", "Student is not ENROLLED")
        student["status"] = "ABSENT"
        store.touch(student)
    return object_response(store.serialize(student))


# ---------------------------------------------------------------------------
# Packages (catalog)
# ---------------------------------------------------------------------------
@bp.route("/api/packages", methods=["POST"])
def create_package():
    _uid, role = get_user_context()
    require_role(role, ["SchoolCoordinator"])
    body = get_body()
    require_fields(body, ["picture_day_session_id", "sku", "name", "tier", "base_price_cents"])
    sid = require_str(body, "picture_day_session_id")
    sku = require_str(body, "sku")
    name = require_str(body, "name")
    tier = require_enum(body, "tier", {"BASIC", "DELUXE", "PREMIUM"})
    base_price = require_int(body, "base_price_cents")
    if base_price <= 0:
        raise err("ERR_INVALID_REQUEST", "base_price_cents must be > 0")
    active = optional_bool(body, "active", True)

    with db.LOCK:
        store.get_session(sid)
        # SKU unique within the session (PRD §2.7).
        for p in db.packages.values():
            if p["picture_day_session_id"] == sid and p["sku"] == sku:
                raise err("ERR_INVALID_REQUEST", "Duplicate sku within session")
        row = store.new_row("package", {
            "picture_day_session_id": sid,
            "sku": sku,
            "name": name,
            "tier": tier,
            "base_price_cents": base_price,
            "active": active,
        })
        db.packages[row["id"]] = row
    return object_response(store.serialize(row), 201)


@bp.route("/api/packages", methods=["GET"])
def list_packages():
    _uid, role = get_user_context()
    require_role(role, ALL_OPERATORS + ["Guardian"])
    limit, offset = parse_pagination()
    sid = request.args.get("picture_day_session_id")
    active = request.args.get("active")
    rows = list(db.packages.values())
    if sid is not None:
        rows = [r for r in rows if r["picture_day_session_id"] == sid]
    if active is not None:
        want = active.lower() in ("true", "1", "yes")
        rows = [r for r in rows if r["active"] == want]
    rows = sort_by_creation(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([store.serialize(r) for r in page], limit, offset, total)


@bp.route("/api/packages/<rid>", methods=["GET"])
def get_package(rid):
    _uid, role = get_user_context()
    require_role(role, ALL_OPERATORS + ["Guardian"])
    return object_response(store.serialize(store.get_package(rid)))
