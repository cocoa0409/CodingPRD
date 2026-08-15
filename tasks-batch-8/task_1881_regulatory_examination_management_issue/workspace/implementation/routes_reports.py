"""Board reports and the regulator commitment log (PRD §3.8-§3.9)."""
from flask import Blueprint, request

from db import db, new_id, next_seq, now, touch
from errors import (ApiError, ERR_ALREADY_TERMINAL, ERR_INVALID_DATE_RANGE,
                    ERR_INVALID_REFERENCE, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE)
from middleware import auth, require_role
from response import ok_obj
from serializers import ser_commitment, ser_report
from util import (enum_filter, get_or_404, list_page, payload, parse_dt,
                  req_dt, req_str)

bp = Blueprint("reports", __name__)

RAM = "RegulatoryAffairsManager"
REPORTER = "BoardReporter"
REPORT_STATUSES = ["DRAFT", "FINALIZED"]


# ------------------------------------------------------------ board reports
@bp.post("/regulatory-exams/board-reports")
def create_report():
    auth_pair = auth()
    require_role(auth_pair[1], REPORTER)
    p = payload()
    s = parse_dt(p.get("reporting_period_start"))
    e = parse_dt(p.get("reporting_period_end"))
    # (10) date-range sanity: end on or after start
    if s is not None and e is not None and e < s:
        raise ApiError(ERR_INVALID_DATE_RANGE, 400,
                       "reporting_period_end must be on or after start")
    # (12) referential
    exam_id = p.get("examination_id")
    if exam_id is not None:
        if not isinstance(exam_id, str):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "examination_id must be a string")
        if exam_id not in db.exams:
            raise ApiError(ERR_INVALID_REFERENCE, 422,
                           "examination_id does not exist")
    # (14) shape
    exam_id = req_str(p, "examination_id")
    s = req_dt(p, "reporting_period_start")
    e = req_dt(p, "reporting_period_end")
    exam = db.exams[exam_id]
    issues = [i for i in db.issues.values() if i["examination_id"] == exam_id]
    rec = {"id": new_id(), "examination_id": exam_id,
           "reporting_period_start": s, "reporting_period_end": e,
           "open_issue_count": sum(1 for i in issues if i["status"] != "CLOSED"),
           "overdue_issue_count": sum(1 for i in issues if i["status"] == "OVERDUE"),
           "escalated_issue_count": sum(1 for i in issues if i["escalated_to_board"]),
           "total_repeat_finding_risk_bp": exam["repeat_finding_risk_score_bp"],
           "status": "DRAFT",
           "created_at": now(), "updated_at": now(), "version": 1,
           "_seq": next_seq()}
    db.reports[rec["id"]] = rec
    touch(exam)
    return ok_obj(ser_report(rec), 201)


@bp.get("/regulatory-exams/board-reports")
def list_reports():
    auth()
    exam_id = request.args.get("examination_id")
    status = enum_filter("status", REPORT_STATUSES)
    rows = [r for r in db.reports.values()
            if (exam_id is None or r["examination_id"] == exam_id)
            and (status is None or r["status"] == status)]
    return list_page(rows, ser_report)


@bp.get("/regulatory-exams/board-reports/<rid>")
def get_report(rid):
    auth()
    return ok_obj(ser_report(get_or_404(db.reports, rid)))


@bp.post("/regulatory-exams/board-reports/<rid>/finalize")
def finalize_report(rid):
    auth_pair = auth()
    require_role(auth_pair[1], REPORTER)
    rec = get_or_404(db.reports, rid)
    if rec["status"] == "FINALIZED":
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "report already FINALIZED")
    rec["status"] = "FINALIZED"
    touch(rec)
    return ok_obj(ser_report(rec))


# -------------------------------------------------------------- commitments
@bp.post("/regulatory-exams/examinations/<eid>/commitments")
def create_commitment(eid):
    auth_pair = auth()
    require_role(auth_pair[1], RAM)
    exam = get_or_404(db.exams, eid)
    p = payload()
    # (12) referential: committed_by_user_id -> BankOfficer
    cby = p.get("committed_by_user_id")
    if cby is not None:
        if not isinstance(cby, str):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "committed_by_user_id must be a string")
        if cby not in db.officers:
            raise ApiError(ERR_INVALID_REFERENCE, 422,
                           "committed_by_user_id does not reference a BankOfficer")
    # (14) shape
    text = req_str(p, "commitment_text")
    cby = req_str(p, "committed_by_user_id")
    due = req_dt(p, "due_date")
    rec = {"id": new_id(), "examination_id": eid, "commitment_text": text,
           "committed_by_user_id": cby, "committed_at": now(),
           "due_date": due, "fulfilled_at": None,
           "created_at": now(), "_seq": next_seq()}
    db.commitments[rec["id"]] = rec
    touch(exam)
    return ok_obj(ser_commitment(rec), 201)


@bp.get("/regulatory-exams/examinations/<eid>/commitments")
def list_commitments_for_exam(eid):
    auth()
    get_or_404(db.exams, eid)
    rows = [c for c in db.commitments.values() if c["examination_id"] == eid]
    return list_page(rows, ser_commitment)


@bp.get("/regulatory-exams/commitments")
def list_commitments_portfolio():
    auth()
    cby = request.args.get("committed_by_user_id")
    rows = [c for c in db.commitments.values()
            if cby is None or c["committed_by_user_id"] == cby]
    return list_page(rows, ser_commitment)


@bp.get("/regulatory-exams/commitments/<cid>")
def get_commitment(cid):
    auth()
    return ok_obj(ser_commitment(get_or_404(db.commitments, cid)))


@bp.post("/regulatory-exams/commitments/<cid>/fulfill")
def fulfill_commitment(cid):
    auth_pair = auth()
    require_role(auth_pair[1], RAM)
    rec = get_or_404(db.commitments, cid)
    if rec["fulfilled_at"] is not None:
        raise ApiError(ERR_INVALID_STATE, 409, "commitment already fulfilled")
    rec["fulfilled_at"] = now()  # write-once stamp; entry itself is immutable
    exam = db.exams.get(rec["examination_id"])
    if exam is not None:
        touch(exam)
    return ok_obj(ser_commitment(rec))
