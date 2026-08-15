"""Examinations, lifecycle transitions, first-day items, document submissions,
risk history."""
from flask import Blueprint

from calc import first_day_due, maybe_advance_exam, recompute_exam, risk_historical
from db import db, new_id, next_seq, now, touch
from errors import (ApiError, ERR_ALREADY_TERMINAL, ERR_COMMITMENT_OUTSTANDING,
                    ERR_DUPLICATE_KEY, ERR_EXAM_POSTURE_FROZEN,
                    ERR_EXAM_SCHEDULE_OVERLAP, ERR_INVALID_DATE_RANGE,
                    ERR_INVALID_REFERENCE, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE, ERR_OPEN_ISSUES_REMAIN)
from middleware import auth, require_role, reviewer_gate
from response import ok_obj
from serializers import ser_exam, ser_item, ser_submission
from util import (enum_filter, get_or_404, list_page, payload, parse_dt,
                  req_enum, req_str, req_dt)

bp = Blueprint("exams", __name__)

EXAM_TYPES = ["SAFETY_SOUNDNESS", "COMPLIANCE", "IT", "TRUST", "SPECIALTY"]
EXAM_STATUSES = ["SCHEDULED", "FIRST_DAY_ISSUED", "FIELDWORK",
                 "FINDINGS_DELIVERED", "REMEDIATION", "VALIDATION", "CLOSED",
                 "CANCELLED"]
POSTURES = ["NORMAL", "RESTRICTED", "FROZEN"]
ITEM_STATUSES = ["PENDING", "SUBMITTED", "WAIVED"]
QUALITY_STATUSES = ["PENDING_REVIEW", "ACCEPTED", "REJECTED"]
RAM = "RegulatoryAffairsManager"


# ----------------------------------------------------------- examinations
@bp.post("/regulatory-exams/examinations")
def create_examination():
    auth_pair = auth()
    require_role(auth_pair[1], RAM)
    p = payload()
    agency_id = p.get("agency_id")
    s = parse_dt(p.get("scheduled_start_date"))
    e = parse_dt(p.get("scheduled_end_date"))
    # (8) schedule overlap — half-open intervals; adjacent windows do not collide.
    if isinstance(agency_id, str) and s is not None and e is not None:
        for ex in db.exams.values():
            if ex["agency_id"] != agency_id:
                continue
            if ex["status"] in ("CANCELLED", "CLOSED"):
                continue
            if s < ex["scheduled_end_date"] and ex["scheduled_start_date"] < e:
                raise ApiError(ERR_EXAM_SCHEDULE_OVERLAP, 422,
                               "examination window overlaps an existing live examination")
    # (10) date-range sanity
    if s is not None and e is not None and not e > s:
        raise ApiError(ERR_INVALID_DATE_RANGE, 400,
                       "scheduled_end_date must be strictly after scheduled_start_date")
    # (12) referential integrity
    if isinstance(agency_id, str):
        agency = db.agencies.get(agency_id)
        if agency is None:
            raise ApiError(ERR_INVALID_REFERENCE, 422, "agency_id does not exist")
        if not agency.get("active", True):
            raise ApiError(ERR_INVALID_REFERENCE, 422, "agency is inactive")
    # (14) request shape
    agency_id = req_str(p, "agency_id")
    cycle = req_str(p, "exam_cycle_code")
    etype = req_enum(p, "exam_type", EXAM_TYPES)
    s = req_dt(p, "scheduled_start_date")
    e = req_dt(p, "scheduled_end_date")
    rec = {"id": new_id(), "agency_id": agency_id, "exam_cycle_code": cycle,
           "exam_type": etype, "status": "SCHEDULED",
           "scheduled_start_date": s, "scheduled_end_date": e,
           "first_day_letter_due_date": first_day_due(s),
           "posture": "NORMAL", "repeat_finding_risk_score_bp": 0,
           "overdue_item_count": 0, "cancelled_reason": None,
           "created_at": now(), "updated_at": now(), "version": 1,
           "_seq": next_seq()}
    db.exams[rec["id"]] = rec
    return ok_obj(ser_exam(rec), 201)


@bp.get("/regulatory-exams/examinations")
def list_examinations():
    auth()
    from flask import request
    agency_id = request.args.get("agency_id")
    status = enum_filter("status", EXAM_STATUSES)
    posture = enum_filter("posture", POSTURES)
    rows = [x for x in db.exams.values()
            if (agency_id is None or x["agency_id"] == agency_id)
            and (status is None or x["status"] == status)
            and (posture is None or x["posture"] == posture)]
    return list_page(rows, ser_exam)


@bp.get("/regulatory-exams/examinations/<eid>")
def get_examination(eid):
    auth()
    return ok_obj(ser_exam(get_or_404(db.exams, eid)))


def _exam_for_action(eid):
    exam = get_or_404(db.exams, eid)
    if exam["status"] in ("CLOSED", "CANCELLED"):
        raise ApiError(ERR_ALREADY_TERMINAL, 409,
                       "examination is in a terminal state")
    return exam


def _transit(exam, to):
    exam["status"] = to
    touch(exam)
    return ok_obj(ser_exam(exam))


@bp.post("/regulatory-exams/examinations/<eid>/issue-first-day-letter")
def issue_first_day_letter(eid):
    auth_pair = auth()
    require_role(auth_pair[1], RAM)
    exam = _exam_for_action(eid)
    if exam["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409, "examination is not SCHEDULED")
    if not any(i["examination_id"] == eid for i in db.items.values()):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "at least one first-day item must exist")
    return _transit(exam, "FIRST_DAY_ISSUED")


@bp.post("/regulatory-exams/examinations/<eid>/begin-fieldwork")
def begin_fieldwork(eid):
    auth_pair = auth()
    require_role(auth_pair[1], RAM)
    exam = _exam_for_action(eid)
    if exam["status"] != "FIRST_DAY_ISSUED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "examination is not FIRST_DAY_ISSUED")
    if any(i["examination_id"] == eid and i["status"] == "PENDING"
           for i in db.items.values()):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "all first-day items must be SUBMITTED or WAIVED")
    return _transit(exam, "FIELDWORK")


@bp.post("/regulatory-exams/examinations/<eid>/deliver-findings")
def deliver_findings(eid):
    auth_pair = auth()
    require_role(auth_pair[1], RAM)
    exam = _exam_for_action(eid)
    if exam["status"] != "FIELDWORK":
        raise ApiError(ERR_INVALID_STATE, 409, "examination is not FIELDWORK")
    if not any(m["examination_id"] == eid and m["status"] == "FINALIZED"
               for m in db.meetings.values()):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "at least one FINALIZED examiner meeting is required")
    return _transit(exam, "FINDINGS_DELIVERED")


@bp.post("/regulatory-exams/examinations/<eid>/open-remediation")
def open_remediation(eid):
    auth_pair = auth()
    require_role(auth_pair[1], RAM)
    exam = _exam_for_action(eid)
    if exam["status"] != "FINDINGS_DELIVERED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "examination is not FINDINGS_DELIVERED")
    if not any(i["examination_id"] == eid for i in db.issues.values()):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "at least one issue must exist")
    return _transit(exam, "REMEDIATION")


@bp.post("/regulatory-exams/examinations/<eid>/close")
def close_examination(eid):
    auth_pair = auth()
    require_role(auth_pair[1], RAM)
    exam = _exam_for_action(eid)
    if exam["status"] != "VALIDATION":
        raise ApiError(ERR_INVALID_STATE, 409, "examination is not VALIDATION")
    if any(i["examination_id"] == eid and i["status"] != "CLOSED"
           for i in db.issues.values()):
        raise ApiError(ERR_OPEN_ISSUES_REMAIN, 422,
                       "issues remain that are not CLOSED")
    if any(c["examination_id"] == eid and c["fulfilled_at"] is None
           for c in db.commitments.values()):
        raise ApiError(ERR_COMMITMENT_OUTSTANDING, 422,
                       "unfulfilled commitments remain")
    return _transit(exam, "CLOSED")


@bp.post("/regulatory-exams/examinations/<eid>/cancel")
def cancel_examination(eid):
    auth_pair = auth()
    require_role(auth_pair[1], RAM)
    exam = _exam_for_action(eid)
    if exam["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409, "examination is not SCHEDULED")
    reason = req_str(payload(), "cancelled_reason")
    exam["cancelled_reason"] = reason
    return _transit(exam, "CANCELLED")


@bp.get("/regulatory-exams/examinations/<eid>/risk-history")
def risk_history(eid):
    auth()
    exam = get_or_404(db.exams, eid)
    score, ids = risk_historical(exam)
    return ok_obj({"historical_risk_bp": score, "contributing_issue_ids": ids})


# ------------------------------------------------------- first-day items
@bp.post("/regulatory-exams/examinations/<eid>/first-day-items")
def create_first_day_item(eid):
    auth_pair = auth()
    require_role(auth_pair[1], RAM)
    exam = get_or_404(db.exams, eid)
    p = payload()
    # (11) uniqueness of request_ref within the examination
    ref = p.get("request_ref")
    if isinstance(ref, str):
        for it in db.items.values():
            if it["examination_id"] == eid and it["request_ref"] == ref:
                raise ApiError(ERR_DUPLICATE_KEY, 409,
                               "request_ref already exists on this examination")
    # (13) posture gate: RESTRICTED or FROZEN blocks new first-day items
    if exam["posture"] != "NORMAL":
        raise ApiError(ERR_EXAM_POSTURE_FROZEN, 422,
                       "examination posture blocks new first-day items")
    # (14) shape
    ref = req_str(p, "request_ref")
    desc = req_str(p, "description")
    due = req_dt(p, "due_date")
    rec = {"id": new_id(), "examination_id": eid, "request_ref": ref,
           "description": desc, "due_date": due, "status": "PENDING",
           "submitted_at": None, "waived_reason": None,
           "created_at": now(), "updated_at": now(), "version": 1,
           "_seq": next_seq()}
    db.items[rec["id"]] = rec
    recompute_exam(exam)
    touch(exam)
    return ok_obj(ser_item(rec), 201)


@bp.get("/regulatory-exams/examinations/<eid>/first-day-items")
def list_first_day_items(eid):
    auth()
    get_or_404(db.exams, eid)
    status = enum_filter("status", ITEM_STATUSES)
    rows = [i for i in db.items.values()
            if i["examination_id"] == eid
            and (status is None or i["status"] == status)]
    return list_page(rows, ser_item)


@bp.get("/regulatory-exams/first-day-items/<iid>")
def get_first_day_item(iid):
    auth()
    return ok_obj(ser_item(get_or_404(db.items, iid)))


@bp.post("/regulatory-exams/first-day-items/<iid>/waive")
def waive_first_day_item(iid):
    auth_pair = auth()
    require_role(auth_pair[1], RAM)
    item = get_or_404(db.items, iid)
    if item["status"] in ("SUBMITTED", "WAIVED"):
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "item is already terminal")
    reason = req_str(payload(), "waived_reason")
    item["status"] = "WAIVED"
    item["waived_reason"] = reason
    touch(item)
    exam = db.exams[item["examination_id"]]
    recompute_exam(exam)
    touch(exam)
    return ok_obj(ser_item(item))


# ---------------------------------------------------- document submissions
@bp.post("/regulatory-exams/first-day-items/<iid>/submissions")
def create_submission(iid):
    auth_pair = auth()
    require_role(auth_pair[1], "RemediationOwner")
    item = get_or_404(db.items, iid)
    exam = db.exams[item["examination_id"]]
    p = payload()
    # (13) posture gate: FROZEN blocks new document submissions
    if exam["posture"] == "FROZEN":
        raise ApiError(ERR_EXAM_POSTURE_FROZEN, 422,
                       "examination posture FROZEN blocks document submissions")
    # (14) shape
    manifest = p.get("document_manifest")
    if not isinstance(manifest, list) or len(manifest) == 0:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "document_manifest must be a non-empty array")
    for d in manifest:
        if not isinstance(d, dict):
            raise ApiError(ERR_INVALID_REQUEST, 400, "manifest entries must be objects")
        for k in ("doc_id", "title", "sha256"):
            if not isinstance(d.get(k), str) or not d.get(k):
                raise ApiError(ERR_INVALID_REQUEST, 400,
                               "manifest entry missing %s" % k)
        if not isinstance(d.get("page_count"), int) \
                or isinstance(d.get("page_count"), bool):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "manifest entry page_count must be an integer")
    round_n = 1 + sum(1 for s in db.submissions.values()
                      if s["first_day_item_id"] == iid)
    rec = {"id": new_id(), "first_day_item_id": iid,
           "submission_round": round_n, "document_manifest": manifest,
           "quality_status": "PENDING_REVIEW", "quality_reject_reason": None,
           "page_count_total": sum(d["page_count"] for d in manifest),
           "created_at": now(), "updated_at": now(), "version": 1,
           "_seq": next_seq()}
    db.submissions[rec["id"]] = rec
    touch(item)
    touch(exam)
    return ok_obj(ser_submission(rec), 201)


@bp.get("/regulatory-exams/first-day-items/<iid>/submissions")
def list_submissions(iid):
    auth()
    get_or_404(db.items, iid)
    qs = enum_filter("quality_status", QUALITY_STATUSES)
    rows = [s for s in db.submissions.values()
            if s["first_day_item_id"] == iid
            and (qs is None or s["quality_status"] == qs)]
    return list_page(rows, ser_submission)


@bp.get("/regulatory-exams/document-submissions/<sid>")
def get_submission(sid):
    auth()
    return ok_obj(ser_submission(get_or_404(db.submissions, sid)))


@bp.post("/regulatory-exams/document-submissions/<sid>/accept")
def accept_submission(sid):
    uid, role = auth()
    require_role(role, "ComplianceReviewer")
    reviewer_gate(uid)
    sub = get_or_404(db.submissions, sid)
    if sub["quality_status"] in ("ACCEPTED", "REJECTED"):
        raise ApiError(ERR_ALREADY_TERMINAL, 409,
                       "submission already adjudicated")
    item = db.items[sub["first_day_item_id"]]
    exam = db.exams[item["examination_id"]]
    if item["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, 409, "parent item is not PENDING")
    if exam["status"] not in ("FIRST_DAY_ISSUED", "FIELDWORK"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "examination is not accepting submissions")
    if exam["posture"] == "FROZEN":
        raise ApiError(ERR_INVALID_STATE, 409, "examination posture is FROZEN")
    sub["quality_status"] = "ACCEPTED"
    touch(sub)
    item["status"] = "SUBMITTED"
    item["submitted_at"] = now()
    touch(item)
    recompute_exam(exam)
    touch(exam)
    return ok_obj(ser_submission(sub))


@bp.post("/regulatory-exams/document-submissions/<sid>/reject")
def reject_submission(sid):
    uid, role = auth()
    require_role(role, "ComplianceReviewer")
    reviewer_gate(uid)
    sub = get_or_404(db.submissions, sid)
    if sub["quality_status"] in ("ACCEPTED", "REJECTED"):
        raise ApiError(ERR_ALREADY_TERMINAL, 409,
                       "submission already adjudicated")
    reason = req_str(payload(), "quality_reject_reason")
    sub["quality_status"] = "REJECTED"
    sub["quality_reject_reason"] = reason
    touch(sub)
    return ok_obj(ser_submission(sub))
