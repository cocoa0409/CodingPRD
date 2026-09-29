"""Duties validation interviews (PRD 3.3)."""
from flask import Blueprint

import db
from constants import ALL_ROLES, RESPONDENT_TYPES
from errors import fail
from middleware import body, endpoint
from response import success
from services import derive, lookup, serialize
from validation import parse_datetime, req_bool, req_enum, req_int, req_num, req_str

bp = Blueprint("interviews", __name__)

LIVE_STATUSES = ("SCHEDULED", "COMPLETED", "ATTESTED")


def _require_fieldwork(position):
    project = derive.project_of_position(position)
    if project is None or project["status"] != "FIELDWORK":
        fail("ERR_PROJECT_STAGE_INVALID")
    return project


@bp.post("/interviews")
@endpoint(["ComplianceAnalyst"])
def create_interview():
    payload = body()
    position_id = req_str(payload, "position_id")
    respondent_type = req_enum(payload, "respondent_type", RESPONDENT_TYPES)
    respondent_ref = req_str(payload, "respondent_ref")
    interviewer_user_id = req_str(payload, "interviewer_user_id")
    raw_start = req_str(payload, "scheduled_start_at")
    raw_end = req_str(payload, "scheduled_end_at")
    start = parse_datetime(raw_start, "scheduled_start_at")
    end = parse_datetime(raw_end, "scheduled_end_at")
    if end <= start:
        fail(
            "ERR_INVALID_REQUEST",
            "scheduled_end_at must be strictly later than scheduled_start_at.",
        )

    # rank 5: foreign key
    position = lookup.position(position_id)

    # rank 7: booking is a FIELDWORK-only act
    _require_fieldwork(position)

    # rank 13: at most one live interview per (position, respondent_type)
    for existing in derive.interviews_of(position["id"]):
        if (
            existing["respondent_type"] == respondent_type
            and existing["status"] != "VOIDED"
        ):
            fail("ERR_DUPLICATE_INTERVIEW_RESPONDENT")

    # rank 14: the interviewer's calendar, half-open, across every engagement
    for existing in db.interviews.values():
        if existing["interviewer_user_id"] != interviewer_user_id:
            continue
        if existing["status"] not in LIVE_STATUSES:
            continue
        if start < existing["_end"] and existing["_start"] < end:
            fail("ERR_INTERVIEWER_DOUBLE_BOOKED")

    row = db.make_row(
        position_id=position["id"],
        respondent_type=respondent_type,
        respondent_ref=respondent_ref,
        interviewer_user_id=interviewer_user_id,
        scheduled_start_at=raw_start,
        scheduled_end_at=raw_end,
        _start=start,
        _end=end,
        reported_exempt_duty_pct=None,
        reported_weekly_hours=None,
        supervises_headcount=None,
        has_hire_fire_influence=None,
        completed_at=None,
        attested_at=None,
        void_reason=None,
        status="SCHEDULED",
    )
    db.interviews[row["id"]] = row
    return success(serialize.interview(row), 201)


@bp.get("/interviews/<interview_id>")
@endpoint(ALL_ROLES)
def get_interview(interview_id):
    interview = lookup.interview(interview_id)
    return success(serialize.interview(interview), 200)


@bp.post("/interviews/<interview_id>/complete")
@endpoint(["ComplianceAnalyst"])
def complete_interview(interview_id):
    interview = lookup.interview(interview_id)
    payload = body()
    exempt_pct = req_num(payload, "reported_exempt_duty_pct", minimum=0, maximum=100)
    weekly_hours = req_num(payload, "reported_weekly_hours", minimum=0, maximum=168)
    supervises = req_int(payload, "supervises_headcount", minimum=0)
    hire_fire = req_bool(payload, "has_hire_fire_influence")

    position = lookup.position(interview["position_id"])

    # rank 7: completion is a FIELDWORK-only act
    _require_fieldwork(position)

    # rank 8: declared transition SCHEDULED -> COMPLETED
    if interview["status"] != "SCHEDULED":
        fail("ERR_INVALID_STATE_TRANSITION")

    interview["reported_exempt_duty_pct"] = exempt_pct
    interview["reported_weekly_hours"] = weekly_hours
    interview["supervises_headcount"] = supervises
    interview["has_hire_fire_influence"] = hire_fire
    interview["completed_at"] = db.now_iso()
    interview["status"] = "COMPLETED"
    db.touch(interview)
    return success(serialize.interview(interview), 200)


@bp.post("/interviews/<interview_id>/attest")
@endpoint(["ComplianceAnalyst"])
def attest_interview(interview_id):
    interview = lookup.interview(interview_id)

    # rank 8: declared transition COMPLETED -> ATTESTED
    if interview["status"] != "COMPLETED":
        if interview["completed_at"] is None:
            fail("ERR_INTERVIEW_NOT_STARTED")
        fail("ERR_INVALID_STATE_TRANSITION")

    interview["attested_at"] = db.now_iso()
    interview["status"] = "ATTESTED"
    db.touch(interview)

    # attestation is where corroboration happens: position, family, engagement
    position = lookup.position(interview["position_id"])
    lookup.touch_position_chain(position)
    return success(serialize.interview(interview), 200)


@bp.post("/interviews/<interview_id>/void")
@endpoint(["ClassificationReviewer"])
def void_interview(interview_id):
    interview = lookup.interview(interview_id)
    payload = body()
    void_reason = req_str(payload, "void_reason")

    # rank 8: VOIDED is terminal
    previous = interview["status"]
    if previous not in LIVE_STATUSES:
        fail("ERR_INVALID_STATE_TRANSITION")

    interview["void_reason"] = void_reason
    interview["status"] = "VOIDED"
    db.touch(interview)

    position = lookup.position(interview["position_id"])
    if previous == "COMPLETED":
        db.touch(position)
    elif previous == "ATTESTED":
        lookup.touch_position_chain(position, include_project=False)
    return success(serialize.interview(interview), 200)
