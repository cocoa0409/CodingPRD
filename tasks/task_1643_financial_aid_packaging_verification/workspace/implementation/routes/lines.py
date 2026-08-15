"""AwardLine, AwardNotification, and RevisionRequest endpoints (PRD 3.6-3.7)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_PARENT_STATE_BLOCKS,
)
from middleware import authorized, check_student_owns
from response import success_object
from routes.helpers import list_response
from services.core import (
    public, touch, recompute_package_totals, recompute_aggregates,
)
from services.packaging import repack_package, run_overaward_detection
from validate import get_body, req_str, req_int, require_path_resource

bp = Blueprint("lines", __name__)

DIRECTOR_OFFICER = ["AidDirector", "AidOfficer"]
ALL_READ = ["AidDirector", "AidOfficer", "Student"]
OFFICER = ["AidOfficer"]
DIRECTOR = ["AidDirector"]


def _line_package(line):
    return db.award_packages.get(line["package_id"])


# ---------------------------------------------------------------------------
# AwardLine
# ---------------------------------------------------------------------------

@bp.get("/award-lines")
def list_lines():
    authorized(DIRECTOR_OFFICER)
    return list_response("award_lines", {
        "package_id": request.args.get("package_id"),
        "fund_type_id": request.args.get("fund_type_id"),
        "status": request.args.get("status"),
    })


@bp.get("/award-lines/<rid>")
def get_line(rid):
    caller = authorized(ALL_READ)
    line = require_path_resource("award_lines", rid)
    pkg = _line_package(line)
    if pkg is not None:
        check_student_owns(caller, pkg["student_id"])
    return success_object(public(line))


@bp.post("/award-lines/<rid>/begin-disbursement")
def begin_disbursement(rid):
    authorized(OFFICER)
    line = require_path_resource("award_lines", rid)
    # Rung 5: the line's own state machine.
    if line["status"] not in ("ACCEPTED", "PARTIALLY_ACCEPTED"):
        raise_error(ERR_INVALID_STATE,
                    f"line is {line['status']}, expected ACCEPTED or "
                    f"PARTIALLY_ACCEPTED")
    # Rung 6: the parent package must be LOCKED.
    pkg = _line_package(line)
    if pkg is None or pkg["status"] != "LOCKED":
        raise_error(ERR_PARENT_STATE_BLOCKS,
                    "line disbursement requires the package to be LOCKED")
    line["status"] = "DISBURSING"
    touch(line)
    return success_object(public(line))


@bp.post("/award-lines/<rid>/request-return")
def request_line_return(rid):
    authorized(OFFICER)
    line = require_path_resource("award_lines", rid)
    if line["status"] != "DISBURSED":
        raise_error(ERR_INVALID_STATE,
                    f"line is {line['status']}, expected DISBURSED")
    body = get_body()
    reason = body.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise_error(ERR_INVALID_REQUEST, "reason must be a string")
    # Permitted when an over-award case in OPEN or RESOLVING references the
    # line, or when a manual reason is supplied.
    referenced = False
    pkg = _line_package(line)
    if pkg is not None:
        for case in db.overaward_cases.values():
            if (case["student_id"] == pkg["student_id"]
                    and case["aid_year_id"] == pkg["aid_year_id"]
                    and case["status"] in ("OPEN", "RESOLVING")):
                plan = case.get("resolution_plan") or []
                if any(step.get("award_line_id") == line["id"]
                       for step in plan if isinstance(step, dict)):
                    referenced = True
                    break
    if not referenced and not (isinstance(reason, str) and reason.strip()):
        raise_error(ERR_INVALID_STATE,
                    "a line return requires an open over-award case referencing the "
                    "line or a manual reason")
    line["status"] = "RETURN_REQUESTED"
    touch(line)
    return success_object(public(line))


@bp.post("/award-lines/<rid>/confirm-return")
def confirm_line_return(rid):
    authorized(OFFICER)
    line = require_path_resource("award_lines", rid)
    if line["status"] != "RETURN_REQUESTED":
        raise_error(ERR_INVALID_STATE,
                    f"line is {line['status']}, expected RETURN_REQUESTED")
    body = get_body()
    return_cents = req_int(body, "return_cents")
    if return_cents <= 0 or return_cents > line["disbursed_cents"]:
        raise_error(ERR_INVALID_REQUEST,
                    "return_cents must be strictly positive and no greater than "
                    "the line's disbursed_cents")
    line["disbursed_cents"] -= return_cents
    line["status"] = "RETURNED"
    touch(line)
    fund = db.fund_types.get(line["fund_type_id"])
    if fund is not None:
        fund["pool_disbursed_cents"] -= return_cents
        touch(fund)
    pkg = _line_package(line)
    if pkg is not None:
        ay = db.aid_years.get(pkg["aid_year_id"])
        if ay is not None:
            ay["total_disbursed_cents"] -= return_cents
            touch(ay)
        recompute_package_totals(pkg)
        # The line leaves the reserving set; pool release may revive EXHAUSTED.
        recompute_aggregates(pkg["aid_year_id"])
    return success_object(public(line))


# ---------------------------------------------------------------------------
# AwardNotification
# ---------------------------------------------------------------------------

@bp.post("/award-notifications/<rid>/acknowledge")
def acknowledge(rid):
    caller = authorized(["Student"])
    note = require_path_resource("award_notifications", rid)
    if note["status"] != "SENT":
        raise_error(ERR_INVALID_STATE,
                    f"notification is {note['status']}, expected SENT")
    pkg = db.award_packages.get(note["package_id"])
    if pkg is not None:
        check_student_owns(caller, pkg["student_id"])
    note["status"] = "ACKNOWLEDGED"
    touch(note)
    return success_object(public(note))


# ---------------------------------------------------------------------------
# RevisionRequest
# ---------------------------------------------------------------------------

@bp.get("/revision-requests/<rid>")
def get_revision_request(rid):
    caller = authorized(ALL_READ)
    req_rec = require_path_resource("revision_requests", rid)
    pkg = db.award_packages.get(req_rec["package_id"])
    if pkg is not None:
        check_student_owns(caller, pkg["student_id"])
    return success_object(public(req_rec))


@bp.post("/revision-requests/<rid>/begin-review")
def revision_begin_review(rid):
    authorized(OFFICER)
    req_rec = require_path_resource("revision_requests", rid)
    if req_rec["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE,
                    f"revision request is {req_rec['status']}, expected SUBMITTED")
    req_rec["status"] = "UNDER_REVIEW"
    touch(req_rec)
    return success_object(public(req_rec))


@bp.post("/revision-requests/<rid>/approve")
def revision_approve(rid):
    authorized(DIRECTOR)
    req_rec = require_path_resource("revision_requests", rid)
    if req_rec["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE,
                    f"revision request is {req_rec['status']}, expected UNDER_REVIEW")
    body = get_body()
    notes = req_str(body, "decision_notes")
    pkg = db.award_packages.get(req_rec["package_id"])
    student = db.students.get(pkg["student_id"]) if pkg is not None else None
    ay = db.aid_years.get(pkg["aid_year_id"]) if pkg is not None else None
    # Rung 15 fires inside repack_package before anything mutates
    # (ERR_FUND_POOL_EXHAUSTED leaves the request UNDER_REVIEW).
    repack_package(pkg, student, ay)
    req_rec["status"] = "APPROVED"
    req_rec["decision_notes"] = notes
    touch(req_rec)
    # The package returns to NOTIFIED through the system transition, with a
    # fresh AwardNotification carrying the next notification_seq.
    pkg["status"] = "NOTIFIED"
    touch(pkg)
    from routes.packages import _fire_notification
    _fire_notification(pkg)
    run_overaward_detection(pkg["student_id"], pkg["aid_year_id"])
    return success_object(public(req_rec))


@bp.post("/revision-requests/<rid>/deny")
def revision_deny(rid):
    authorized(DIRECTOR)
    req_rec = require_path_resource("revision_requests", rid)
    if req_rec["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE,
                    f"revision request is {req_rec['status']}, expected UNDER_REVIEW")
    body = get_body()
    notes = req_str(body, "decision_notes")
    req_rec["status"] = "DENIED"
    req_rec["decision_notes"] = notes
    touch(req_rec)
    # Denial returns the package to NOTIFIED unchanged.
    pkg = db.award_packages.get(req_rec["package_id"])
    if pkg is not None and pkg["status"] == "REVISION_REQUESTED":
        pkg["status"] = "NOTIFIED"
        touch(pkg)
    return success_object(public(req_rec))
