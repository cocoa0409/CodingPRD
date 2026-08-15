"""Clock, departments, terms, and courses."""

from flask import Blueprint, request

import db
from db import STORE, new_record, pub, touch
from errors import ApiError
from helpers import (
    body_fk, check_fields, get_json_body, is_number_held, list_response,
    parse_date, parse_dt, path_param, serialize_course, serialize_term,
)
from middleware import require_auth
from response import ok

bp = Blueprint("core", __name__)

REGISTRAR = {"Registrar"}


# --- Logical clock -----------------------------------------------------------

@bp.post("/curriculum/_clock/set_current_utc")
def set_clock():
    require_auth(REGISTRAR)
    body = get_json_body()
    check_fields(body, {"to_iso8601": ("datetime", True)})
    dt = parse_dt(body["to_iso8601"])
    db.CLOCK["dt"] = dt
    return ok({"current_utc": body["to_iso8601"]}, 200)


# --- Departments ---------------------------------------------------------------

@bp.post("/curriculum/departments")
def create_department():
    require_auth(REGISTRAR)
    body = get_json_body()
    check_fields(body, {
        "dept_name": ("str", True),
        "subject_codes": ("str_list", True),
        "college": ("str", True),
    })
    rec = new_record()
    rec.update({
        "dept_name": body["dept_name"],
        "subject_codes": list(body["subject_codes"]),
        "college": body["college"],
    })
    STORE["departments"][rec["id"]] = rec
    return ok(pub(rec), 201)


# --- Terms ---------------------------------------------------------------------

def _term_shape_rules(start_d, end_d, prop_frz, cat_frz):
    if not (end_d > start_d):
        raise ApiError("ERR_VALIDATION", 400, "classes_end_date must be after classes_start_date")
    if prop_frz > cat_frz:
        raise ApiError("ERR_VALIDATION", 400, "proposal_freeze_at must be at or before catalog_freeze_at")


def _term_overlap_check(start_d, end_d, exclude_id=None):
    """Half-open [start, end): conflict iff start < other.end AND end > other.start."""
    for other in STORE["terms"].values():
        if exclude_id is not None and other["id"] == exclude_id:
            continue
        o_start = parse_date(other["classes_start_date"])
        o_end = parse_date(other["classes_end_date"])
        if start_d < o_end and end_d > o_start:
            raise ApiError("ERR_TERM_DATE_OVERLAP", 409, "term date range overlaps an existing term")


def _term_sequence_check(seq, exclude_id=None):
    for other in STORE["terms"].values():
        if exclude_id is not None and other["id"] == exclude_id:
            continue
        if other["sequence_index"] == seq:
            raise ApiError("ERR_TERM_SEQUENCE_CONFLICT", 409, "sequence_index already in use")


@bp.post("/curriculum/terms")
def create_term():
    require_auth(REGISTRAR)
    body = get_json_body()
    check_fields(body, {
        "term_code": ("str", True),
        "academic_year": ("str", True),
        "sequence_index": ("int", True),
        "classes_start_date": ("date", True),
        "classes_end_date": ("date", True),
        "proposal_freeze_at": ("datetime", True),
        "catalog_freeze_at": ("datetime", True),
    })
    start_d = parse_date(body["classes_start_date"])
    end_d = parse_date(body["classes_end_date"])
    prop_frz = parse_dt(body["proposal_freeze_at"])
    cat_frz = parse_dt(body["catalog_freeze_at"])
    _term_shape_rules(start_d, end_d, prop_frz, cat_frz)
    _term_overlap_check(start_d, end_d)
    _term_sequence_check(body["sequence_index"])
    rec = new_record()
    rec.update({
        "term_code": body["term_code"],
        "academic_year": body["academic_year"],
        "sequence_index": body["sequence_index"],
        "classes_start_date": body["classes_start_date"],
        "classes_end_date": body["classes_end_date"],
        "proposal_freeze_at": body["proposal_freeze_at"],
        "catalog_freeze_at": body["catalog_freeze_at"],
        "status": "OPEN_FOR_PROPOSALS",
    })
    STORE["terms"][rec["id"]] = rec
    return ok(serialize_term(rec), 201)


@bp.get("/curriculum/terms/<tid>")
def get_term(tid):
    require_auth()
    rec = path_param("terms", tid)
    return ok(serialize_term(rec), 200)


@bp.patch("/curriculum/terms/<tid>")
def patch_term(tid):
    require_auth(REGISTRAR)
    rec = path_param("terms", tid)
    body = get_json_body()
    check_fields(body, {
        "expected_term_version": ("int", True),
        "classes_start_date": ("date", False),
        "classes_end_date": ("date", False),
        "proposal_freeze_at": ("datetime", False),
        "catalog_freeze_at": ("datetime", False),
    })
    # merged date-ordering rules (priority 4)
    start_d = parse_date(body.get("classes_start_date", rec["classes_start_date"]))
    end_d = parse_date(body.get("classes_end_date", rec["classes_end_date"]))
    prop_frz = parse_dt(body.get("proposal_freeze_at", rec["proposal_freeze_at"]))
    cat_frz = parse_dt(body.get("catalog_freeze_at", rec["catalog_freeze_at"]))
    _term_shape_rules(start_d, end_d, prop_frz, cat_frz)
    # optimistic concurrency
    if body["expected_term_version"] != rec["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "term version does not match expected_term_version")
    _term_overlap_check(start_d, end_d, exclude_id=rec["id"])
    for f in ("classes_start_date", "classes_end_date", "proposal_freeze_at", "catalog_freeze_at"):
        if f in body and body[f] is not None:
            rec[f] = body[f]
    touch(rec)
    return ok(serialize_term(rec), 200)


@bp.post("/curriculum/terms/<tid>/freeze-proposals")
def freeze_proposals(tid):
    require_auth(REGISTRAR)
    rec = path_param("terms", tid)
    if rec["status"] != "OPEN_FOR_PROPOSALS":
        raise ApiError("ERR_INVALID_STATE", 409, "term is not OPEN_FOR_PROPOSALS")
    if db.clock_now() < parse_dt(rec["proposal_freeze_at"]):
        raise ApiError("ERR_FREEZE_DATE_NOT_REACHED", 409, "proposal freeze datetime not reached")
    rec["status"] = "PROPOSAL_FROZEN"
    touch(rec)
    return ok(serialize_term(rec), 200)


@bp.post("/curriculum/terms/<tid>/freeze-catalog")
def freeze_catalog(tid):
    require_auth(REGISTRAR)
    rec = path_param("terms", tid)
    if rec["status"] != "PROPOSAL_FROZEN":
        raise ApiError("ERR_INVALID_STATE", 409, "term is not PROPOSAL_FROZEN")
    if db.clock_now() < parse_dt(rec["catalog_freeze_at"]):
        raise ApiError("ERR_FREEZE_DATE_NOT_REACHED", 409, "catalog freeze datetime not reached")
    rec["status"] = "CATALOG_FROZEN"
    touch(rec)
    return ok(serialize_term(rec), 200)


# --- Courses -------------------------------------------------------------------

@bp.post("/curriculum/courses")
def create_course():
    require_auth(REGISTRAR)
    body = get_json_body()
    check_fields(body, {
        "subject_code": ("str", True),
        "course_number": ("str", True),
        "title": ("str", True),
        "credit_hours": ("num", True),
        "contact_hours_per_week": ("num", True),
        "out_of_class_hours_per_week": ("num", True),
        "learning_outcomes": ("str_list", True),
        "owning_department_id": ("str", True),
        "introduced_in_term_id": ("str", True),
    })
    body_fk("departments", body["owning_department_id"], "owning_department_id")
    body_fk("terms", body["introduced_in_term_id"], "introduced_in_term_id")
    if len(body["learning_outcomes"]) == 0:
        raise ApiError("ERR_VALIDATION", 400, "learning_outcomes must be non-empty")
    if is_number_held(body["subject_code"], body["course_number"]):
        raise ApiError("ERR_COURSE_NUMBER_HELD", 409, "course number is already held")
    rec = new_record()
    rec.update({
        "subject_code": body["subject_code"],
        "course_number": body["course_number"],
        "title": body["title"],
        "credit_hours": body["credit_hours"],
        "contact_hours_per_week": body["contact_hours_per_week"],
        "out_of_class_hours_per_week": body["out_of_class_hours_per_week"],
        "learning_outcomes": list(body["learning_outcomes"]),
        "owning_department_id": body["owning_department_id"],
        "introduced_in_term_id": body["introduced_in_term_id"],
        "last_published_edition_id": None,
        "status": "ACTIVE",
    })
    STORE["courses"][rec["id"]] = rec
    return ok(serialize_course(rec), 201)


_COURSE_FILTERS = (
    "owning_department_id", "introduced_in_term_id", "last_published_edition_id",
    "status", "subject_code", "course_number",
)


@bp.get("/curriculum/courses")
def list_courses():
    require_auth()
    records = list(STORE["courses"].values())
    for f in _COURSE_FILTERS:
        v = request.args.get(f)
        if v is not None:
            records = [c for c in records if ("" if c[f] is None else str(c[f])) == v]
    return list_response(records, serialize_course)


@bp.get("/curriculum/courses/<cid>")
def get_course(cid):
    require_auth()
    rec = path_param("courses", cid)
    return ok(serialize_course(rec), 200)


@bp.get("/curriculum/courses/<cid>/requisites")
def list_course_requisites(cid):
    require_auth()
    course = path_param("courses", cid)
    records = [
        l for l in STORE["requisite_links"].values()
        if l["course_id"] == course["id"] or l["requisite_course_id"] == course["id"]
    ]
    rtype = request.args.get("requisite_type")
    if rtype is not None:
        records = [l for l in records if l["requisite_type"] == rtype]
    status = request.args.get("status")
    if status is not None:
        records = [l for l in records if l["status"] == status]
    return list_response(records, pub)


@bp.get("/curriculum/courses/<cid>/cross-listings")
def list_course_cross_listings(cid):
    require_auth()
    course = path_param("courses", cid)
    records = [
        cl for cl in STORE["cross_listings"].values()
        if cl["home_course_id"] == course["id"] or cl["partner_course_id"] == course["id"]
    ]
    status = request.args.get("status")
    if status is not None:
        records = [cl for cl in records if cl["status"] == status]
    return list_response(records, pub)
