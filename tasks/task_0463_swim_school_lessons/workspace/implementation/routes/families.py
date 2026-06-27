"""Parent + Student routes. PRD 3.2."""
from flask import Blueprint, request

from db import store, iso, common_fields_on_create, touch
from errors import err, ERR_INVALID_REQUEST, ERR_NOT_RESOURCE_OWNER
from helpers import (
    get_body, require_str, require_datetime, parse_pagination, paginate,
)
from middleware import get_principal, require_roles
from response import object_response, array_response
from domain import (
    serialize_parent, serialize_student, withdraw_enrollment,
)
from lookups import get_parent, get_student, get_level

bp = Blueprint("families", __name__)


# ---------------------------------------------------------------------------
# Parent — PRD 3.2
# ---------------------------------------------------------------------------
@bp.route("/parents", methods=["POST"])
def create_parent():
    principal = get_principal()
    require_roles(principal, ["SchoolAdmin"])
    body = get_body()
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    # email unique without regard to letter case (PRD 3.2).
    lowered = email.lower()
    for p in store.parents.values():
        if p["email"].lower() == lowered:
            err(ERR_INVALID_REQUEST, "email must be unique")
    rec = common_fields_on_create()
    rec.update({
        "full_name": full_name,
        "email": email,
        "account_standing": "CURRENT",
        "outstanding_balance_cents": 0,
    })
    store.parents[rec["id"]] = rec
    return object_response(serialize_parent(rec), 201)


@bp.route("/parents", methods=["GET"])
def list_parents():
    principal = get_principal()
    require_roles(principal, ["SchoolAdmin", "BillingAdmin"])
    limit, offset = parse_pagination()
    window, total = paginate(list(store.parents.values()), limit, offset)
    return array_response([serialize_parent(r) for r in window], limit, offset, total)


@bp.route("/parents/<id>", methods=["GET"])
def get_parent_route(id):
    principal = get_principal()
    require_roles(principal, ["SchoolAdmin", "BillingAdmin", "Parent"])
    rec = get_parent(id)
    # PRD 2.1: a Parent may read only their own account.
    if principal.role == "Parent" and principal.user_id != rec["id"]:
        err(ERR_NOT_RESOURCE_OWNER, "Parent may only view its own account")
    return object_response(serialize_parent(rec), 200)


# ---------------------------------------------------------------------------
# Student — PRD 3.2
# ---------------------------------------------------------------------------
@bp.route("/parents/<id>/students", methods=["POST"])
def add_student(id):
    principal = get_principal()
    require_roles(principal, ["SchoolAdmin", "Parent"])
    parent = get_parent(id)
    # Ownership: a Parent acts only on their own account (PRD 2.1).
    if principal.role == "Parent" and principal.user_id != parent["id"]:
        err(ERR_NOT_RESOURCE_OWNER, "Parent may only add students to its own account")
    body = get_body()
    full_name = require_str(body, "full_name")
    birthdate = require_datetime(body, "birthdate")
    current_level_id = require_str(body, "current_level_id")
    get_level(current_level_id)  # existence of current_level_id (404 if missing)
    rec = common_fields_on_create()
    rec.update({
        "parent_id": parent["id"],
        "full_name": full_name,
        "birthdate": iso(birthdate),
        "current_level_id": current_level_id,
        "status": "ACTIVE",
    })
    store.students[rec["id"]] = rec
    return object_response(serialize_student(rec), 201)


@bp.route("/parents/<id>/students", methods=["GET"])
def list_parent_students(id):
    principal = get_principal()
    require_roles(principal, ["SchoolAdmin", "BillingAdmin", "Parent"])
    parent = get_parent(id)
    if principal.role == "Parent" and principal.user_id != parent["id"]:
        err(ERR_NOT_RESOURCE_OWNER, "Parent may only list its own students")
    limit, offset = parse_pagination()
    records = [s for s in store.students.values() if s["parent_id"] == parent["id"]]
    window, total = paginate(records, limit, offset)
    return array_response([serialize_student(r) for r in window], limit, offset, total)


@bp.route("/students", methods=["GET"])
def list_students():
    principal = get_principal()
    require_roles(principal, ["SchoolAdmin", "BillingAdmin"])
    limit, offset = parse_pagination()
    records = list(store.students.values())
    current_level_id = request.args.get("current_level_id")
    if current_level_id is not None:
        records = [s for s in records if s["current_level_id"] == current_level_id]
    window, total = paginate(records, limit, offset)
    return array_response([serialize_student(r) for r in window], limit, offset, total)


@bp.route("/students/<id>", methods=["GET"])
def get_student_route(id):
    principal = get_principal()
    require_roles(principal, ["SchoolAdmin", "BillingAdmin", "Instructor", "Parent"])
    rec = get_student(id)
    # Parent may read only their own student (PRD 2.1).
    if principal.role == "Parent" and principal.user_id != rec["parent_id"]:
        err(ERR_NOT_RESOURCE_OWNER, "Parent may only view its own student")
    return object_response(serialize_student(rec), 200)


@bp.route("/students/<id>/withdraw", methods=["POST"])
def withdraw_student(id):
    principal = get_principal()
    require_roles(principal, ["SchoolAdmin", "Parent"])
    student = get_student(id)
    # PRD 3.2: ownership enforced first for a Parent withdrawing a child.
    if principal.role == "Parent" and principal.user_id != student["parent_id"]:
        err(ERR_NOT_RESOURCE_OWNER, "Parent may only withdraw its own student")
    # State legality: a WITHDRAWN student cannot be withdrawn again.
    from errors import ERR_INVALID_STATE
    if student["status"] != "ACTIVE":
        err(ERR_INVALID_STATE, "Student is not ACTIVE")

    student["status"] = "WITHDRAWN"
    touch(student)
    # CASCADE L1->L2->L3: every enrollment of this student in ACTIVE/PAUSED/WAITLISTED
    # -> WITHDRAWN; each ACTIVE withdrawal frees a seat -> promotes earliest waitlisted.
    affected = [e for e in store.enrollments.values()
                if e["student_id"] == student["id"]
                and e["status"] in ("ACTIVE", "PAUSED", "WAITLISTED")]
    # Deterministic order: by created_at then id.
    affected.sort(key=lambda e: (e["created_at"], e["id"]))
    for enrollment in affected:
        withdraw_enrollment(enrollment)
    return object_response(serialize_student(student), 200)
