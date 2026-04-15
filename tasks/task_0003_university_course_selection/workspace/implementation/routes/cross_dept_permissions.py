"""Cross-department permission endpoints."""
from flask import Blueprint, request as req
import db
from db import new_id, now_iso
from middleware import require_roles
from response import success_single, success_list
from errors import raise_error, CROSS_DEPT_PERMISSION_UNKNOWN, CROSS_DEPT_REVOKE_BLOCKED, \
    ENROLLMENT_STATE_INVALID
from pagination import parse_page_params, paginate
from routes.semesters import get_semester_or_404
from services.enrollment_service import recompute_student_credits, compute_cross_dept_usage, \
    recompute_waitlist_positions, recompute_section_counts

bp = Blueprint("cross_dept_permissions", __name__)


def get_permission_or_404(semester_id, permission_id):
    perm = db.cross_dept_permissions.get(permission_id)
    if not perm or perm.get("semester_id") != semester_id:
        raise_error(CROSS_DEPT_PERMISSION_UNKNOWN,
                    f"CrossDeptPermission {permission_id} not found")
    return perm


def permission_response(perm):
    return {
        "id": perm["id"],
        "semester_id": perm["semester_id"],
        "student_id": perm["student_id"],
        "target_department_id": perm["target_department_id"],
        "granted_by": perm["granted_by"],
        "max_courses": perm.get("max_courses", 2),
        "courses_used": perm.get("courses_used", 0),
        "status": perm["status"],
        "opened_on": perm["opened_on"],
        "modified_on": perm["modified_on"],
        "enrollment_seq": perm.get("enrollment_seq", 1),
    }


@bp.route("/semesters/<semester_id>/cross-dept-permissions", methods=["POST"])
def create_permission(semester_id):
    caller_id, role = require_roles("Registrar", "Professor")
    get_semester_or_404(semester_id)
    data = req.get_json(force=True)
    now = now_iso()
    perm = {
        "id": new_id(),
        "semester_id": semester_id,
        "student_id": data.get("student_id"),
        "target_department_id": data.get("target_department_id"),
        "granted_by": caller_id,
        "max_courses": data.get("max_courses", 2),
        "courses_used": 0,
        "status": "ACTIVE",
        "opened_on": now,
        "modified_on": now,
        "enrollment_seq": 1,
    }
    db.cross_dept_permissions[perm["id"]] = perm
    return success_single(permission_response(perm), 201)


@bp.route("/semesters/<semester_id>/cross-dept-permissions", methods=["GET"])
def list_permissions(semester_id):
    require_roles("Any")
    get_semester_or_404(semester_id)
    page_size, offset = parse_page_params()
    items = [p for p in db.cross_dept_permissions.values() if p.get("semester_id") == semester_id]

    # Optional filters
    student_filter = req.args.get("student_id")
    dept_filter = req.args.get("target_department_id")
    if student_filter:
        items = [p for p in items if p["student_id"] == student_filter]
    if dept_filter:
        items = [p for p in items if p["target_department_id"] == dept_filter]

    items.sort(key=lambda p: p["opened_on"])
    items = [permission_response(p) for p in items]
    page_items, total, next_token = paginate(items, page_size, offset)
    return success_list(page_items, page_size, offset, total, next_token)


@bp.route("/semesters/<semester_id>/cross-dept-permissions/<permission_id>", methods=["GET"])
def get_permission(semester_id, permission_id):
    require_roles("Any")
    get_semester_or_404(semester_id)
    perm = get_permission_or_404(semester_id, permission_id)
    return success_single(permission_response(perm))


@bp.route("/semesters/<semester_id>/cross-dept-permissions/<permission_id>/revoke", methods=["POST"])
def revoke_permission(semester_id, permission_id):
    require_roles("Registrar", "Professor")
    get_semester_or_404(semester_id)
    perm = get_permission_or_404(semester_id, permission_id)

    if perm["status"] != "ACTIVE":
        raise_error(ENROLLMENT_STATE_INVALID, "Permission is not in ACTIVE status")

    student_id = perm["student_id"]
    dept_id = perm["target_department_id"]

    # Check for ENROLLED enrollments depending on this permission
    for enr in db.enrollments.values():
        if enr["student_id"] == student_id and enr["status"] == "ENROLLED" and enr.get("is_cross_dept"):
            section = db.sections.get(enr["section_id"])
            if section:
                course = db.courses.get(section["course_id"])
                if course and course["department_id"] == dept_id:
                    raise_error(CROSS_DEPT_REVOKE_BLOCKED,
                                "Cannot revoke: student has ENROLLED enrollments depending on this permission")

    now = now_iso()
    perm["status"] = "REVOKED"
    perm["modified_on"] = now

    # Auto-drop WAITLISTED and PENDING_APPROVAL enrollments in that department
    for enr in list(db.enrollments.values()):
        if (enr["student_id"] == student_id and
                enr["status"] in ("WAITLISTED", "PENDING_APPROVAL") and
                enr.get("is_cross_dept")):
            section = db.sections.get(enr["section_id"])
            if section:
                course = db.courses.get(section["course_id"])
                if course and course["department_id"] == dept_id:
                    old_status = enr["status"]
                    enr["status"] = "DROPPED"
                    enr["dropped_on"] = now
                    enr["modified_on"] = now

                    if old_status == "WAITLISTED":
                        section["waitlist_count"] = max(0, section.get("waitlist_count", 0) - 1)
                        section["modified_on"] = now
                        recompute_waitlist_positions(section["id"])
                    elif old_status == "PENDING_APPROVAL":
                        recompute_student_credits(student_id)

    # Recompute usage (should be 0 for non-enrolled now)
    perm["courses_used"] = compute_cross_dept_usage(student_id, dept_id)

    return success_single(permission_response(perm))
