"""Enrollment endpoints (PRD 3.4), the drop cascade (PRD 3.7) and single posting."""

from datetime import timedelta

from flask import Blueprint

from auth import (ROLE_BURSAR, ROLE_FACULTY, ROLE_PROGRAM_ADMIN, ROLE_REGISTRAR,
                  ROLE_STUDENT, authenticate)
from domain import (agreement_of_adoption, apply_drop_refunds, charge_json,
                    charges_of_enrollment, current_approved_adoption,
                    enrollment_json, freeze_billing_basis, get_enrollment,
                    get_section, get_student, get_term, gross_price,
                    has_live_charge, post_charge, recompute_section, tier_basis)
from errors import fail
from response import apply_filters, object_response, paginate
from store import base_record, db, in_order, touch
from validate import f_date, f_str, get_body

bp = Blueprint("enrollments", __name__)

READ_ROLES = (ROLE_PROGRAM_ADMIN, ROLE_FACULTY, ROLE_REGISTRAR, ROLE_BURSAR)

DROP_EVENT = "POST /enrollments/{enrollment_id}/drop"
POST_CHARGE_EVENT = "POST /enrollments/{enrollment_id}/post-charge"


@bp.post("/enrollments")
def create_enrollment():
    authenticate(ROLE_REGISTRAR)
    body = get_body(("section_id", "student_id", "enrolled_on"))
    section_id = f_str(body, "section_id")
    student_id = f_str(body, "student_id")
    enrolled_on = f_date(body, "enrolled_on")

    section = get_section(section_id)
    student = get_student(student_id)
    term = get_term(section["term_id"])

    if enrolled_on > term["late_registration_cutoff_date"]:
        fail("ERR_LATE_REGISTRATION_CLOSED")
    if enrolled_on < term["term_start_date"] - timedelta(days=30):
        fail("ERR_ENROLLMENT_DATE_OUT_OF_RANGE")

    for existing in db.enrollments.values():
        if (existing["section_id"] == section["id"]
                and existing["student_id"] == student["id"]
                and existing["status"] == "ENROLLED"):
            fail("ERR_DUPLICATE_ENROLLMENT")

    enrollment = base_record()
    enrollment.update({
        "section_id": section["id"],
        "student_id": student["id"],
        "enrolled_on": enrolled_on,
        "registration_type": ("REGULAR" if enrolled_on <= term["add_drop_deadline"]
                              else "LATE"),
        "status": "ENROLLED",
        "dropped_on": None,
    })
    db.enrollments[enrollment["id"]] = enrollment
    recompute_section(section)
    return object_response(enrollment_json(enrollment), 201)


@bp.get("/enrollments/<enrollment_id>")
def read_enrollment(enrollment_id):
    authenticate(*READ_ROLES)
    return object_response(enrollment_json(get_enrollment(enrollment_id)))


@bp.get("/enrollments")
def list_enrollments():
    authenticate(*READ_ROLES)
    items = apply_filters(in_order(db.enrollments.values()), [
        ("section_id", "section_id"),
        ("student_id", "student_id"),
        ("status", "status"),
        ("registration_type", "registration_type"),
    ])
    return paginate(items, enrollment_json)


@bp.post("/enrollments/<enrollment_id>/drop")
def drop_enrollment(enrollment_id):
    authenticate(ROLE_REGISTRAR)
    body = get_body(("dropped_on",))
    dropped_on = f_date(body, "dropped_on")
    enrollment = get_enrollment(enrollment_id)
    section = get_section(enrollment["section_id"])
    term = get_term(section["term_id"])

    if enrollment["status"] != "ENROLLED":
        fail("ERR_INVALID_STATE")
    if term["status"] not in ("OPEN", "BILLING_LOCKED"):
        fail("ERR_INVALID_STATE")
    if dropped_on < enrollment["enrolled_on"]:
        fail("ERR_ENROLLMENT_DATE_OUT_OF_RANGE")

    enrollment["status"] = "DROPPED"
    enrollment["dropped_on"] = dropped_on
    touch(enrollment)

    apply_drop_refunds(enrollment, section, term, DROP_EVENT)
    recompute_section(section)
    return object_response(enrollment_json(enrollment))


@bp.get("/enrollments/<enrollment_id>/charges")
def list_enrollment_charges(enrollment_id):
    authenticate(ROLE_PROGRAM_ADMIN, ROLE_REGISTRAR, ROLE_BURSAR, ROLE_STUDENT)
    enrollment = get_enrollment(enrollment_id)
    items = apply_filters(charges_of_enrollment(enrollment["id"]),
                          [("billing_status", "billing_status")])
    return paginate(items, charge_json)


@bp.post("/enrollments/<enrollment_id>/post-charge")
def post_single_charge(enrollment_id):
    authenticate(ROLE_BURSAR, ROLE_PROGRAM_ADMIN)
    get_body(())
    enrollment = get_enrollment(enrollment_id)
    section = get_section(enrollment["section_id"])
    term = get_term(section["term_id"])

    if term["status"] != "OPEN":
        fail("ERR_TERM_BILLING_LOCKED")
    if section["ia_status"] not in ("FLAGGED", "BILLED"):
        fail("ERR_SECTION_NOT_FLAGGED")

    adoption = current_approved_adoption(section["id"])
    if adoption is None:
        fail("ERR_ADOPTION_NOT_APPROVED")
    if agreement_of_adoption(adoption)["status"] != "ACTIVE":
        fail("ERR_AGREEMENT_NOT_ACTIVE")
    if enrollment["status"] != "ENROLLED":
        fail("ERR_ENROLLMENT_NOT_ACTIVE")

    basis = tier_basis(section)
    gross_price(adoption, basis)

    if has_live_charge(enrollment["id"], adoption["id"]):
        fail("ERR_CHARGE_ALREADY_EXISTS")

    charge = post_charge(section, term, enrollment, adoption, basis, POST_CHARGE_EVENT)
    freeze_billing_basis(section, term, basis)
    recompute_section(section)
    return object_response(charge_json(charge), 201)
