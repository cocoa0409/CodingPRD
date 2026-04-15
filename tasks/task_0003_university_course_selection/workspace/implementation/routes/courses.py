"""Course endpoints including prerequisite graph."""
from flask import Blueprint, request as req
import db
from db import new_id, now_iso
from middleware import require_roles
from response import success_single, success_list
from errors import raise_error, COURSE_UNKNOWN, PREREQUISITE_CYCLE_DETECTED
from pagination import parse_page_params, paginate
from routes.semesters import get_semester_or_404
from routes.departments import get_department_or_404
from services.prerequisite import compute_prerequisite_graph, check_cycle_on_update

bp = Blueprint("courses", __name__)


def get_course_or_404(semester_id, department_id, course_id):
    course = db.courses.get(course_id)
    if not course or course["department_id"] != department_id:
        raise_error(COURSE_UNKNOWN, f"Course {course_id} not found in department {department_id}")
    return course


def course_response(course):
    return {
        "id": course["id"],
        "department_id": course["department_id"],
        "course_code": course["course_code"],
        "title": course["title"],
        "credit_hours": course["credit_hours"],
        "level": course["level"],
        "min_gpa": course.get("min_gpa", 0.0),
        "prerequisite_ids": course.get("prerequisite_ids", []),
        "corequisite_ids": course.get("corequisite_ids", []),
        "is_active": course.get("is_active", True),
        "opened_on": course["opened_on"],
        "modified_on": course["modified_on"],
        "enrollment_seq": course.get("enrollment_seq", 1),
    }


@bp.route("/semesters/<semester_id>/departments/<department_id>/courses", methods=["POST"])
def create_course(semester_id, department_id):
    require_roles("Registrar", "Professor")
    get_semester_or_404(semester_id)
    get_department_or_404(semester_id, department_id)
    data = req.get_json(force=True)

    now = now_iso()
    course_id = new_id()

    prerequisite_ids = data.get("prerequisite_ids", [])
    corequisite_ids = data.get("corequisite_ids", [])

    # Check for prerequisite cycle
    if prerequisite_ids:
        # Temporarily create the course to check cycle
        temp_course = {"id": course_id, "prerequisite_ids": prerequisite_ids}
        db.courses[course_id] = temp_course
        has_cycle = check_cycle_on_update(course_id, prerequisite_ids)
        if has_cycle:
            del db.courses[course_id]
            raise_error(PREREQUISITE_CYCLE_DETECTED,
                        "Adding these prerequisites would create a cycle in the dependency graph")
        del db.courses[course_id]

    course = {
        "id": course_id,
        "department_id": department_id,
        "course_code": data.get("course_code"),
        "title": data.get("title"),
        "credit_hours": data.get("credit_hours"),
        "level": data.get("level"),
        "min_gpa": data.get("min_gpa", 0.0),
        "prerequisite_ids": prerequisite_ids,
        "corequisite_ids": corequisite_ids,
        "is_active": True,
        "opened_on": now,
        "modified_on": now,
        "enrollment_seq": 1,
    }
    db.courses[course_id] = course
    return success_single(course_response(course), 201)


@bp.route("/semesters/<semester_id>/departments/<department_id>/courses", methods=["GET"])
def list_courses(semester_id, department_id):
    require_roles("Any")
    get_semester_or_404(semester_id)
    get_department_or_404(semester_id, department_id)
    page_size, offset = parse_page_params()

    items = [c for c in db.courses.values() if c["department_id"] == department_id]

    # Optional level filter
    level_filter = req.args.get("level")
    if level_filter:
        items = [c for c in items if c.get("level") == level_filter]

    items.sort(key=lambda c: c["opened_on"])
    items = [course_response(c) for c in items]
    page_items, total, next_token = paginate(items, page_size, offset)
    return success_list(page_items, page_size, offset, total, next_token)


@bp.route("/semesters/<semester_id>/departments/<department_id>/courses/<course_id>", methods=["GET"])
def get_course(semester_id, department_id, course_id):
    require_roles("Any")
    get_semester_or_404(semester_id)
    get_department_or_404(semester_id, department_id)
    course = get_course_or_404(semester_id, department_id, course_id)
    return success_single(course_response(course))


@bp.route("/semesters/<semester_id>/departments/<department_id>/courses/<course_id>", methods=["PATCH"])
def update_course(semester_id, department_id, course_id):
    require_roles("Registrar")
    get_semester_or_404(semester_id)
    get_department_or_404(semester_id, department_id)
    course = get_course_or_404(semester_id, department_id, course_id)
    data = req.get_json(force=True)

    if "prerequisite_ids" in data:
        new_prereqs = data["prerequisite_ids"]
        if check_cycle_on_update(course_id, new_prereqs):
            raise_error(PREREQUISITE_CYCLE_DETECTED,
                        "Updating prerequisites would create a cycle")
        course["prerequisite_ids"] = new_prereqs

    if "corequisite_ids" in data:
        course["corequisite_ids"] = data["corequisite_ids"]
    if "min_gpa" in data:
        course["min_gpa"] = data["min_gpa"]
    if "is_active" in data:
        course["is_active"] = data["is_active"]

    course["modified_on"] = now_iso()
    return success_single(course_response(course))


@bp.route("/semesters/<semester_id>/departments/<department_id>/courses/<course_id>/prerequisite-graph", methods=["GET"])
def get_prerequisite_graph(semester_id, department_id, course_id):
    require_roles("Any")
    get_semester_or_404(semester_id)
    get_department_or_404(semester_id, department_id)
    get_course_or_404(semester_id, department_id, course_id)

    graph = compute_prerequisite_graph(course_id)
    return success_single(graph)
