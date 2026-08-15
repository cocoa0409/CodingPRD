"""Interview scheduling and lifecycle (PRD §3.3)."""
from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE, ERR_UNAUTHORIZED, ERR_INTERVIEW_OVERLAP,
    ERR_TIMING_VIOLATION, ERR_DOCUMENTATION_STANDARD,
)
from middleware import authorize, require_investigator
from response import success_object
from services.core import (
    new_record, touch, require_path, require_ref, list_response,
    serialize_interview, check_case_not_held, touch_case_manifest,
)
from util import CLOCK, fmt_dt
from validate import Payload

bp = Blueprint("interviews", __name__)

READ_ROLES = {"ERManager", "Investigator", "LegalCounsel"}


@bp.post("/er/cases/<cid>/interviews")
def schedule_interview(cid):
    caller = authorize({"Investigator"})
    case = require_path("cases", cid)
    p = Payload(request.get_json(silent=True))
    interviewee_id = p.get_str("interviewee_employee_id", required=True)
    start_dt = p.get_dt("scheduled_start", required=True)
    end_dt = p.get_dt("scheduled_end", required=True)

    # priority 5
    if interviewee_id is not None:
        require_ref("employees", interviewee_id, "interviewee_employee_id")

    # priority 6 — case must be INVESTIGATING
    if case["status"] != "INVESTIGATING":
        raise_error(ERR_INVALID_STATE,
                    f"cannot schedule an interview under a case in status "
                    f"{case['status']}")
    # priority 7
    check_case_not_held(case)
    # ownership — interviews are scheduled by the case's assigned investigator
    inv = require_investigator(caller)
    if inv["id"] != case["assigned_investigator_id"]:
        raise_error(ERR_UNAUTHORIZED,
                    "only the case's assigned investigator may schedule "
                    "interviews")

    # priority 12 — window rules, half-open [start, end) overlap semantics
    if start_dt is not None and end_dt is not None:
        if not end_dt > start_dt:
            raise_error(ERR_INTERVIEW_OVERLAP,
                        "scheduled_end must be strictly after scheduled_start")
        for other in db["interviews"].values():
            if other["interviewer_investigator_id"] != inv["id"]:
                continue
            if other["status"] != "SCHEDULED":
                continue
            if start_dt < other["_end_dt"] and other["_start_dt"] < end_dt:
                raise_error(ERR_INTERVIEW_OVERLAP,
                            "interview window overlaps an existing SCHEDULED "
                            "interview of the same interviewer")

    # priority 24
    p.raise_if_errors()

    rec = new_record()
    rec.update({
        "case_id": cid,
        "interviewee_employee_id": interviewee_id,
        "interviewer_investigator_id": case["assigned_investigator_id"],
        "scheduled_start": fmt_dt(start_dt),
        "scheduled_end": fmt_dt(end_dt),
        "_start_dt": start_dt,
        "_end_dt": end_dt,
        "status": "SCHEDULED",
        "documentation_text": None,
        "documentation_word_count": 0,
        "completed_at": None,
    })
    db["interviews"][rec["id"]] = rec
    return success_object(serialize_interview(rec), status=201)


@bp.get("/er/cases/<cid>/interviews")
def list_case_interviews(cid):
    authorize(READ_ROLES)
    require_path("cases", cid)
    items = [iv for iv in db["interviews"].values() if iv["case_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        items = [iv for iv in items if iv["status"] == status]
    return list_response(items, serialize_interview)


@bp.get("/er/interviews/<iid>")
def get_interview(iid):
    authorize(READ_ROLES)
    rec = require_path("interviews", iid)
    return success_object(serialize_interview(rec))


@bp.get("/er/interviews")
def list_interviews():
    authorize(READ_ROLES)
    items = list(db["interviews"].values())
    for field in ("interviewee_employee_id", "interviewer_investigator_id",
                  "status"):
        v = request.args.get(field)
        if v is not None:
            items = [iv for iv in items if iv.get(field) == v]
    return list_response(items, serialize_interview)


@bp.post("/er/interviews/<iid>/complete")
def complete_interview(iid):
    caller = authorize({"Investigator"})
    iv = require_path("interviews", iid)
    p = Payload(request.get_json(silent=True))
    documentation_text = p.get_str("documentation_text", required=True)

    case = db["cases"][iv["case_id"]]
    # priority 6 — interview SCHEDULED and parent case INVESTIGATING
    if iv["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE,
                    f"cannot complete an interview in status {iv['status']}")
    if case["status"] != "INVESTIGATING":
        raise_error(ERR_INVALID_STATE,
                    f"cannot complete an interview while the case is "
                    f"{case['status']}")
    # priority 7
    check_case_not_held(case)
    # ownership — only the bound interviewer
    require_investigator(caller)
    if caller.user_id != iv["interviewer_investigator_id"]:
        raise_error(ERR_UNAUTHORIZED,
                    "only the interview's interviewer may complete it")
    # priority 13 — the logical clock must have reached at least the
    # scheduled_start (PRD §3.3: "attempting earlier fails with
    # ERR_TIMING_VIOLATION")
    now = CLOCK.now()
    if now < iv["_start_dt"]:
        raise_error(ERR_TIMING_VIOLATION,
                    "interview cannot be completed before its scheduled_start")
    # priority 16 — documentation standard
    if documentation_text is not None and len(documentation_text) < 50:
        raise_error(ERR_DOCUMENTATION_STANDARD,
                    "documentation_text must be at least 50 characters")
    # priority 24
    p.raise_if_errors()

    iv["status"] = "COMPLETED"
    iv["documentation_text"] = documentation_text
    iv["documentation_word_count"] = len(documentation_text.split())
    iv["completed_at"] = fmt_dt(now)
    touch(iv)
    touch_case_manifest(iv["case_id"])
    return success_object(serialize_interview(iv))


@bp.post("/er/interviews/<iid>/mark-no-show")
def mark_no_show(iid):
    caller = authorize({"Investigator"})
    iv = require_path("interviews", iid)

    case = db["cases"][iv["case_id"]]
    # priority 6
    if iv["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE,
                    f"cannot mark no-show an interview in status {iv['status']}")
    # priority 7
    check_case_not_held(case)
    # ownership
    require_investigator(caller)
    if caller.user_id != iv["interviewer_investigator_id"]:
        raise_error(ERR_UNAUTHORIZED,
                    "only the interview's interviewer may mark it no-show")
    # priority 13 — strictly after scheduled_end + 30 minutes
    now = CLOCK.now()
    if not now > iv["_end_dt"] + timedelta(minutes=30):
        raise_error(ERR_TIMING_VIOLATION,
                    "no-show is permitted only once the logical clock has "
                    "passed scheduled_end by more than 30 minutes")

    iv["status"] = "NO_SHOW"
    touch(iv)
    return success_object(serialize_interview(iv))


@bp.post("/er/interviews/<iid>/cancel")
def cancel_interview(iid):
    caller = authorize({"Investigator", "ERManager"})
    iv = require_path("interviews", iid)

    case = db["cases"][iv["case_id"]]
    # priority 6
    if iv["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE,
                    f"cannot cancel an interview in status {iv['status']}")
    # priority 7
    check_case_not_held(case)
    # ownership — the interviewer, or any ERManager
    if caller.role == "Investigator":
        require_investigator(caller)
        if caller.user_id != iv["interviewer_investigator_id"]:
            raise_error(ERR_UNAUTHORIZED,
                        "only the interview's interviewer may cancel it")

    iv["status"] = "CANCELLED"
    touch(iv)
    return success_object(serialize_interview(iv))
