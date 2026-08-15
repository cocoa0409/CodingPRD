"""Examiner meetings and informal findings (PRD §3.4)."""
from flask import Blueprint, request

from db import db, new_id, next_seq, now, touch
from errors import (ApiError, ERR_ALREADY_TERMINAL, ERR_INVALID_REFERENCE,
                    ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_MEETING_DATE_CONFLICT)
from middleware import auth, require_role
from response import ok_obj
from serializers import ser_finding, ser_meeting
from util import (enum_filter, get_or_404, list_page, payload, parse_dt,
                  req_enum, req_str, req_dt)

bp = Blueprint("fieldwork", __name__)

RAM = "RegulatoryAffairsManager"
MEETING_STATUSES = ["DRAFT", "FINALIZED"]
SEVERITIES = ["LOW", "MODERATE", "HIGH", "CRITICAL"]


# ------------------------------------------------------------- meetings
@bp.post("/regulatory-exams/examiner-meetings")
def create_meeting():
    auth_pair = auth()
    require_role(auth_pair[1], RAM)
    p = payload()
    exam_id = p.get("examination_id")
    mdate = parse_dt(p.get("meeting_date"))
    # (9) meeting date collision vs FINALIZED meetings on the same examination
    if isinstance(exam_id, str) and mdate is not None:
        for m in db.meetings.values():
            if m["examination_id"] == exam_id and m["status"] == "FINALIZED" \
                    and m["meeting_date"].date() == mdate.date():
                raise ApiError(ERR_MEETING_DATE_CONFLICT, 422,
                               "a FINALIZED meeting already exists on that date")
    # (12) referential
    if isinstance(exam_id, str) and exam_id not in db.exams:
        raise ApiError(ERR_INVALID_REFERENCE, 422, "examination_id does not exist")
    # (14) shape
    exam_id = req_str(p, "examination_id")
    if exam_id not in db.exams:
        raise ApiError(ERR_INVALID_REFERENCE, 422, "examination_id does not exist")
    mdate = req_dt(p, "meeting_date")
    attendees = p.get("attendees")
    if not isinstance(attendees, list) or len(attendees) == 0 \
            or any(not isinstance(a, str) or not a for a in attendees):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "attendees must be a non-empty array of names")
    if "minutes_summary" not in p or not isinstance(p["minutes_summary"], str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "minutes_summary is required")
    rec = {"id": new_id(), "examination_id": exam_id, "meeting_date": mdate,
           "attendees": attendees, "minutes_summary": p["minutes_summary"],
           "status": "DRAFT",
           "created_at": now(), "updated_at": now(), "version": 1,
           "_seq": next_seq()}
    db.meetings[rec["id"]] = rec
    return ok_obj(ser_meeting(rec), 201)


@bp.get("/regulatory-exams/examiner-meetings")
def list_meetings():
    auth()
    exam_id = request.args.get("examination_id")
    status = enum_filter("status", MEETING_STATUSES)
    rows = [m for m in db.meetings.values()
            if (exam_id is None or m["examination_id"] == exam_id)
            and (status is None or m["status"] == status)]
    return list_page(rows, ser_meeting)


@bp.get("/regulatory-exams/examiner-meetings/<mid>")
def get_meeting(mid):
    auth()
    return ok_obj(ser_meeting(get_or_404(db.meetings, mid)))


@bp.post("/regulatory-exams/examiner-meetings/<mid>/finalize")
def finalize_meeting(mid):
    auth_pair = auth()
    require_role(auth_pair[1], RAM)
    m = get_or_404(db.meetings, mid)
    if m["status"] == "FINALIZED":
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "meeting already FINALIZED")
    if not m.get("minutes_summary", "").strip():
        raise ApiError(ERR_INVALID_STATE, 409, "minutes_summary must be non-empty")
    exam = db.exams[m["examination_id"]]
    if exam["status"] not in ("FIELDWORK", "FINDINGS_DELIVERED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "examination must be in FIELDWORK or FINDINGS_DELIVERED")
    m["status"] = "FINALIZED"
    touch(m)
    return ok_obj(ser_meeting(m))


# ------------------------------------------------------- informal findings
@bp.post("/regulatory-exams/examiner-meetings/<mid>/informal-findings")
def create_finding(mid):
    auth_pair = auth()
    require_role(auth_pair[1], RAM)
    m = get_or_404(db.meetings, mid)
    if m["status"] != "FINALIZED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "informal findings require a FINALIZED meeting")
    p = payload()
    text = req_str(p, "finding_text")
    hint = req_enum(p, "severity_hint", SEVERITIES)
    rec = {"id": new_id(), "examiner_meeting_id": mid, "finding_text": text,
           "severity_hint": hint, "promoted_issue_id": None,
           "created_at": now(), "updated_at": now(), "version": 1,
           "_seq": next_seq()}
    db.findings[rec["id"]] = rec
    return ok_obj(ser_finding(rec), 201)


@bp.get("/regulatory-exams/examiner-meetings/<mid>/informal-findings")
def list_findings_for_meeting(mid):
    auth()
    get_or_404(db.meetings, mid)
    rows = [f for f in db.findings.values() if f["examiner_meeting_id"] == mid]
    return list_page(rows, ser_finding)


@bp.get("/regulatory-exams/informal-findings/<fid>")
def get_finding(fid):
    auth()
    return ok_obj(ser_finding(get_or_404(db.findings, fid)))


@bp.get("/regulatory-exams/informal-findings")
def list_findings_portfolio():
    auth()
    pid = request.args.get("promoted_issue_id")
    rows = [f for f in db.findings.values()
            if pid is None or f["promoted_issue_id"] == pid]
    return list_page(rows, ser_finding)
