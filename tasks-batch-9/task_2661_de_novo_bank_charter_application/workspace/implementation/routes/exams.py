"""Readiness examination scheduling and results."""
from flask import Blueprint

import calc
import cascade
import db
import response
import serialize
import validation as v
from errors import err
from middleware import authenticate
from routes.helpers import must_get

bp = Blueprint("exams", __name__)

EXAM_SCOPES = ("FULL_SCOPE", "TARGETED_FOLLOW_UP")
EXAM_OUTCOMES = ("PASSED", "DEFICIENT")


@bp.post("/de-novo/organizing-groups/<group_id>/readiness-exams")
def schedule_exam(group_id):
    authenticate(("CharteringExaminer",))
    data = v.body()
    window_start = v.req_dt(data, "window_start_utc")
    window_end = v.req_dt(data, "window_end_utc")
    exam_scope = v.req_enum(data, "exam_scope", EXAM_SCOPES)
    group = must_get("groups", group_id)
    if group["stage"] not in ("CONDITIONALLY_APPROVED", "PRE_OPENING"):
        raise err("ERR_GROUP_NOT_EXAM_READY")
    existing = calc.exams_of(group["id"])
    if exam_scope == "TARGETED_FOLLOW_UP":
        if not any(e["status"] == "DEFICIENT" for e in existing):
            raise err("ERR_NO_DEFICIENT_EXAM")
    else:
        for row in existing:
            if row["exam_scope"] == "FULL_SCOPE" and row["status"] in ("SCHEDULED", "PASSED"):
                raise err("ERR_FULL_SCOPE_EXAM_EXISTS")
    if window_end <= window_start:
        raise err("ERR_WINDOW_END_NOT_AFTER_START")
    if window_start < db.clock():
        raise err("ERR_WINDOW_START_IN_PAST")
    buffer_end = calc.exam_buffer_end(window_end)
    if calc.exam_window_conflict(group["id"], window_start, buffer_end):
        raise err("ERR_EXAM_WINDOW_CONFLICT")
    exam = db.insert("exams", {
        "group_id": group["id"],
        "window_start_utc": window_start,
        "window_end_utc": window_end,
        "exam_scope": exam_scope,
        "status": "SCHEDULED",
        "buffer_end_utc": buffer_end,
        "finding_count": 0,
    })
    db.touch(group)
    db.commit()
    return response.object_response(serialize.exam(exam), 201)


@bp.post("/de-novo/readiness-exams/<exam_id>/result")
def exam_result(exam_id):
    authenticate(("CharteringExaminer",))
    data = v.body()
    outcome = v.req_enum(data, "outcome", EXAM_OUTCOMES)
    finding_count = v.req_int(data, "finding_count", 0, None)
    exam = must_get("exams", exam_id)
    if exam["status"] != "SCHEDULED":
        raise err("ERR_EXAM_NOT_RESOLVABLE")
    group = db.get("groups", exam["group_id"])
    if group is None or group["stage"] != "PRE_OPENING":
        raise err("ERR_GROUP_NOT_IN_PRE_OPENING")
    if outcome == "PASSED" and finding_count > calc.MAX_PASSING_FINDINGS:
        raise err("ERR_FINDINGS_EXCEED_PASS_LIMIT")
    if db.clock() < exam["window_start_utc"]:
        raise err("ERR_EXAM_WINDOW_NOT_STARTED")
    exam["status"] = outcome
    exam["finding_count"] = finding_count
    db.touch(exam)
    if outcome == "DEFICIENT":
        cascade.exam_deficient_cascade(group)
    db.commit()
    return response.object_response(serialize.exam(exam))
