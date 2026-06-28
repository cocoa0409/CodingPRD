"""Course catalog endpoints (PRD §3.1)."""
from flask import Blueprint

import db
import response
from errors import err
from middleware import require_auth, get_json_body, parse_pagination, get_identity
from services import serialize, validators
from services.listing import sort_and_page

bp = Blueprint("courses", __name__)

PUBLIC_READ_ROLES = {"Anonymous", "Student", "Instructor", "Registrar"}


@bp.post("/courses")
def create_course():
    require_auth({"Registrar"})
    body = get_json_body()

    exam_type = validators.require_enum(body, "exam_type", validators.EXAM_TYPES)
    fmt = validators.require_enum(body, "format", validators.FORMATS)
    title = validators.require_str(body, "title")
    list_price_cents = validators.require_int(body, "list_price_cents", minimum=0)
    baseline_scale_max = validators.require_int(body, "baseline_scale_max", minimum=1)
    guarantee_min_delta = validators.require_int(body, "guarantee_min_delta", minimum=0)
    required_practice_tests = validators.require_int(body, "required_practice_tests", minimum=0)
    required_attendance_pct = validators.require_number(
        body, "required_attendance_pct", minimum=0.0, maximum=1.0
    )
    materials_access_days = validators.require_int(body, "materials_access_days", minimum=1)

    rec = {
        "id": db.new_id(),
        "exam_type": exam_type,
        "format": fmt,
        "title": title,
        "list_price_cents": list_price_cents,
        "baseline_scale_max": baseline_scale_max,
        "guarantee_min_delta": guarantee_min_delta,
        "required_practice_tests": required_practice_tests,
        "required_attendance_pct": required_attendance_pct,
        "materials_access_days": materials_access_days,
        "status": "DRAFT",
    }
    db.stamp_create(rec)
    db.courses[rec["id"]] = rec
    return response.success(serialize.course(rec), 201)


@bp.post("/courses/<cid>/publish")
def publish_course(cid):
    require_auth({"Registrar"})
    course = db.courses.get(cid)
    if course is None:
        raise err("ERR_NOT_FOUND", "Course not found.")
    if course["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Course is not DRAFT.")
    course["status"] = "PUBLISHED"
    db.touch(course)
    return response.success(serialize.course(course), 200)


@bp.post("/courses/<cid>/retire")
def retire_course(cid):
    require_auth({"Registrar"})
    course = db.courses.get(cid)
    if course is None:
        raise err("ERR_NOT_FOUND", "Course not found.")
    if course["status"] != "PUBLISHED":
        raise err("ERR_INVALID_STATE", "Course is not PUBLISHED.")
    course["status"] = "RETIRED"
    db.touch(course)
    return response.success(serialize.course(course), 200)


@bp.get("/courses")
def list_courses():
    # Public catalog read: no auth required. If headers are present but the role
    # is unknown, still allow (public endpoint).
    from flask import request

    limit, offset = parse_pagination()
    exam_type = request.args.get("exam_type")
    fmt = request.args.get("format")
    status = request.args.get("status")

    records = list(db.courses.values())
    if exam_type is not None:
        records = [c for c in records if c["exam_type"] == exam_type]
    if fmt is not None:
        records = [c for c in records if c["format"] == fmt]
    if status is not None:
        records = [c for c in records if c["status"] == status]

    page, total = sort_and_page(records, limit, offset)
    return response.success_list([serialize.course(c) for c in page], limit, offset, total)


@bp.get("/courses/<cid>")
def get_course(cid):
    course = db.courses.get(cid)
    if course is None:
        raise err("ERR_NOT_FOUND", "Course not found.")
    return response.success(serialize.course(course), 200)


@bp.get("/courses/<cid>/cohorts")
def list_course_cohorts(cid):
    from flask import request

    course = db.courses.get(cid)
    if course is None:
        raise err("ERR_NOT_FOUND", "Course not found.")
    limit, offset = parse_pagination()
    status = request.args.get("status")
    records = [c for c in db.cohorts.values() if c["course_id"] == cid]
    if status is not None:
        records = [c for c in records if c["status"] == status]
    page, total = sort_and_page(records, limit, offset)
    return response.success_list(
        [serialize.cohort(c) for c in page], limit, offset, total
    )
