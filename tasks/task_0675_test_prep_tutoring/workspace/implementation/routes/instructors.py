"""Instructor endpoints (PRD §3.2)."""
from flask import Blueprint, request

import db
import response
from errors import err
from middleware import require_auth, get_json_body, parse_pagination
from services import serialize, validators
from services.listing import sort_and_page

bp = Blueprint("instructors", __name__)


@bp.post("/instructors")
def create_instructor():
    require_auth({"Registrar"})
    body = get_json_body()

    full_name = validators.require_str(body, "full_name")
    certified = validators.require(body, "certified_exam_types")
    if (
        not isinstance(certified, list)
        or len(certified) == 0
        or any(e not in validators.EXAM_TYPES for e in certified)
    ):
        raise err(
            "ERR_INVALID_REQUEST",
            "certified_exam_types must be a non-empty array of exam-type enums.",
        )
    max_concurrent = validators.require_int(body, "max_concurrent_cohorts", minimum=1)

    rec = {
        "id": db.new_id(),
        "full_name": full_name,
        "certified_exam_types": list(certified),
        "max_concurrent_cohorts": max_concurrent,
        "active_cohort_count": 0,
    }
    db.stamp_create(rec)
    db.instructors[rec["id"]] = rec
    return response.success(serialize.instructor(rec), 201)


@bp.get("/instructors/<iid>")
def get_instructor(iid):
    require_auth({"Registrar", "Instructor"})
    inst = db.instructors.get(iid)
    if inst is None:
        raise err("ERR_NOT_FOUND", "Instructor not found.")
    return response.success(serialize.instructor(inst), 200)


@bp.get("/instructors/<iid>/cohorts")
def list_instructor_cohorts(iid):
    require_auth({"Registrar", "Instructor"})
    inst = db.instructors.get(iid)
    if inst is None:
        raise err("ERR_NOT_FOUND", "Instructor not found.")
    limit, offset = parse_pagination()
    status = request.args.get("status")
    records = [c for c in db.cohorts.values() if c["instructor_id"] == iid]
    if status is not None:
        records = [c for c in records if c["status"] == status]
    page, total = sort_and_page(records, limit, offset)
    return response.success_list(
        [serialize.cohort(c) for c in page], limit, offset, total
    )
