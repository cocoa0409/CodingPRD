"""Regulatory exams and findings (PRD 3.9), including the supervisory cascade."""
from flask import Blueprint, request

import db
import serialize as ser
from errors import (
    not_found, invalid_state, raise_err,
    ERR_NOT_OWNER, ERR_SOD, ERR_EXAM_OVERLAP, ERR_INVALID_REQUEST,
)
from middleware import (
    auth_context, require_role, body, req_str, req_enum, req_dt, req_bool,
    touch, paginate, ALL_ROLES,
)
from response import success
from services.cascade import cuso_suspend, cuso_reinstate

bp = Blueprint("exams", __name__)

SEVERITIES = {"LOW", "MODERATE", "HIGH", "CRITICAL"}
OPEN_FINDING_STATUSES = {"OPEN", "VERIFYING", "REOPENED"}


def _get_exam(eid):
    e = db.exams.get(eid)
    if e is None:
        not_found("RegulatoryExam")
    return e


def _get_finding(fid):
    f = db.findings.get(fid)
    if f is None:
        not_found("ExamFinding")
    return f


@bp.post("/network/exams")
def create_exam():
    uid, role = auth_context()
    require_role(role, {"RegulatorUser"})
    b = body()
    cuso_id = b.get("cuso_id")
    if cuso_id is not None and cuso_id not in db.cusos:
        not_found("CUSO")
    if cuso_id is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: cuso_id")
    start = req_dt(b, "start_date")
    end = req_dt(b, "end_date")
    if end <= start:
        raise_err(ERR_INVALID_REQUEST, "end_date must fall after start_date")
    # half-open [start_date, end_date) windows must not overlap per CUSO;
    # adjacency (start == other's end) is allowed
    for e in db.exams.values():
        if e["cuso_id"] == cuso_id and start < e["end_date"] and e["start_date"] < end:
            raise_err(ERR_EXAM_OVERLAP, "Exam window overlaps another exam for this CUSO")
    exam = db.insert("exam", {
        "cuso_id": cuso_id,
        "start_date": start,
        "end_date": end,
        "status": "IN_PROGRESS",
        "finalized_at": None,
    })
    return success(ser.exam(exam), 201)


@bp.get("/network/exams/<eid>")
def get_exam(eid):
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    return success(ser.exam(_get_exam(eid)))


@bp.get("/network/exams")
def list_exams():
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    items = list(db.exams.values())
    co = request.args.get("cuso_id")
    if co is not None:
        items = [e for e in items if e["cuso_id"] == co]
    st = request.args.get("status")
    if st is not None:
        items = [e for e in items if e["status"] == st]
    page, meta = paginate(items, ser.exam)
    return success(page, 200, meta)


@bp.post("/network/exams/<eid>/finalize")
def finalize_exam(eid):
    uid, role = auth_context()
    require_role(role, {"RegulatorUser"})
    exam = _get_exam(eid)
    if exam["status"] != "IN_PROGRESS":
        invalid_state("Exam must be IN_PROGRESS to finalize")
    exam["status"] = "FINALIZED"
    exam["finalized_at"] = db.clock_now()
    touch("exam", exam)
    # supervisory tripwire: >= 1 CRITICAL finding still open suspends the CUSO
    has_open_critical = any(
        f["exam_id"] == eid and f["severity"] == "CRITICAL" and f["status"] in OPEN_FINDING_STATUSES
        for f in db.findings.values()
    )
    if has_open_critical:
        cuso = db.cusos.get(exam["cuso_id"])
        if cuso is not None:
            cuso_suspend(cuso)
    return success(ser.exam(exam))


@bp.post("/network/findings")
def create_finding():
    uid, role = auth_context()
    require_role(role, {"RegulatorUser"})
    b = body()
    exam_id = b.get("exam_id")
    if exam_id is not None and exam_id not in db.exams:
        not_found("RegulatoryExam")
    if exam_id is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: exam_id")
    severity = req_enum(b, "severity", SEVERITIES)
    description = req_str(b, "description")
    due = req_dt(b, "remediation_due_date")
    f = db.insert("finding", {
        "exam_id": exam_id,
        "severity": severity,
        "description": description,
        "remediation_due_date": due,
        "recorded_by_user_id": uid,
        "status": "OPEN",
        "remediation_notes": None,
    })
    # open_critical_finding_count recomputed (bump when it actually changes)
    if severity == "CRITICAL":
        cuso = db.cusos.get(db.exams[exam_id]["cuso_id"])
        if cuso is not None:
            touch("cuso", cuso)
    return success(ser.finding(f), 201)


@bp.get("/network/findings/<fid>")
def get_finding(fid):
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    return success(ser.finding(_get_finding(fid)))


@bp.get("/network/findings")
def list_findings():
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    items = list(db.findings.values())
    eid = request.args.get("exam_id")
    if eid is not None:
        items = [f for f in items if f["exam_id"] == eid]
    st = request.args.get("status")
    if st is not None:
        items = [f for f in items if f["status"] == st]
    sev = request.args.get("severity")
    if sev is not None:
        items = [f for f in items if f["severity"] == sev]
    page, meta = paginate(items, ser.finding)
    return success(page, 200, meta)


@bp.post("/network/findings/<fid>/submit-remediation")
def submit_remediation(fid):
    uid, role = auth_context()
    require_role(role, {"CUSOOfficer"})
    f = _get_finding(fid)
    exam = db.exams[f["exam_id"]]
    if exam["cuso_id"] != uid:
        raise_err(ERR_NOT_OWNER, "CUSOOfficer must own the exam's CUSO")
    notes = req_str(body(), "remediation_notes")
    if f["status"] not in ("OPEN", "REOPENED"):
        invalid_state("Finding must be OPEN or REOPENED to submit remediation")
    f["status"] = "VERIFYING"
    f["remediation_notes"] = notes
    touch("finding", f)
    return success(ser.finding(f))


@bp.post("/network/findings/<fid>/verify")
def verify_finding(fid):
    uid, role = auth_context()
    require_role(role, {"RegulatorUser"})
    f = _get_finding(fid)
    passed = req_bool(body(), "verification_passed")
    if f["status"] != "VERIFYING":
        invalid_state("Finding must be VERIFYING to verify")
    # segregation of duties: verifier must differ from recorder
    if uid == f["recorded_by_user_id"]:
        raise_err(ERR_SOD, "Finding verifier must differ from the finding's recorder")
    if passed:
        f["status"] = "CLOSED"
        touch("finding", f)
        cuso = db.cusos.get(db.exams[f["exam_id"]]["cuso_id"])
        if (
            f["severity"] == "CRITICAL"
            and cuso is not None
            and ser.cuso_open_critical(cuso["id"]) == 0
            and cuso["status"] == "SUSPENDED"
        ):
            cuso_reinstate(cuso)
        elif f["severity"] == "CRITICAL" and cuso is not None:
            touch("cuso", cuso)  # open_critical_finding_count changed
    else:
        f["status"] = "REOPENED"
        touch("finding", f)
    return success(ser.finding(f))
