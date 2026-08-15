"""Interview endpoints (PRD §3.4)."""

from flask import Blueprint, request

from db import db, clock_now, fmt_iso, parse_iso
from middleware import get_auth, require_role, ALL_ROLES
from response import success_object, success_list, parse_pagination
from services.validate import (
    body, req_string, opt_string, req_enum, req_datetime, get_or_404,
)
from services.entities import make_interview, pub, touch
from services.calculations import compute_doc_stale
from errors import (
    err400, err403, err404, err409,
    ERR_INVALID_REQUEST, ERR_INVALID_STATE_TRANSITION, ERR_NOT_CASE_ASSIGNEE,
    ERR_INTERVIEWER_MISMATCH, ERR_INTERVIEW_OVERLAP, ERR_EMPLOYEE_NOT_ACTIVE,
    ERR_SUBJECT_MISMATCH,
)

bp = Blueprint("interviews", __name__)


@bp.route("/interviews", methods=["POST"])
def create_interview():
    user_id, role = get_auth()
    require_role(role, {"LPAnalyst"})
    data = body()
    case_id = req_string(data, "case_id")
    interviewer_id = req_string(data, "interviewer_id")
    scheduled_start = req_datetime(data, "scheduled_start")
    scheduled_end = req_datetime(data, "scheduled_end")
    subject_employee_id = opt_string(data, "subject_employee_id")

    # shape: scheduled_end strictly after scheduled_start
    if parse_iso(scheduled_end) <= parse_iso(scheduled_start):
        raise err400(ERR_INVALID_REQUEST,
                     "scheduled_end must be strictly after scheduled_start")

    # anchor existence (needed to evaluate ownership), then ownership (pri 3)
    case = get_or_404(db.cases, case_id, "case")
    if case.get("assigned_analyst_id") != user_id:
        raise err403(ERR_NOT_CASE_ASSIGNEE,
                     "Actor is not the case's assigned analyst")

    if subject_employee_id is not None:
        get_or_404(db.employees, subject_employee_id, "employee")

    if case["status"] not in ("INVESTIGATING", "READY_FOR_INTERVIEW"):
        raise err409(ERR_INVALID_STATE_TRANSITION,
                     "Case must be INVESTIGATING or READY_FOR_INTERVIEW")

    # employee consistency: subject_employee_id on employee-subject cases
    if subject_employee_id is not None:
        emp = db.employees[subject_employee_id]
        if emp["status"] == "TERMINATED":
            raise err409(ERR_EMPLOYEE_NOT_ACTIVE, "Employee is TERMINATED")
        if case["subject_type"] == "EMPLOYEE" and case.get("employee_id") != subject_employee_id:
            raise err409(ERR_SUBJECT_MISMATCH,
                         "subject_employee_id must equal the case's employee_id")

    # overlap: half-open [start, end), touching allowed; against SCHEDULED/HELD
    # interviews for the same employee.
    if subject_employee_id is not None:
        new_start = parse_iso(scheduled_start)
        new_end = parse_iso(scheduled_end)
        for iv in db.interviews.values():
            if iv.get("subject_employee_id") != subject_employee_id:
                continue
            if iv["status"] not in ("SCHEDULED", "HELD"):
                continue
            ex_start = parse_iso(iv["scheduled_start"])
            ex_end = parse_iso(iv["scheduled_end"])
            if new_start < ex_end and ex_start < new_end:
                raise err409(ERR_INTERVIEW_OVERLAP,
                             "Interview window overlaps another interview for this "
                             "employee")

    iv = make_interview(case_id, interviewer_id, subject_employee_id,
                        scheduled_start, scheduled_end)
    db.interviews[iv["id"]] = iv
    return success_object(pub(iv), status=201)


@bp.route("/interviews", methods=["GET"])
def list_interviews():
    user_id, role = get_auth()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    case_id = _q("case_id")
    interviewer_id = _q("interviewer_id")
    subject_employee_id = _q("subject_employee_id")
    status = _q("status")
    items = sorted(db.interviews.values(), key=lambda i: (i["created_at"], i["id"]))
    if case_id is not None:
        items = [i for i in items if i["case_id"] == case_id]
    if interviewer_id is not None:
        items = [i for i in items if i["interviewer_id"] == interviewer_id]
    if subject_employee_id is not None:
        items = [i for i in items if i.get("subject_employee_id") == subject_employee_id]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([pub(i) for i in page], limit, offset, total)


@bp.route("/interviews/<interview_id>", methods=["GET"])
def get_interview(interview_id):
    user_id, role = get_auth()
    require_role(role, ALL_ROLES)
    iv = get_or_404(db.interviews, interview_id, "interview")
    return success_object(pub(iv))


@bp.route("/interviews/<interview_id>/record-outcome", methods=["POST"])
def record_outcome(interview_id):
    user_id, role = get_auth()
    require_role(role, {"LPAnalyst"})
    data = body()
    outcome = req_enum(data, "outcome",
                       ["ADMITTED", "DENIED", "PARTIAL", "NO_SHOW"])
    iv = get_or_404(db.interviews, interview_id, "interview")
    if iv["interviewer_id"] != user_id:
        raise err403(ERR_INTERVIEWER_MISMATCH,
                     "Actor is not the interview's interviewer")
    if iv["status"] != "SCHEDULED":
        raise err409(ERR_INVALID_STATE_TRANSITION,
                     "Interview must be SCHEDULED to record an outcome")
    iv["outcome"] = outcome
    if outcome == "NO_SHOW":
        iv["status"] = "NO_SHOW"
    else:
        iv["status"] = "HELD"
        iv["conducted_at"] = fmt_iso(clock_now())
    touch(iv)
    return success_object(pub(iv))


@bp.route("/interviews/<interview_id>/document", methods=["POST"])
def document_interview(interview_id):
    user_id, role = get_auth()
    require_role(role, {"LPAnalyst"})
    data = body()
    notes = req_string(data, "notes")
    iv = get_or_404(db.interviews, interview_id, "interview")
    if iv["interviewer_id"] != user_id:
        raise err403(ERR_INTERVIEWER_MISMATCH,
                     "Actor is not the interview's interviewer")
    if iv["status"] != "HELD":
        raise err409(ERR_INVALID_STATE_TRANSITION,
                     "Interview must be HELD to document")
    now_iso = fmt_iso(clock_now())
    iv["notes"] = notes
    iv["documented_at"] = now_iso
    iv["doc_stale"] = compute_doc_stale(iv["conducted_at"], now_iso)
    iv["status"] = "DOCUMENTED"
    touch(iv)
    case = db.cases.get(iv["case_id"])
    if case is not None and case["status"] == "READY_FOR_INTERVIEW":
        case["status"] = "INTERVIEWED"
        touch(case)
    return success_object(pub(iv))


@bp.route("/interviews/<interview_id>/cancel", methods=["POST"])
def cancel_interview(interview_id):
    user_id, role = get_auth()
    require_role(role, {"LPAnalyst"})
    iv = get_or_404(db.interviews, interview_id, "interview")
    if iv["status"] != "SCHEDULED":
        raise err409(ERR_INVALID_STATE_TRANSITION,
                     "Interview must be SCHEDULED to cancel")
    iv["status"] = "CANCELLED"
    touch(iv)
    return success_object(pub(iv))


def _q(name):
    v = request.args.get(name)
    return v if v not in (None, "") else None
