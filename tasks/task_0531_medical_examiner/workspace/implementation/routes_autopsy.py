"""Autopsy exam scheduling, completion, cancellation, list/get."""
from flask import Blueprint, request

import calculations
import errors
import lookup
import validate
from clock import parse_iso, fmt_iso
from db import db
from middleware import require, json_body, paginate
from records import make_record, touch, public
from response import object_response, array_response
import services

bp = Blueprint("autopsy", __name__)


def _view(rec):
    return public(rec)


def _interval(scheduled_for, duration_minutes):
    start = scheduled_for
    end = start.timestamp() + duration_minutes * 60
    return start.timestamp(), end


@bp.post("/cases/<case_id>/autopsy-exams")
def schedule_exam(case_id):
    require({"Pathologist"})
    case = lookup.case(case_id)
    body = json_body()
    pathologist_user_id = validate.req_str(body, "pathologist_user_id")
    scheduled_for = validate.req_datetime(body, "scheduled_for")
    duration_minutes = validate.req_int(body, "duration_minutes", minimum=30)

    # referenced pathologist must exist (priority 20)
    lookup.pathologist(pathologist_user_id)

    # declined case is a dead end (priority 22)
    if case["status"] == "DECLINED":
        raise errors.err(errors.ERR_CASE_DECLINED, "Case is declined")

    # double-booking (priority 32): half-open interval overlap vs other SCHEDULED
    new_start, new_end = _interval(scheduled_for, duration_minutes)
    for e in db.autopsy_exams.values():
        if e["pathologist_user_id"] != pathologist_user_id:
            continue
        if e["exam_status"] != "SCHEDULED":
            continue
        e_start, e_end = _interval(parse_iso(e["scheduled_for"]), e["duration_minutes"])
        # overlap iff new_start < e_end and e_start < new_end (adjacency allowed)
        if new_start < e_end and e_start < new_end:
            raise errors.err(errors.ERR_PATHOLOGIST_DOUBLE_BOOKED, "Pathologist double-booked")

    estimated = calculations.autopsy_fee_estimate(duration_minutes, case["case_type"])
    rec = make_record({
        "case_id": case_id,
        "pathologist_user_id": pathologist_user_id,
        "scheduled_for": fmt_iso(scheduled_for),
        "duration_minutes": duration_minutes,
        "exam_status": "SCHEDULED",
        "estimated_fee_cents": estimated,
        "final_fee_cents": None,
        "primary_finding": None,
        "cause_of_death": None,
    })
    db.autopsy_exams[rec["id"]] = rec
    return object_response(_view(rec), 201)


@bp.get("/cases/<case_id>/autopsy-exams")
def list_case_exams(case_id):
    require({"Admin", "Investigator", "MedicalExaminer", "Pathologist"})
    lookup.case(case_id)
    rows = [e for e in db.autopsy_exams.values() if e["case_id"] == case_id]
    page, limit, offset, total = paginate(rows)
    return array_response([_view(e) for e in page], limit, offset, total)


@bp.get("/autopsy-exams/<id_>")
def get_exam(id_):
    require({"Admin", "Investigator", "MedicalExaminer", "Pathologist"})
    rec = lookup.autopsy_exam(id_)
    return object_response(_view(rec), 200)


@bp.get("/autopsy-exams")
def list_exams():
    require({"Admin", "Pathologist", "MedicalExaminer"})
    rows = list(db.autopsy_exams.values())
    path = request.args.get("pathologist_user_id")
    if path is not None:
        rows = [e for e in rows if e["pathologist_user_id"] == path]
    page, limit, offset, total = paginate(rows)
    return array_response([_view(e) for e in page], limit, offset, total)


@bp.post("/autopsy-exams/<id_>/complete")
def complete_exam(id_):
    actor = require({"Pathologist"})
    rec = lookup.autopsy_exam(id_)
    body = json_body()
    primary_finding = validate.req_str(body, "primary_finding")
    cause_of_death = validate.req_str(body, "cause_of_death")

    if rec["exam_status"] != "SCHEDULED":
        raise errors.err(errors.ERR_INVALID_STATE, "Complete only allowed from SCHEDULED")

    now = db.clock.now()
    scheduled_for = parse_iso(rec["scheduled_for"])
    if now < scheduled_for:
        raise errors.err(errors.ERR_EXAM_NOT_DUE, "Autopsy not yet due")

    # only the recorded pathologist may complete (ownership check -> forbidden)
    if actor.user_id != rec["pathologist_user_id"]:
        raise errors.err(errors.ERR_FORBIDDEN_ROLE, "Only the assigned pathologist may complete")

    case = db.cases.get(rec["case_id"])
    case_type = case["case_type"] if case else "PENDING"
    billable = services.billable_specimen_count(rec["case_id"])
    final = calculations.autopsy_fee_final(scheduled_for, now, rec["duration_minutes"], billable, case_type)

    rec["exam_status"] = "COMPLETED"
    rec["primary_finding"] = primary_finding
    rec["cause_of_death"] = cause_of_death
    rec["final_fee_cents"] = final
    touch(rec)
    return object_response(_view(rec), 200)


@bp.post("/autopsy-exams/<id_>/cancel")
def cancel_exam(id_):
    require({"Pathologist"})
    rec = lookup.autopsy_exam(id_)
    if rec["exam_status"] != "SCHEDULED":
        raise errors.err(errors.ERR_INVALID_STATE, "Cancel only allowed from SCHEDULED")
    rec["exam_status"] = "CANCELLED"
    touch(rec)
    return object_response(_view(rec), 200)
