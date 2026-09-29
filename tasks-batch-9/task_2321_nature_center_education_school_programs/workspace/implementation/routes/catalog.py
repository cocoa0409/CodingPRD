"""Program catalog: offerings, standard alignments and curriculum materials."""

from flask import Blueprint

import derive
import logical_clock
from envelope import array_response, object_response
from errors import ApiError
from schema import (body_json, lookup, opt_bool, opt_enum, opt_id, opt_str,
                    pagination, paginate, query_enum, query_str, req_enum,
                    req_int, req_str)
from security import authorize, teacher_scope_self
from store import db, new_entity, public, set_system_dt, sorted_rows, touch

bp = Blueprint("catalog", __name__)

GRADE_BANDS = ("K_2", "G3_5", "G6_8", "G9_12")
DELIVERY_MODES = ("ONSITE_FIELD_TRIP", "OUTREACH_AT_SCHOOL", "VIRTUAL")
OFFERING_STATUSES = ("DRAFT", "UNDER_REVIEW", "REVISION_REQUESTED", "PUBLISHED", "RETIRED")
DIMENSIONS = ("DISCIPLINARY_CORE_IDEA", "SCIENCE_PRACTICE", "CROSSCUTTING_CONCEPT")
PHASES = ("PRE_VISIT", "POST_VISIT")
MATERIAL_STATUSES = ("DRAFT", "PUBLISHED", "ARCHIVED")

READERS = ("CurriculumSpecialist", "EducationDirector", "BookingCoordinator", "TeacherContact")


@bp.post("/program-offerings")
def create_offering():
    actor = authorize(("CurriculumSpecialist",))
    body = body_json()
    title = req_str(body, "title")
    grade_band = req_enum(body, "grade_band", GRADE_BANDS)
    delivery_mode = req_enum(body, "delivery_mode", DELIVERY_MODES)
    duration_minutes = req_int(body, "duration_minutes", 30, 480)
    max_group_size = req_int(body, "max_group_size", 1, 500)
    ratio = req_int(body, "min_chaperone_ratio_students_per_adult", 1, 30)
    base_fee = req_int(body, "base_fee_cents_per_student", 0, 100000)
    requires_live_animal = opt_bool(body, "requires_live_animal", False)
    requires_trail_segment = opt_bool(body, "requires_trail_segment", False)
    public_contact_required = opt_bool(body, "public_contact_required", False)
    rain_alternate_for = opt_id(body, "rain_alternate_for_offering_id")

    if rain_alternate_for is not None:
        lookup("offering", rain_alternate_for)

    offering = new_entity()
    offering.update({
        "title": title,
        "grade_band": grade_band,
        "delivery_mode": delivery_mode,
        "duration_minutes": duration_minutes,
        "max_group_size": max_group_size,
        "min_chaperone_ratio_students_per_adult": ratio,
        "base_fee_cents_per_student": base_fee,
        "requires_live_animal": requires_live_animal,
        "requires_trail_segment": requires_trail_segment,
        "public_contact_required": public_contact_required,
        "rain_alternate_for_offering_id": rain_alternate_for,
        "status": "DRAFT",
        "authored_by_user_id": actor.user_id,
        "reviewed_by_user_id": None,
        "revision_round": 0,
        "standard_alignment_count": 0,
        "materials_ready": False,
        "published_at": None,
    })
    db.offerings[offering["id"]] = offering
    derive.sync()
    return object_response(public(offering), 201)


@bp.get("/program-offerings")
def list_offerings():
    actor = authorize(READERS)
    limit, offset = pagination()
    grade_band = query_enum("grade_band", GRADE_BANDS)
    delivery_mode = query_enum("delivery_mode", DELIVERY_MODES)
    status = query_enum("status", OFFERING_STATUSES)
    rain_alternate_for = query_str("rain_alternate_for_offering_id")
    teacher_scope_self(actor)

    rows = sorted_rows(db.offerings.values())
    if grade_band is not None:
        rows = [r for r in rows if r["grade_band"] == grade_band]
    if delivery_mode is not None:
        rows = [r for r in rows if r["delivery_mode"] == delivery_mode]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if rain_alternate_for is not None:
        rows = [r for r in rows if r.get("rain_alternate_for_offering_id") == rain_alternate_for]
    page, total = paginate(rows, limit, offset)
    return array_response([public(r) for r in page], limit, offset, total)


@bp.get("/program-offerings/<offering_id>")
def read_offering(offering_id):
    actor = authorize(READERS)
    offering = lookup("offering", offering_id)
    teacher_scope_self(actor)
    return object_response(public(offering))


@bp.post("/program-offerings/<offering_id>/standard-alignments")
def create_alignment(offering_id):
    authorize(("CurriculumSpecialist",))
    body = body_json()
    standard_code = req_str(body, "standard_code")
    dimension = req_enum(body, "dimension", DIMENSIONS)
    grade_band = opt_enum(body, "grade_band", GRADE_BANDS)
    offering = lookup("offering", offering_id)

    for existing in db.alignments.values():
        if (existing["offering_id"] == offering["id"]
                and existing["standard_code"] == standard_code
                and existing["dimension"] == dimension):
            raise ApiError("ERR_DUPLICATE_STANDARD_ALIGNMENT")

    alignment = new_entity(versioned=False)
    alignment.update({
        "offering_id": offering["id"],
        "standard_code": standard_code,
        "dimension": dimension,
        "grade_band": grade_band if grade_band is not None else offering["grade_band"],
    })
    db.alignments[alignment["id"]] = alignment
    derive.sync()
    return object_response(public(alignment), 201)


@bp.get("/program-offerings/<offering_id>/standard-alignments")
def list_alignments(offering_id):
    authorize(("CurriculumSpecialist", "EducationDirector"))
    limit, offset = pagination()
    offering = lookup("offering", offering_id)
    rows = [r for r in sorted_rows(db.alignments.values()) if r["offering_id"] == offering["id"]]
    page, total = paginate(rows, limit, offset)
    return array_response([public(r) for r in page], limit, offset, total)


@bp.post("/program-offerings/<offering_id>/materials")
def create_material(offering_id):
    authorize(("CurriculumSpecialist",))
    body = body_json()
    phase = req_enum(body, "phase", PHASES)
    url_slug = req_str(body, "url_slug")
    offering = lookup("offering", offering_id)

    material = new_entity()
    material.update({
        "offering_id": offering["id"],
        "phase": phase,
        "url_slug": url_slug,
        "status": "DRAFT",
    })
    db.materials[material["id"]] = material
    derive.sync()
    return object_response(public(material), 201)


@bp.get("/program-offerings/<offering_id>/materials")
def list_materials(offering_id):
    actor = authorize(("CurriculumSpecialist", "EducationDirector", "TeacherContact"))
    limit, offset = pagination()
    phase = query_enum("phase", PHASES)
    status = query_enum("status", MATERIAL_STATUSES)
    offering = lookup("offering", offering_id)
    teacher_scope_self(actor)

    rows = [r for r in sorted_rows(db.materials.values()) if r["offering_id"] == offering["id"]]
    if phase is not None:
        rows = [r for r in rows if r["phase"] == phase]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return array_response([public(r) for r in page], limit, offset, total)


@bp.post("/curriculum-materials/<material_id>/publish")
def publish_material(material_id):
    authorize(("CurriculumSpecialist",))
    material = lookup("material", material_id)
    if material["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_MATERIAL_STATE")
    offering = db.offerings.get(material["offering_id"])
    if offering is None or offering["status"] not in ("DRAFT", "UNDER_REVIEW", "REVISION_REQUESTED", "PUBLISHED"):
        raise ApiError("ERR_INVALID_OFFERING_STATE")
    material["status"] = "PUBLISHED"
    touch(material)
    derive.sync()
    return object_response(public(material))


@bp.post("/program-offerings/<offering_id>/submit-for-review")
def submit_for_review(offering_id):
    authorize(("CurriculumSpecialist",))
    offering = lookup("offering", offering_id)
    if offering["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError("ERR_INVALID_OFFERING_STATE")
    if derive.alignment_count(offering["id"]) < 1:
        raise ApiError("ERR_INSUFFICIENT_STANDARD_ALIGNMENT")
    offering["status"] = "UNDER_REVIEW"
    touch(offering)
    derive.sync()
    return object_response(public(offering))


@bp.post("/program-offerings/<offering_id>/review")
def review_offering(offering_id):
    actor = authorize(("EducationDirector",))
    body = body_json()
    decision = req_enum(body, "decision", ("PUBLISH", "REQUEST_REVISION"))
    opt_str(body, "reviewer_note")
    offering = lookup("offering", offering_id)

    if actor.user_id == offering.get("authored_by_user_id"):
        raise ApiError("ERR_SOD_REVIEW_SAME_ACTOR")
    if offering["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_OFFERING_STATE")

    if decision == "PUBLISH":
        if derive.alignment_count(offering["id"]) < 2:
            raise ApiError("ERR_INSUFFICIENT_STANDARD_ALIGNMENT")
        if not derive.materials_ready(offering["id"]):
            raise ApiError("ERR_MATERIALS_NOT_READY")
        offering["status"] = "PUBLISHED"
        set_system_dt(offering, "published_at", logical_clock.now())
        offering["reviewed_by_user_id"] = actor.user_id
        touch(offering)
    else:
        offering["status"] = "REVISION_REQUESTED"
        offering["revision_round"] = offering["revision_round"] + 1
        offering["reviewed_by_user_id"] = actor.user_id
        touch(offering)
        for material in derive.materials_for(offering["id"]):
            if material["status"] == "PUBLISHED":
                material["status"] = "DRAFT"
                touch(material)
    derive.sync()
    return object_response(public(offering))


@bp.post("/program-offerings/<offering_id>/retire")
def retire_offering(offering_id):
    authorize(("EducationDirector",))
    body = body_json()
    opt_str(body, "reason")
    offering = lookup("offering", offering_id)
    if offering["status"] not in ("DRAFT", "PUBLISHED"):
        raise ApiError("ERR_INVALID_OFFERING_STATE")
    for booking in derive.bookings_where("offering_id", offering["id"]):
        if booking["delivery_status"] in ("REQUESTED", "CONFIRMED", "RAIN_DIVERTED"):
            raise ApiError("ERR_OFFERING_HAS_ACTIVE_BOOKINGS")
    offering["status"] = "RETIRED"
    touch(offering)
    for material in derive.materials_for(offering["id"]):
        if material["status"] in ("DRAFT", "PUBLISHED"):
            material["status"] = "ARCHIVED"
            touch(material)
    derive.sync()
    return object_response(public(offering))
