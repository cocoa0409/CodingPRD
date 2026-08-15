"""Credit posting endpoints: create, list, post."""

from flask import Blueprint, request
import db
from db import new_id, now_iso
from middleware import get_auth, require_role, check_student_ownership
from response import success_object, success_list
from utils import require_field, parse_pagination, round_credit
from errors import (
    not_found, invalid_request, invalid_state, ApiError,
    ERR_PREAPPROVAL_INVALID, ERR_DUPLICATE_CREDIT_POSTING, ERR_GRADE_OUT_OF_RANGE,
)

bp = Blueprint("credit_postings", __name__)

TRANSFER_GRADE_MIN = 2.0


@bp.route("/api/v1/applications/<id>/credit-postings", methods=["POST"])
def create_credit_posting(id):
    user_id, role = get_auth()
    require_role(role, ["FacultyApprover"])

    app = db.applications.get(id)
    if not app:
        raise not_found("Application not found")

    body = request.get_json(silent=True) or {}
    lines = require_field(body, "lines")
    if not isinstance(lines, list):
        raise invalid_request("lines must be an array")

    # state gate (tier 5): application must be RETURNED_HOME
    if app["status"] != "RETURNED_HOME":
        raise invalid_state("Application is not in RETURNED_HOME status")

    program = db.programs.get(app["program_id"])
    agreement = db.partner_agreements.get(program["partner_agreement_id"]) if program else None
    factor = agreement["credit_conversion_factor"] if agreement else 1.0

    # validate lines
    validated = []
    for line in lines:
        if not isinstance(line, dict):
            raise invalid_request("each line must be an object")
        cpa_id = line.get("course_preapproval_id")
        grade_points = line.get("grade_points")
        if not isinstance(cpa_id, str):
            raise invalid_request("line.course_preapproval_id must be a string")
        if isinstance(grade_points, bool) or not isinstance(grade_points, (int, float)):
            raise invalid_request("line.grade_points must be a number")

        # referential integrity (tier 9): preapproval must exist, belong to this app, be APPROVED
        cpa = db.course_preapprovals.get(cpa_id)
        if not cpa or cpa["application_id"] != app["id"] or cpa["status"] != "APPROVED":
            raise ApiError(ERR_PREAPPROVAL_INVALID, "line references a CoursePreApproval that is missing, belongs to another application, or is not APPROVED", 422)

        validated.append((cpa, grade_points))

    # duplicate check (tier 10): at most one PENDING/POSTED credit posting per application
    for cp in db.credit_postings.values():
        if cp["application_id"] == app["id"] and cp["status"] in ("PENDING", "POSTED"):
            raise ApiError(ERR_DUPLICATE_CREDIT_POSTING, "A PENDING or POSTED CreditPosting already exists for the application", 409)

    # grade range check (tier 10)
    for cpa, grade_points in validated:
        if not (0.0 <= grade_points <= 4.0):
            raise ApiError(ERR_GRADE_OUT_OF_RANGE, "grade_points must be between 0.0 and 4.0", 422)

    # compute credits per transfer_credit_conversion
    provisional = 0.0
    final = 0.0
    for cpa, grade_points in validated:
        home = round_credit(cpa["host_credits"], factor)
        provisional += home
        if grade_points >= TRANSFER_GRADE_MIN:
            final += home

    # normalize to int when whole (avoid 3.0 vs 3 style drift); keep numeric
    def _norm(x):
        return int(x) if x == int(x) else x

    ts = now_iso()
    rec = {
        "id": new_id(),
        "application_id": app["id"],
        "lines": [
            {"course_preapproval_id": cpa["id"], "grade_points": gp}
            for cpa, gp in validated
        ],
        "provisional_credits": _norm(provisional),
        "final_credits": _norm(final),
        "posted_by": None,
        "status": "PENDING",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.credit_postings[rec["id"]] = rec
    return success_object(rec, 201)


@bp.route("/api/v1/applications/<id>/credit-postings", methods=["GET"])
def list_credit_postings(id):
    user_id, role = get_auth()
    require_role(role, ["FacultyApprover", "ProgramCoordinator", "Student"])

    app = db.applications.get(id)
    if not app:
        raise not_found("Application not found")

    check_student_ownership(user_id, role, app["student_id"])

    limit, offset = parse_pagination(request.args)
    items = [c for c in db.credit_postings.values() if c["application_id"] == app["id"]]
    items.sort(key=lambda c: (c["created_at"], c["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([dict(c) for c in page], limit, offset, total)


@bp.route("/api/v1/credit-postings/<id>/post", methods=["POST"])
def post_credit_posting(id):
    user_id, role = get_auth()
    require_role(role, ["FacultyApprover"])

    rec = db.credit_postings.get(id)
    if not rec:
        raise not_found("CreditPosting not found")

    if rec["status"] != "PENDING":
        raise invalid_state("CreditPosting is not in PENDING status")

    app = db.applications.get(rec["application_id"])
    if not app:
        raise not_found("Application not found")

    if app["status"] != "RETURNED_HOME":
        raise invalid_state("Application is not in RETURNED_HOME status")

    rec["status"] = "POSTED"
    rec["posted_by"] = user_id
    rec["version"] += 1
    rec["updated_at"] = now_iso()

    # cascade: Application RETURNED_HOME -> CREDIT_POSTED
    app["status"] = "CREDIT_POSTED"
    app["transfer_credits_posted"] = rec["final_credits"]
    app["version"] += 1
    app["updated_at"] = now_iso()

    return success_object(dict(rec), 200)
