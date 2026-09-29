"""Equipment manifests, evaluation reports and the logical-clock helper."""

from flask import Blueprint

import calc
import derive
import logical_clock
from envelope import array_response, object_response
from errors import ApiError
from schema import (body_json, lookup, opt_str, opt_str_array, pagination,
                    paginate, query_enum, req_dt, req_enum, req_int, req_num,
                    req_str_array)
from security import authorize, teacher_scope
from store import db, new_entity, public, sorted_rows, touch

bp = Blueprint("ops", __name__)
clock_bp = Blueprint("clock", __name__)

MANIFEST_STATUSES = ("DRAFT", "LOADED", "RETURNED", "SHORTAGE_REPORTED")
EVALUATION_STATUSES = ("DRAFT", "SUBMITTED", "RETURNED", "ACCEPTED")


# -------------------------------------------------------- equipment manifests
@bp.post("/bookings/<booking_id>/equipment-manifests")
def create_manifest(booking_id):
    authorize(("BookingCoordinator",))
    body = body_json()
    kit_codes = req_str_array(body, "kit_codes")
    total_weight = req_num(body, "total_weight_kg", high=4000, exclusive_low=0)
    booking = lookup("booking", booking_id)

    manifest = new_entity()
    manifest.update({
        "booking_id": booking["id"],
        "kit_codes": kit_codes,
        "total_weight_kg": total_weight,
        "vehicle_class": None,
        "status": "DRAFT",
        "shortage_kit_codes": [],
    })
    db.manifests[manifest["id"]] = manifest
    derive.sync()
    return object_response(public(manifest), 201)


@bp.get("/bookings/<booking_id>/equipment-manifests")
def list_manifests(booking_id):
    authorize(("BookingCoordinator", "EducationDirector"))
    limit, offset = pagination()
    status = query_enum("status", MANIFEST_STATUSES)
    booking = lookup("booking", booking_id)

    rows = [r for r in sorted_rows(db.manifests.values()) if r["booking_id"] == booking["id"]]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return array_response([public(r) for r in page], limit, offset, total)


@bp.post("/equipment-manifests/<manifest_id>/advance")
def advance_manifest(manifest_id):
    authorize(("BookingCoordinator",))
    body = body_json()
    action = req_enum(body, "action", ("LOAD", "RETURN"))
    shortage = opt_str_array(body, "shortage_kit_codes")
    manifest = lookup("manifest", manifest_id)
    booking = db.bookings.get(manifest["booking_id"])

    if action == "LOAD":
        if manifest["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_MANIFEST_STATE")
        if booking is None or booking["delivery_status"] != "CONFIRMED":
            raise ApiError("ERR_INVALID_BOOKING_STATE")
        manifest["vehicle_class"] = calc.vehicle_class(manifest["total_weight_kg"])
        manifest["status"] = "LOADED"
        touch(manifest)
        new_fee = derive.provisional_fee(booking)
        if booking["provisional_gross_fee_cents"] != new_fee:
            booking["provisional_gross_fee_cents"] = new_fee
            touch(booking)
    else:
        if manifest["status"] != "LOADED":
            raise ApiError("ERR_INVALID_MANIFEST_STATE")
        codes = shortage if shortage else []
        for code in codes:
            if code not in manifest["kit_codes"]:
                raise ApiError("ERR_SHORTAGE_CODE_UNKNOWN")
        if codes:
            manifest["shortage_kit_codes"] = codes
            manifest["status"] = "SHORTAGE_REPORTED"
        else:
            manifest["status"] = "RETURNED"
        touch(manifest)

    derive.sync()
    return object_response(public(manifest))


# --------------------------------------------------------- evaluation reports
@bp.post("/bookings/<booking_id>/evaluation-reports")
def create_evaluation(booking_id):
    actor = authorize(("TeacherContact",))
    body = body_json()
    standards = req_int(body, "teacher_score_standards_alignment", 1, 5)
    logistics = req_int(body, "teacher_score_logistics", 1, 5)
    engagement = req_int(body, "teacher_score_engagement", 1, 5)
    pre_score = req_num(body, "student_pre_score_avg", 0, calc.MAX_ASSESSMENT_SCORE)
    post_score = req_num(body, "student_post_score_avg", 0, calc.MAX_ASSESSMENT_SCORE)
    comment = opt_str(body, "teacher_comment")
    booking = lookup("booking", booking_id)
    teacher_scope(actor, booking["school_id"])

    for existing in derive.evaluations_for(booking["id"]):
        if existing["status"] in EVALUATION_STATUSES:
            raise ApiError("ERR_DUPLICATE_EVALUATION")

    report = new_entity()
    report.update({
        "booking_id": booking["id"],
        "teacher_score_standards_alignment": standards,
        "teacher_score_logistics": logistics,
        "teacher_score_engagement": engagement,
        "student_pre_score_avg": pre_score,
        "student_post_score_avg": post_score,
        "teacher_comment": comment,
        "learning_gain_index": 0,
        "status": "DRAFT",
        "submitted_by_user_id": None,
        "reviewed_by_user_id": None,
    })
    db.evaluations[report["id"]] = report
    derive.sync()
    return object_response(public(report), 201)


@bp.get("/bookings/<booking_id>/evaluation-reports")
def list_evaluations(booking_id):
    actor = authorize(("TeacherContact", "EducationDirector"))
    limit, offset = pagination()
    status = query_enum("status", EVALUATION_STATUSES)
    booking = lookup("booking", booking_id)
    teacher_scope(actor, booking["school_id"])

    rows = [r for r in sorted_rows(db.evaluations.values()) if r["booking_id"] == booking["id"]]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return array_response([public(r) for r in page], limit, offset, total)


@bp.post("/evaluation-reports/<report_id>/submit")
def submit_evaluation(report_id):
    actor = authorize(("TeacherContact",))
    report = lookup("evaluation", report_id)
    booking = db.bookings.get(report["booking_id"])
    teacher_scope(actor, booking["school_id"] if booking else None)

    if report["status"] not in ("DRAFT", "RETURNED"):
        raise ApiError("ERR_INVALID_EVALUATION_STATE")
    if booking is None or booking["delivery_status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_BOOKING_STATE")

    offering = derive.offering_of(booking)
    report["learning_gain_index"] = calc.learning_gain_index(report, booking, offering)
    report["status"] = "SUBMITTED"
    report["submitted_by_user_id"] = actor.user_id
    touch(report)
    derive.sync()
    return object_response(public(report))


@bp.post("/evaluation-reports/<report_id>/review")
def review_evaluation(report_id):
    actor = authorize(("EducationDirector",))
    body = body_json()
    decision = req_enum(body, "decision", ("ACCEPT", "RETURN"))
    opt_str(body, "reviewer_note")
    report = lookup("evaluation", report_id)

    if decision == "ACCEPT" and actor.user_id == report.get("submitted_by_user_id"):
        raise ApiError("ERR_SOD_EVALUATION_SAME_ACTOR")
    if report["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_EVALUATION_STATE")

    report["status"] = "ACCEPTED" if decision == "ACCEPT" else "RETURNED"
    report["reviewed_by_user_id"] = actor.user_id
    touch(report)
    derive.sync()
    return object_response(public(report))


# ------------------------------------------------------------- logical clock
@clock_bp.post("/_clock/set_current_utc")
def set_clock():
    authorize(("EducationDirector",))
    body = body_json()
    raw, parsed = req_dt(body, "to_iso8601")
    logical_clock.set_now(parsed)
    return object_response({"current_utc": raw})
