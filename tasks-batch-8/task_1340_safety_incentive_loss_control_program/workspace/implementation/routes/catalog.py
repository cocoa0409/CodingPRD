"""Catalog data: job roles and training courses (PRD 3.2)."""

from flask import Blueprint, request

import db
from middleware import auth, paginate, ALL_ROLES
from response import ok, ok_list
from services import core
from errors import ApiError

bp = Blueprint("catalog", __name__)

_HAZARD_CLASSES = ("LOW", "MODERATE", "HIGH")


@bp.route("/safety/job-roles", methods=["POST"])
def create_job_role():
    auth(["EHSAdmin"])
    body = core.body_json()
    title = core.req_str(body, "title")
    hazard_class = core.req_enum(body, "hazard_class", _HAZARD_CLASSES)
    course_ids = core.opt_list(body, "required_course_ids", default=[])
    for cid in course_ids:
        if not isinstance(cid, str):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "required_course_ids must be an array of course ids")
        core.get_or_404("training_courses", cid, "TrainingCourse")
    r = core.stamp_new({
        "id": core.new_id(),
        "title": title,
        "hazard_class": hazard_class,
        "required_course_ids": list(course_ids),
    })
    db.DB["job_roles"][r["id"]] = r
    return ok(core.job_role_view(r), 201)


@bp.route("/safety/job-roles", methods=["GET"])
def list_job_roles():
    auth(ALL_ROLES)
    hazard_class = request.args.get("hazard_class")
    course_id = request.args.get("required_course_ids")
    items = list(db.DB["job_roles"].values())
    if hazard_class is not None:
        items = [r for r in items if r["hazard_class"] == hazard_class]
    if course_id is not None:
        items = [r for r in items if course_id in r["required_course_ids"]]
    items = core.sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([core.job_role_view(r) for r in page], total, limit, offset)


@bp.route("/safety/job-roles/<rid>", methods=["GET"])
def get_job_role(rid):
    auth(ALL_ROLES)
    r = core.get_or_404("job_roles", rid, "JobRole")
    return ok(core.job_role_view(r))


@bp.route("/safety/training-courses", methods=["POST"])
def create_course():
    auth(["EHSAdmin"])
    body = core.body_json()
    title = core.req_str(body, "title")
    hazard_class = core.req_enum(body, "hazard_class", _HAZARD_CLASSES)
    validity = core.req_int(body, "validity_months", minimum=0)
    window = core.opt_int(body, "renewal_window_days", default=30, minimum=0)
    c = core.stamp_new({
        "id": core.new_id(),
        "title": title,
        "hazard_class": hazard_class,
        "validity_months": validity,
        "renewal_window_days": window,
    })
    db.DB["training_courses"][c["id"]] = c
    return ok(core.course_view(c), 201)


@bp.route("/safety/training-courses", methods=["GET"])
def list_courses():
    auth(ALL_ROLES)
    hazard_class = request.args.get("hazard_class")
    items = list(db.DB["training_courses"].values())
    if hazard_class is not None:
        items = [c for c in items if c["hazard_class"] == hazard_class]
    items = core.sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([core.course_view(c) for c in page], total, limit, offset)


@bp.route("/safety/training-courses/<cid>", methods=["GET"])
def get_course(cid):
    auth(ALL_ROLES)
    c = core.get_or_404("training_courses", cid, "TrainingCourse")
    return ok(core.course_view(c))
