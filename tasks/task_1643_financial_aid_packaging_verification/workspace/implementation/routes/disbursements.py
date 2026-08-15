"""Disbursement endpoints (PRD 3.7): schedule, eligibility, post, returns."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE, ERR_PARENT_STATE_BLOCKS,
    ERR_DISBURSEMENT_AMOUNT,
)
from middleware import authorized
from response import success_object
from routes.helpers import list_response
from services.calc import evaluate_disbursement_eligibility
from services.core import (
    new_record, public, touch, latest_verification_case,
    adjust_disbursed_aggregates, recompute_aggregates,
)
from validate import (
    get_body, req_str, req_int, require_path_resource, deferred_body_ref,
)

bp = Blueprint("disbursements", __name__)

DIRECTOR_OFFICER = ["AidDirector", "AidOfficer"]
OFFICER = ["AidOfficer"]


def _package_posted_total(pkg_id):
    total = 0
    for disb in db.disbursements.values():
        if disb["status"] != "POSTED":
            continue
        line = db.award_lines.get(disb["award_line_id"])
        if line is not None and line["package_id"] == pkg_id:
            total += disb["disbursed_cents"]
    return total


@bp.post("/disbursements")
def create_disbursement():
    authorized(OFFICER)
    body = get_body()
    # Rung 4: body foreign key (absent key defers to the rung-9 shape check).
    line = deferred_body_ref("award_lines", body, "award_line_id")
    pkg = None
    ay = None
    if line is not None:
        pkg = db.award_packages.get(line["package_id"])
        ay = db.aid_years.get(pkg["aid_year_id"]) if pkg is not None else None
    # Rung 6: the aid year must not be CLOSED for a student-level write.
    if ay is not None and ay["status"] == "CLOSED":
        raise_error(ERR_PARENT_STATE_BLOCKS,
                    "the aid year is CLOSED to student-level writes")
    # Rung 9: shape (types only; the amount's domain rules are rung 17).
    req_str(body, "award_line_id")
    scheduled = req_int(body, "scheduled_cents")
    term_code = req_str(body, "term_code")
    # Rung 17: amount, line status, and package status — one error id.
    headroom = line["accepted_cents"] - line["disbursed_cents"]
    if scheduled <= 0 or scheduled > headroom:
        raise_error(ERR_DISBURSEMENT_AMOUNT,
                    "scheduled_cents must be strictly positive and no greater than "
                    "the line's remaining headroom")
    if line["status"] != "DISBURSING":
        raise_error(ERR_DISBURSEMENT_AMOUNT,
                    "the award line must be DISBURSING to schedule a disbursement")
    if pkg is None or pkg["status"] != "LOCKED":
        raise_error(ERR_DISBURSEMENT_AMOUNT,
                    "the package must be LOCKED to schedule a disbursement")
    rec = new_record("disbursements", {
        "award_line_id": line["id"],
        "scheduled_cents": scheduled,
        "disbursed_cents": 0,
        "term_code": term_code,
        "status": "SCHEDULED",
        "failure_reasons": [],
    })
    return success_object(public(rec), status=201)


@bp.get("/disbursements")
def list_disbursements():
    authorized(DIRECTOR_OFFICER)
    return list_response("disbursements", {
        "award_line_id": request.args.get("award_line_id"),
        "status": request.args.get("status"),
    })


@bp.get("/disbursements/<rid>")
def get_disbursement(rid):
    authorized(DIRECTOR_OFFICER)
    rec = require_path_resource("disbursements", rid)
    return success_object(public(rec))


@bp.post("/disbursements/<rid>/evaluate-eligibility")
def evaluate_eligibility(rid):
    authorized(OFFICER)
    disb = require_path_resource("disbursements", rid)
    if disb["status"] not in ("SCHEDULED", "ELIGIBILITY_FAILED"):
        raise_error(ERR_INVALID_STATE,
                    f"disbursement is {disb['status']}, expected SCHEDULED or "
                    f"ELIGIBILITY_FAILED")
    line = db.award_lines.get(disb["award_line_id"])
    fund = db.fund_types.get(line["fund_type_id"]) if line is not None else None
    pkg = db.award_packages.get(line["package_id"]) if line is not None else None
    student = db.students.get(pkg["student_id"]) if pkg is not None else None
    ay = db.aid_years.get(pkg["aid_year_id"]) if pkg is not None else None
    case = latest_verification_case(pkg["student_id"], pkg["aid_year_id"]) if pkg else None
    posted_total = _package_posted_total(pkg["id"]) if pkg is not None else 0
    failures = evaluate_disbursement_eligibility(
        disb, line, fund, pkg, student, ay, case, posted_total)
    disb["failure_reasons"] = failures
    disb["status"] = "ELIGIBILITY_PASSED" if not failures else "ELIGIBILITY_FAILED"
    touch(disb)
    return success_object(public(disb))


@bp.post("/disbursements/<rid>/reset")
def reset_disbursement(rid):
    authorized(OFFICER)
    disb = require_path_resource("disbursements", rid)
    if disb["status"] != "ELIGIBILITY_FAILED":
        raise_error(ERR_INVALID_STATE,
                    f"disbursement is {disb['status']}, expected ELIGIBILITY_FAILED")
    disb["status"] = "SCHEDULED"
    disb["failure_reasons"] = []
    touch(disb)
    return success_object(public(disb))


@bp.post("/disbursements/<rid>/post")
def post_disbursement(rid):
    authorized(OFFICER)
    disb = require_path_resource("disbursements", rid)
    if disb["status"] != "ELIGIBILITY_PASSED":
        raise_error(ERR_INVALID_STATE,
                    f"disbursement is {disb['status']}, expected ELIGIBILITY_PASSED")
    line = db.award_lines.get(disb["award_line_id"])
    # Posting re-checks the money at that instant (PRD 3.7).
    if line is None or line["status"] != "DISBURSING":
        raise_error(ERR_INVALID_STATE,
                    "the parent line must be DISBURSING to post")
    if line["disbursed_cents"] + disb["scheduled_cents"] > line["accepted_cents"]:
        raise_error(ERR_INVALID_STATE,
                    "posting would exceed the line's accepted_cents")
    disb["disbursed_cents"] = disb["scheduled_cents"]
    disb["status"] = "POSTED"
    touch(disb)
    adjust_disbursed_aggregates(line, disb["scheduled_cents"])
    touch(line)
    # Line completion: posted total equals accepted (necessarily above zero).
    if line["disbursed_cents"] == line["accepted_cents"] and line["disbursed_cents"] > 0:
        line["status"] = "DISBURSED"
        touch(line)
    return success_object(public(disb))


@bp.post("/disbursements/<rid>/request-return")
def request_return(rid):
    authorized(OFFICER)
    disb = require_path_resource("disbursements", rid)
    if disb["status"] != "POSTED":
        raise_error(ERR_INVALID_STATE,
                    f"disbursement is {disb['status']}, expected POSTED")
    disb["status"] = "RETURN_REQUESTED"
    touch(disb)
    return success_object(public(disb))


@bp.post("/disbursements/<rid>/confirm-return")
def confirm_return(rid):
    authorized(OFFICER)
    disb = require_path_resource("disbursements", rid)
    if disb["status"] != "RETURN_REQUESTED":
        raise_error(ERR_INVALID_STATE,
                    f"disbursement is {disb['status']}, expected RETURN_REQUESTED")
    disb["status"] = "RETURNED"
    touch(disb)
    line = db.award_lines.get(disb["award_line_id"])
    if line is not None:
        adjust_disbursed_aggregates(line, -disb["disbursed_cents"])
        touch(line)
        pkg = db.award_packages.get(line["package_id"])
        if pkg is not None:
            recompute_aggregates(pkg["aid_year_id"])
    return success_object(public(disb))
