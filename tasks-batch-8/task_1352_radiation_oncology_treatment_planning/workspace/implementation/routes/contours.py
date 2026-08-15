"""Contour sets and peer review (PRD 3.3, segregation 2.9)."""
from flask import Blueprint

from db import store, new_entity, touch, sorted_all
from errors import (err, ERR_NOT_FOUND, ERR_COURSE_TERMINAL,
                    ERR_CONTOUR_NOT_SUBMITTABLE, ERR_CONTOUR_NOT_SUBMITTED,
                    ERR_SEGREGATION_OF_DUTIES)
from middleware import require_roles, ALL_ROLES, get_body
from response import success, paginate
from serializers import contour_json
from timeutil import new_id
from validate import req_str, req_str_list, opt_str

bp = Blueprint("contours", __name__)


def get_contour_or_404(kid):
    c = store.contours.get(kid)
    if c is None:
        err(ERR_NOT_FOUND, "contour set not found")
    return c


@bp.post("/oncology/treatment-courses/<cid>/contour-sets")
@require_roles("RadiationOncologist")
def create_contour(cid, user_id):
    course = store.courses.get(cid)
    if course is None:
        err(ERR_NOT_FOUND, "treatment course not found")
    body = get_body()
    label = req_str(body, "set_label")
    targets = req_str_list(body, "target_volumes", min_len=1)
    oars = req_str_list(body, "oar_structures", min_len=0, allow_missing=True)
    if course["status"] in ("COMPLETED", "DISCONTINUED"):
        err(ERR_COURSE_TERMINAL, "Course is terminal")
    c = new_entity()
    c.update({
        "id": new_id(), "course_id": cid, "set_label": label,
        "target_volumes": targets, "oar_structures": oars,
        "created_by_user_id": user_id, "reviewed_by_user_id": None,
        "status": "DRAFT",
    })
    store.contours[c["id"]] = c
    if course["status"] == "SIMULATED":
        course["status"] = "CONTOURING"
        touch(course)
    return success(contour_json(c), 201)


@bp.get("/oncology/treatment-courses/<cid>/contour-sets")
@require_roles(*ALL_ROLES)
def list_contours(cid, user_id):
    if cid not in store.courses:
        err(ERR_NOT_FOUND, "treatment course not found")
    items = sorted_all(c for c in store.contours.values() if c["course_id"] == cid)
    page, meta = paginate(items)
    return success([contour_json(c) for c in page], 200, pagination=meta)


@bp.get("/oncology/contour-sets/<kid>")
@require_roles(*ALL_ROLES)
def get_contour(kid, user_id):
    return success(contour_json(get_contour_or_404(kid)), 200)


@bp.post("/oncology/contour-sets/<kid>/submit")
@require_roles("RadiationOncologist")
def submit_contour(kid, user_id):
    contour = get_contour_or_404(kid)
    get_body()
    if contour["status"] not in ("DRAFT", "RETURNED"):
        err(ERR_CONTOUR_NOT_SUBMITTABLE, "Submit requires DRAFT or RETURNED")
    course = store.courses[contour["course_id"]]
    if course["status"] in ("COMPLETED", "DISCONTINUED"):
        err(ERR_COURSE_TERMINAL, "Course is terminal")
    contour["status"] = "SUBMITTED"
    touch(contour)
    return success(contour_json(contour), 200)


@bp.post("/oncology/contour-sets/<kid>/approve")
@require_roles("RadiationOncologist")
def approve_contour(kid, user_id):
    contour = get_contour_or_404(kid)
    get_body()
    if contour["status"] != "SUBMITTED":
        err(ERR_CONTOUR_NOT_SUBMITTED, "Approve requires SUBMITTED")
    course = store.courses[contour["course_id"]]
    if course["status"] in ("COMPLETED", "DISCONTINUED"):
        err(ERR_COURSE_TERMINAL, "Course is terminal")
    # p7 segregation: approver must differ from the creating oncologist
    if user_id == contour["created_by_user_id"]:
        err(ERR_SEGREGATION_OF_DUTIES,
            "The creating oncologist may not approve this contour set")
    contour["status"] = "APPROVED"
    contour["reviewed_by_user_id"] = user_id
    touch(contour)
    if course["status"] == "CONTOURING":
        course["status"] = "PLANNING"
        touch(course)
    return success(contour_json(contour), 200)


@bp.post("/oncology/contour-sets/<kid>/return")
@require_roles("RadiationOncologist")
def return_contour(kid, user_id):
    contour = get_contour_or_404(kid)
    get_body()  # accepts optional return_notes
    opt_str(get_body(), "return_notes")
    if contour["status"] not in ("SUBMITTED", "APPROVED"):
        err(ERR_CONTOUR_NOT_SUBMITTED, "Return requires SUBMITTED or APPROVED")
    if user_id == contour["created_by_user_id"]:
        err(ERR_SEGREGATION_OF_DUTIES,
            "The creating oncologist may not return this contour set")
    contour["status"] = "RETURNED"
    touch(contour)  # version bump stales plans pinning the old contour version
    return success(contour_json(contour), 200)
