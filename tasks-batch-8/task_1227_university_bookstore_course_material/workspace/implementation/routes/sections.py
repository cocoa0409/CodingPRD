"""Course sections, enrollments, and the IA charge creation cascade at lock
(PRD §3.3)."""

from flask import Blueprint, request

from db import store, new_entity, touch, pub
from errors import (
    ApiError, ERR_VALIDATION, ERR_INVALID_STATE, ERR_NOT_OWNER,
    ERR_ENROLLMENT_DUPLICATE, ERR_SECTION_CAPACITY_REACHED,
)
from middleware import (
    require_roles, body, get_str, get_int, get_bool, get_or_404,
)
from response import success, list_response

bp = Blueprint("sections", __name__)

SECTION_READ_ROLES = ("PlatformAdmin", "BookstoreManager", "Faculty", "Student")
ENROLLMENT_READ_ROLES = ("PlatformAdmin", "BookstoreManager", "Student")


@bp.post("/bookstore/sections")
def create_section():
    require_roles("PlatformAdmin")
    data = body()
    term_id = get_str(data, "term_id")
    faculty_id = get_str(data, "faculty_id")
    course_code = get_str(data, "course_code")
    section_code = get_str(data, "section_code")
    capacity = get_int(data, "enrollment_capacity", min_val=0)
    ia_enabled = get_bool(data, "ia_enabled")
    get_or_404(store.terms, term_id, "term")
    get_or_404(store.faculty, faculty_id, "faculty")
    # ia_material_fee_cents is required exactly when ia_enabled is true
    if ia_enabled:
        fee = get_int(data, "ia_material_fee_cents", min_val=0)
    else:
        fee = get_int(data, "ia_material_fee_cents", required=False,
                      default=None, min_val=0)
    # section_code unique within (term_id, course_code)
    for s in store.sections.values():
        if (s["term_id"] == term_id and s["course_code"] == course_code
                and s["section_code"] == section_code):
            raise ApiError(
                ERR_VALIDATION, 400,
                "section_code must be unique within (term_id, course_code)")
    sec = new_entity()
    sec.update({
        "term_id": term_id,
        "faculty_id": faculty_id,
        "course_code": course_code,
        "section_code": section_code,
        "enrollment_capacity": capacity,
        "ia_enabled": ia_enabled,
        "ia_material_fee_cents": fee,
        "status": "DRAFT",
        "compliance_status": "PENDING",
    })
    store.sections[sec["id"]] = sec
    return success(pub(sec), status=201)


@bp.get("/bookstore/sections")
def list_sections():
    require_roles(*SECTION_READ_ROLES)
    term_id = request.args.get("term_id")
    faculty_id = request.args.get("faculty_id")
    status = request.args.get("status")
    items = [
        s for s in store.sections.values()
        if (term_id is None or s["term_id"] == term_id)
        and (faculty_id is None or s["faculty_id"] == faculty_id)
        and (status is None or s["status"] == status)
    ]
    return list_response(items)


@bp.get("/bookstore/sections/<sid>")
def get_section(sid):
    require_roles(*SECTION_READ_ROLES)
    return success(pub(get_or_404(store.sections, sid, "section")))


@bp.post("/bookstore/sections/<sid>/open")
def open_section(sid):
    require_roles("PlatformAdmin")
    sec = get_or_404(store.sections, sid, "section")
    if sec["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "section not in DRAFT")
    term = store.terms[sec["term_id"]]
    if term["status"] not in ("ADOPTION_OPEN", "ADOPTION_CLOSED", "SALES_OPEN"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "term not in an adoption/sales phase")
    sec["status"] = "OPEN"
    touch(sec)
    return success(pub(sec))


@bp.post("/bookstore/sections/<sid>/lock")
def lock_section(sid):
    require_roles("BookstoreManager")
    sec = get_or_404(store.sections, sid, "section")
    if sec["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "section not in OPEN")
    term = store.terms[sec["term_id"]]
    if term["status"] != "SALES_OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "term not in SALES_OPEN")
    if sec["ia_enabled"]:
        # one PENDING inclusive-access charge per ENROLLED enrollment, fee
        # locked from the section at this moment
        for enr in store.enrollments.values():
            if enr["section_id"] != sec["id"] or enr["status"] != "ENROLLED":
                continue
            if any(c["enrollment_id"] == enr["id"]
                   for c in store.ia_charges.values()):
                continue
            ch = new_entity()
            ch.update({
                "enrollment_id": enr["id"],
                "section_id": sec["id"],
                "student_id": enr["student_id"],
                "term_id": sec["term_id"],
                "fee_cents": sec["ia_material_fee_cents"],
                "aid_applied_cents": 0,
                "balance_due_cents": 0,
                "status": "PENDING",
                "opted_out_at": None,
            })
            store.ia_charges[ch["id"]] = ch
    sec["status"] = "LOCKED"
    touch(sec)
    return success(pub(sec))


@bp.post("/bookstore/sections/<sid>/enrollments")
def create_enrollment(sid):
    require_roles("PlatformAdmin")
    sec = get_or_404(store.sections, sid, "section")
    data = body()
    student_id = get_str(data, "student_id")
    get_or_404(store.students, student_id, "student")
    for e in store.enrollments.values():
        if e["section_id"] == sec["id"] and e["student_id"] == student_id:
            raise ApiError(ERR_ENROLLMENT_DUPLICATE, 409,
                           "enrollment already exists for (section, student)")
    enrolled = sum(
        1 for e in store.enrollments.values()
        if e["section_id"] == sec["id"] and e["status"] == "ENROLLED")
    if enrolled >= sec["enrollment_capacity"]:
        raise ApiError(ERR_SECTION_CAPACITY_REACHED, 409,
                       "section enrollment capacity reached")
    enr = new_entity()
    enr.update({
        "section_id": sec["id"],
        "student_id": student_id,
        "status": "ENROLLED",
    })
    store.enrollments[enr["id"]] = enr
    return success(pub(enr), status=201)


@bp.get("/bookstore/enrollments")
def list_enrollments():
    require_roles(*ENROLLMENT_READ_ROLES)
    section_id = request.args.get("section_id")
    student_id = request.args.get("student_id")
    status = request.args.get("status")
    items = [
        e for e in store.enrollments.values()
        if (section_id is None or e["section_id"] == section_id)
        and (student_id is None or e["student_id"] == student_id)
        and (status is None or e["status"] == status)
    ]
    return list_response(items)


@bp.get("/bookstore/enrollments/<eid>")
def get_enrollment(eid):
    require_roles(*ENROLLMENT_READ_ROLES)
    return success(pub(get_or_404(store.enrollments, eid, "enrollment")))


@bp.post("/bookstore/enrollments/<eid>/drop")
def drop_enrollment(eid):
    uid, role = require_roles("Student", "BookstoreManager")
    enr = get_or_404(store.enrollments, eid, "enrollment")
    if role == "Student":
        if enr["student_id"] != uid:
            raise ApiError(ERR_NOT_OWNER, 403, "not the enrollment owner")
    if enr["status"] != "ENROLLED":
        raise ApiError(ERR_INVALID_STATE, 409, "enrollment not ENROLLED")
    sec = store.sections[enr["section_id"]]
    if role == "Student" and sec["status"] == "LOCKED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "students cannot drop from a locked section")
    # IA cascade: PENDING/OPTED_OUT -> CANCELLED; BILLED -> REFUNDED with aid
    # credit and zeroed amounts
    for ch in store.ia_charges.values():
        if ch["enrollment_id"] != enr["id"]:
            continue
        if ch["status"] in ("PENDING", "OPTED_OUT"):
            ch["status"] = "CANCELLED"
            touch(ch)
        elif ch["status"] == "BILLED":
            student = store.students[ch["student_id"]]
            student["aid_balance_cents"] += ch["aid_applied_cents"]
            touch(student)
            ch["aid_applied_cents"] = 0
            ch["balance_due_cents"] = 0
            ch["status"] = "REFUNDED"
            touch(ch)
    enr["status"] = "DROPPED"
    touch(enr)
    return success(pub(enr))
