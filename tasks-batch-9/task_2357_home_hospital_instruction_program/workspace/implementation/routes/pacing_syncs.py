"""Curriculum pacing coordination with the campus classroom teacher (PRD §3.9)."""

from flask import Blueprint

import clock
import db
import middleware
from errors import ApiError
from middleware import endpoint
from routes import ACCOMMODATIONS, ACK_STATUSES, IN_SERVICE, SUBJECTS, listing
from services import logic

bp = Blueprint("pacing_syncs", __name__)

READ_ROLES = [
    "ProgramAdministrator",
    "CaseManager",
    "ClassroomTeacher",
    "HomeboundTeacher",
]

CREATE_BODY = {
    "case_id": {"type": "string", "required": True},
    "classroom_teacher_id": {"type": "string", "required": True},
    "subject": {"type": "string", "required": True, "enum": SUBJECTS},
    "pacing_target_unit": {"type": "string", "required": True},
    "assessment_accommodation": {
        "type": "string",
        "required": True,
        "enum": ACCOMMODATIONS,
    },
}

LIST_QUERY = {
    "case_id": {"type": "string"},
    "classroom_teacher_id": {"type": "string"},
    "ack_status": {"type": "string", "enum": ACK_STATUSES},
    "subject": {"type": "string", "enum": SUBJECTS},
}


def load_sync(sync_id):
    row = db.get("pacing_syncs", sync_id)
    if row is None:
        raise ApiError("ERR_PACING_SYNC_NOT_FOUND")
    return row


@bp.post("/hhi/pacing-syncs")
@endpoint(["CaseManager"], body=CREATE_BODY, status=201)
def create_sync():
    body = middleware.body()

    case = db.get("cases", body["case_id"])                       # tier 5: case first
    if case is None:
        raise ApiError("ERR_CASE_NOT_FOUND")
    teacher = db.get("teachers", body["classroom_teacher_id"])
    if teacher is None:
        raise ApiError("ERR_TEACHER_NOT_FOUND")

    if case["service_status"] not in IN_SERVICE:                  # tier 8
        raise ApiError("ERR_CASE_NOT_ACTIVE")

    for other in db.by_case("pacing_syncs", case["id"]):          # tier 11
        if other["subject"] == body["subject"]:
            raise ApiError("ERR_DUPLICATE_PACING_SUBJECT")

    row = db.insert(
        "pacing_syncs",
        {
            "case_id": case["id"],
            "classroom_teacher_id": teacher["id"],
            "subject": body["subject"],
            "pacing_target_unit": body["pacing_target_unit"],
            "assessment_accommodation": body["assessment_accommodation"],
            "ack_status": "PENDING",
            "acked_at": None,
            "dispute_note": None,
        },
    )

    logic.recompute_ack_counters(case)
    return middleware.obj(row)


@bp.get("/hhi/pacing-syncs/<sync_id>")
@endpoint(READ_ROLES)
def read_sync(sync_id):
    return middleware.obj(load_sync(sync_id))


@bp.get("/hhi/pacing-syncs")
@endpoint(READ_ROLES, query=LIST_QUERY)
def list_syncs():
    return listing("pacing_syncs", LIST_QUERY)


@bp.post("/hhi/pacing-syncs/<sync_id>/acknowledge")
@endpoint(["ClassroomTeacher"])
def acknowledge_sync(sync_id):
    sync = load_sync(sync_id)
    if sync["classroom_teacher_id"] != middleware.user_id():      # tier 6
        raise ApiError("ERR_NOT_CLASSROOM_TEACHER_OF_RECORD")
    if sync["ack_status"] not in ("PENDING", "DISPUTED"):         # tier 8
        raise ApiError("ERR_PACING_ALREADY_ACKED")

    db.set_field(sync, "ack_status", "ACKED")
    db.set_field(sync, "acked_at", clock.instant_str())
    logic.recompute_ack_counters(db.get("cases", sync["case_id"]))
    return middleware.obj(sync)


@bp.post("/hhi/pacing-syncs/<sync_id>/dispute")
@endpoint(["ClassroomTeacher"], body={"dispute_note": {"type": "string", "required": True}})
def dispute_sync(sync_id):
    sync = load_sync(sync_id)
    if sync["classroom_teacher_id"] != middleware.user_id():      # tier 6
        raise ApiError("ERR_NOT_CLASSROOM_TEACHER_OF_RECORD")
    if sync["ack_status"] != "PENDING":                           # tier 8
        raise ApiError("ERR_PACING_ALREADY_ACKED")

    db.set_field(sync, "ack_status", "DISPUTED")
    db.set_field(sync, "dispute_note", middleware.body()["dispute_note"])
    logic.recompute_ack_counters(db.get("cases", sync["case_id"]))
    return middleware.obj(sync)
