"""Application endpoints + state transitions."""
from flask import Blueprint, request

import db
from auth import require_role
from common import (
    get_json_or_400,
    require_str,
    new_id,
    now_iso,
    parse_pagination,
    paginate,
    get_or_404,
    fk_or_404,
    stamp_update,
)
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_PRECONDITION_FAILED,
    ERR_DUPLICATE_APPLICATION,
)
from response import success_object, success_array
from serializers import ser_application


bp = Blueprint("applications", __name__)


@bp.post("/ats/applications")
def create_application():
    require_role({"Recruiter"})
    body = get_json_or_400()
    candidate_id = require_str(body, "candidate_id")
    requisition_id = require_str(body, "requisition_id")

    fk_or_404(db.candidates, candidate_id, "candidate")
    req = fk_or_404(db.requisitions, requisition_id, "requisition")

    # State (priority 5/6) — requisition must be APPROVED.
    if req["status"] != "APPROVED":
        raise ApiError(ERR_PRECONDITION_FAILED, 409, "requisition not APPROVED")

    # Candidate must not already have an ACCEPTED offer.
    for off in db.offers.values():
        if off["status"] != "ACCEPTED":
            continue
        app = db.applications.get(off["application_id"])
        if app and app["candidate_id"] == candidate_id:
            raise ApiError(ERR_PRECONDITION_FAILED, 409, "candidate already has an accepted offer")

    # Duplicate application check.
    for a in db.applications.values():
        if a["candidate_id"] == candidate_id and a["requisition_id"] == requisition_id:
            raise ApiError(ERR_DUPLICATE_APPLICATION, 422, "duplicate (candidate_id, requisition_id)")

    app = {
        "id": new_id(),
        "candidate_id": candidate_id,
        "requisition_id": requisition_id,
        "status": "APPLIED",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }
    db.applications[app["id"]] = app
    return success_object(ser_application(app), status=201)


@bp.get("/ats/applications/<app_id>")
def read_application(app_id):
    require_role({"Recruiter", "HiringManager", "Candidate", "PlatformAdmin"})
    app = get_or_404(db.applications, app_id, "application")
    return success_object(ser_application(app), status=200)


@bp.get("/ats/applications")
def list_applications():
    require_role({"Recruiter", "HiringManager", "PlatformAdmin"})
    limit, offset = parse_pagination()
    rows = list(db.applications.values())
    cand_filter = request.args.get("candidate_id")
    req_filter = request.args.get("requisition_id")
    status_filter = request.args.get("status")
    if cand_filter:
        rows = [a for a in rows if a["candidate_id"] == cand_filter]
    if req_filter:
        rows = [a for a in rows if a["requisition_id"] == req_filter]
    if status_filter:
        rows = [a for a in rows if a["status"] == status_filter]
    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    return success_array([ser_application(a) for a in page], limit, offset, total, status=200)


@bp.post("/ats/applications/<app_id>/screen")
def screen_application(app_id):
    require_role({"Recruiter"})
    app = get_or_404(db.applications, app_id, "application")
    if app["status"] != "APPLIED":
        raise ApiError(ERR_INVALID_STATE, 409, "application not in APPLIED")
    req = db.requisitions.get(app["requisition_id"])
    if not req or req["status"] != "APPROVED":
        raise ApiError(ERR_PRECONDITION_FAILED, 409, "requisition not APPROVED")
    app["status"] = "SCREENING"
    stamp_update(app)
    return success_object(ser_application(app), status=200)


@bp.post("/ats/applications/<app_id>/reject")
def reject_application(app_id):
    require_role({"Recruiter"})
    app = get_or_404(db.applications, app_id, "application")
    if app["status"] not in {"APPLIED", "SCREENING", "INTERVIEWING"}:
        raise ApiError(ERR_INVALID_STATE, 409, "application not rejectable from current state")
    app["status"] = "REJECTED"
    stamp_update(app)
    return success_object(ser_application(app), status=200)


@bp.post("/ats/applications/<app_id>/withdraw")
def withdraw_application(app_id):
    require_role({"Candidate"})
    app = get_or_404(db.applications, app_id, "application")
    if app["status"] not in {"APPLIED", "SCREENING", "INTERVIEWING"}:
        raise ApiError(ERR_INVALID_STATE, 409, "application not withdrawable from current state")
    app["status"] = "WITHDRAWN"
    stamp_update(app)
    return success_object(ser_application(app), status=200)
