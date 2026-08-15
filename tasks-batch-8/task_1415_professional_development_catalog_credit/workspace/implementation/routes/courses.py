"""Course catalog."""
from flask import Blueprint, request

from auth import require_role, require_any_role
from db import store, new_resource, touch
from envelope import ok, paginate, get_body, sort_by_created
from errors import err, ERR_NOT_FOUND, ERR_INVALID_STATE
from serializers import ser_course
from validate import req_str, req_enum, req_number, opt_int, opt_str

bp = Blueprint("courses", __name__)

DELIVERY_MODES = ("IN_PERSON", "VIRTUAL", "HYBRID")


def get_course_or_404(cid):
    c = store.courses.get(cid)
    if c is None:
        raise err(ERR_NOT_FOUND, "course not found")
    return c


@bp.post("/pd/courses")
def create_course():
    require_role("PDCoordinator")
    body = get_body()
    code = req_str(body, "course_code")
    title = req_str(body, "title")
    mode = req_enum(body, "delivery_mode", DELIVERY_MODES)
    hours = req_number(body, "clock_hours", gt=0)
    fee = opt_int(body, "fee_cents", minimum=0)
    fee = 0 if fee is None else fee
    tag = opt_str(body, "compliance_tag")
    recurrence = opt_int(body, "recurrence_months", minimum=1)
    prereq = opt_str(body, "prerequisite_course_id")
    for c in store.courses.values():
        if c["course_code"] == code:
            from errors import ERR_INVALID_REQUEST
            raise err(ERR_INVALID_REQUEST, "course_code must be unique")
    if prereq is not None and prereq not in store.courses:
        raise err(ERR_NOT_FOUND, "prerequisite_course_id not found")
    c = new_resource()
    c.update({
        "course_code": code,
        "title": title,
        "delivery_mode": mode,
        "clock_hours": hours,
        "fee_cents": fee,
        "compliance_tag": tag,
        "recurrence_months": recurrence,
        "prerequisite_course_id": prereq,
        "status": "ACTIVE",
    })
    store.courses[c["id"]] = c
    return ok(ser_course(c), 201)


@bp.get("/pd/courses/<cid>")
def get_course(cid):
    require_any_role()
    return ok(ser_course(get_course_or_404(cid)), 200)


@bp.get("/pd/courses")
def list_courses():
    require_any_role()
    items = store.courses.values()
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    tag = request.args.get("compliance_tag")
    if tag is not None:
        items = [c for c in items if c["compliance_tag"] == tag]
    prereq = request.args.get("prerequisite_course_id")
    if prereq is not None:
        items = [c for c in items if c["prerequisite_course_id"] == prereq]
    return paginate([ser_course(c) for c in sort_by_created(items)])


@bp.post("/pd/courses/<cid>/retire")
def retire_course(cid):
    require_role("PDCoordinator")
    get_body()
    c = get_course_or_404(cid)
    if c["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "course is not ACTIVE")
    for s in store.sections.values():
        if s["course_id"] == c["id"] and s["status"] in (
                "PUBLISHED", "REGISTRATION_CLOSED", "IN_SESSION"):
            raise err(ERR_INVALID_STATE,
                      "course has sections in a live state")
    c["status"] = "RETIRED"
    touch(c)
    return ok(ser_course(c), 200)
