"""Re-enrollment offer routes."""

from flask import Blueprint, request

import db
import errors
from middleware import require_roles, get_json_body, check_fields
from response import success, success_list
from services import serializers as ser
from services.calculations import next_grade, sibling_discount_for
from services.helpers import (make_record, get_or_404, ref_or_404,
                              parent_scope_check, reenrollment_family_id,
                              sort_created)
from services.lifecycle import touch

bp = Blueprint("reenrollment", __name__)

READ_ROLES = ("AdmissionDirector", "AdmissionOfficer", "FinancialAidOfficer", "Parent")


@bp.post("/admissions/reenrollment-offers")
@require_roles("AdmissionDirector")
def create_offer(_uid, _role):
    body = get_json_body()
    vals = check_fields(body, {
        "student_id": "string",
        "cycle_id": "string",
        "expected_student_version": "int",
    }, {})
    student = ref_or_404(db.students, vals["student_id"], "Student")
    cycle = ref_or_404(db.cycles, vals["cycle_id"], "AdmissionCycle")
    # OCC on the student version (pipeline layer 9)
    if vals["expected_student_version"] != student["version"]:
        raise errors.err(errors.ERR_STALE_VERSION,
                         "expected_student_version does not match the student's current version")
    # No further offers once an ACCEPTED offer exists for the same student+cycle
    for o in db.reenrollment_offers.values():
        if (o["student_id"] == student["id"] and o["cycle_id"] == cycle["id"]
                and o["status"] == "ACCEPTED"):
            raise errors.err(errors.ERR_REENROLL_ALREADY_ACCEPTED,
                             "A re-enrollment offer for this student+cycle is already ACCEPTED")
    # Next-grade section must exist in the target cycle
    current_section = db.grade_sections.get(student["current_grade_section_id"])
    nxt = next_grade(current_section["grade_level"]) if current_section else None
    next_section = None
    if nxt is not None:
        for s in db.grade_sections.values():
            if s["cycle_id"] == cycle["id"] and s["grade_level"] == nxt:
                next_section = s
                break
    if next_section is None:
        raise errors.err(errors.ERR_NO_NEXT_GRADE,
                         "No grade section for the student's next grade exists in the target cycle")

    prior_tuition = current_section["tuition_cents"] if current_section else 0
    new_tuition = next_section["tuition_cents"]
    discount = sibling_discount_for(student, new_tuition)

    # Supersede any prior ISSUED offer for the same student+cycle
    for o in db.reenrollment_offers.values():
        if (o["student_id"] == student["id"] and o["cycle_id"] == cycle["id"]
                and o["status"] == "ISSUED"):
            o["status"] = "SUPERSEDED"
            touch(o)

    offer = make_record(db.reenrollment_offers, {
        "student_id": student["id"],
        "cycle_id": cycle["id"],
        "prior_tuition_cents": prior_tuition,
        "new_tuition_cents": new_tuition,
        "sibling_discount_cents": discount,
        "discounted_tuition_cents": new_tuition - discount,
        "response_deadline_at": cycle["reenroll_response_deadline_at"],
        "status": "ISSUED",
    })
    touch(student)  # issuance increments the student's version
    return success(ser.reenrollment_view(offer), 201)


@bp.get("/admissions/reenrollment-offers")
@require_roles(*READ_ROLES)
def list_offers(_uid, _role):
    student_id = request.args.get("student_id")
    cycle_id = request.args.get("cycle_id")
    family_id = request.args.get("family_id")
    status = request.args.get("status")
    if _role == "Parent":
        family_id = _uid
    items = []
    for o in db.reenrollment_offers.values():
        if student_id is not None and o["student_id"] != student_id:
            continue
        if cycle_id is not None and o["cycle_id"] != cycle_id:
            continue
        if status is not None and o["status"] != status:
            continue
        if family_id is not None and reenrollment_family_id(o) != family_id:
            continue
        items.append(o)
    return success_list([ser.reenrollment_view(o) for o in sort_created(items)])


@bp.get("/admissions/reenrollment-offers/<offerId>")
@require_roles(*READ_ROLES)
def get_offer(offerId, _uid, _role):
    offer = get_or_404(db.reenrollment_offers, offerId, "ReenrollmentOffer")
    parent_scope_check(_uid, _role, reenrollment_family_id(offer))
    return success(ser.reenrollment_view(offer))


@bp.post("/admissions/reenrollment-offers/<offerId>/respond")
@require_roles("Parent")
def respond_offer(offerId, _uid, _role):
    body = get_json_body()
    vals = check_fields(body, {"decision": ("enum", ("ACCEPTED", "DECLINED"))}, {})
    offer = get_or_404(db.reenrollment_offers, offerId, "ReenrollmentOffer")
    parent_scope_check(_uid, _role, reenrollment_family_id(offer))
    if offer["status"] != "ISSUED":
        raise errors.err(errors.ERR_REENROLL_NOT_ISSUED,
                         "Respond requires the offer to be ISSUED")
    deadline = db.parse_iso(offer["response_deadline_at"])
    if deadline is not None and db.get_clock() > deadline:
        raise errors.err(errors.ERR_REENROLL_WINDOW_CLOSED,
                         "The re-enrollment response window has closed")
    decision = vals["decision"]
    offer["status"] = decision
    touch(offer)
    if decision == "ACCEPTED":
        student = db.students[offer["student_id"]]
        student["re_enrolled_for_cycle_id"] = offer["cycle_id"]
        touch(student)
    return success(ser.reenrollment_view(offer))
