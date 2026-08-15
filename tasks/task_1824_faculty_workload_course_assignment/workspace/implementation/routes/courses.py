"""Course endpoints (PRD §3.2)."""

import db
from errors import ApiError, ERR_COURSE_NOT_FOUND
from middleware import authenticate, ALL_ROLES, CHAIR
from response import success_obj, success_list
from routes import make_blueprint
from util import body_json, check_shape, pagination_params, paginate, apply_filters

bp = make_blueprint("courses")

COURSE_TYPES = ["LECTURE", "LAB", "SEMINAR"]
MODALITIES = ["IN_PERSON", "ONLINE", "HYBRID"]


@bp.post("/courses")
def create_course():
    authenticate([CHAIR])
    body = body_json()
    check_shape(body, {
        "course_code": {"type": "string", "required": True},
        "title": {"type": "string", "required": True},
        "course_type": {"type": "enum", "values": COURSE_TYPES, "required": True},
        "base_credits": {"type": "number", "required": True},
        "default_enrollment_cap": {"type": "integer", "required": True},
        "allowed_modalities": {"type": "enum_array", "values": MODALITIES, "non_empty": True, "required": True},
    })
    course = db.new_entity("courses", {
        "course_code": body["course_code"],
        "title": body["title"],
        "course_type": body["course_type"],
        "base_credits": body["base_credits"],
        "default_enrollment_cap": body["default_enrollment_cap"],
        "allowed_modalities": list(body["allowed_modalities"]),
    })
    return success_obj(db.public(course), 201)


@bp.get("/courses")
def list_courses():
    authenticate(ALL_ROLES)
    limit, offset = pagination_params()
    items = apply_filters(db.all_of("courses"), ["course_type"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(c) for c in page], limit, offset, total, has_more)


@bp.get("/courses/<courseId>")
def get_course(courseId):
    authenticate(ALL_ROLES)
    course = db.get("courses", courseId)
    if course is None:
        raise ApiError(ERR_COURSE_NOT_FOUND, 404, "course not found")
    return success_obj(db.public(course), 200)
