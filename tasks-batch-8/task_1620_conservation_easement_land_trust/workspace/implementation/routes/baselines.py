"""Baseline report endpoints."""
from flask import Blueprint, g

import db
import utils
from errors import ApiError
from middleware import ANY_ROLE, body, paginate, require_roles
from response import ok
from services import domain

bp = Blueprint("baselines", __name__)


def get_baseline_or_404(baseline_id):
    r = db.baseline_reports.get(baseline_id)
    if r is None:
        raise ApiError("ERR_BASELINE_REPORT_NOT_FOUND", "BaselineReport id does not exist.", 404)
    return r


@bp.route("/stewardship/baseline-reports", methods=["POST"])
@require_roles("StewardshipCoordinator")
def create_baseline():
    b = body()
    easement_id = b.get("easement_id")
    if easement_id is not None and easement_id not in db.easements:
        raise ApiError("ERR_EASEMENT_NOT_FOUND", "Easement id does not exist.", 404)
    # Uniqueness (priority 8): one BaselineReport per easement ever.
    if easement_id is not None and any(
        r["easement_id"] == easement_id for r in db.baseline_reports.values()
    ):
        raise ApiError("ERR_BASELINE_ALREADY_EXISTS", "Second BaselineReport for the same easement.", 409)
    prepared_by = b.get("prepared_by_user_id")
    narrative = b.get("condition_narrative")
    photo_count = b.get("photo_point_count")
    if (
        easement_id is None
        or not isinstance(prepared_by, str)
        or not isinstance(narrative, str)
        or not utils.is_int(photo_count)
        or photo_count < 0
    ):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "easement_id, prepared_by_user_id, condition_narrative and a non-negative integer photo_point_count are required.",
            400,
        )
    now = utils.now_iso()
    r = {
        "id": utils.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "easement_id": easement_id,
        "prepared_by_user_id": prepared_by,
        "condition_narrative": narrative,
        "photo_point_count": photo_count,
        "review_round": 0,
        "submitted_on": None,
        "accepted_on": None,
        "revision_notes": None,
        "status": "DRAFT",
    }
    db.baseline_reports[r["id"]] = r
    return ok(domain.baseline_json(r), 201)


@bp.route("/stewardship/baseline-reports", methods=["GET"])
@require_roles(*ANY_ROLE)
def list_baselines():
    from flask import request

    filters = {}
    for key in ("easement_id", "status"):
        v = request.args.get(key)
        if v is not None:
            filters[key] = v
    return paginate(list(db.baseline_reports.values()), domain.baseline_json, filters)


@bp.route("/stewardship/baseline-reports/<baselineReportId>", methods=["GET"])
@require_roles(*ANY_ROLE)
def get_baseline(baselineReportId):
    return ok(domain.baseline_json(get_baseline_or_404(baselineReportId)))


@bp.route("/stewardship/baseline-reports/<baselineReportId>/submit", methods=["POST"])
@require_roles("StewardshipCoordinator")
def submit_baseline(baselineReportId):
    r = get_baseline_or_404(baselineReportId)
    if r["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError("ERR_INVALID_BASELINE_STATE", "Submit requires DRAFT or REVISION_REQUESTED.", 409)
    e = db.easements[r["easement_id"]]
    if r["photo_point_count"] < domain.required_photo_points(e["parcel_acreage"]):
        raise ApiError("ERR_INCOMPLETE_BASELINE", "photo_point_count is below required_photo_points.", 422)
    r["status"] = "SUBMITTED"
    r["review_round"] += 1
    r["submitted_on"] = utils.today()
    domain.bump(r)
    return ok(domain.baseline_json(r))


@bp.route("/stewardship/baseline-reports/<baselineReportId>/accept", methods=["POST"])
@require_roles("TrustBoardReviewer")
def accept_baseline(baselineReportId):
    r = get_baseline_or_404(baselineReportId)
    if r["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_BASELINE_STATE", "Accept requires SUBMITTED.", 409)
    if g.user_id == r["prepared_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", "The preparer may not accept the baseline.", 403)
    r["status"] = "ACCEPTED"
    r["accepted_on"] = utils.today()
    domain.bump(r)
    return ok(domain.baseline_json(r))


@bp.route("/stewardship/baseline-reports/<baselineReportId>/request-revision", methods=["POST"])
@require_roles("TrustBoardReviewer")
def request_revision_baseline(baselineReportId):
    r = get_baseline_or_404(baselineReportId)
    if r["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_BASELINE_STATE", "Request-revision requires SUBMITTED.", 409)
    b = body()
    notes = b.get("revision_notes")
    if not isinstance(notes, str):
        raise ApiError("ERR_INVALID_REQUEST", "revision_notes is required.", 400)
    r["revision_notes"] = notes
    r["status"] = "REVISION_REQUESTED"
    domain.bump(r)
    return ok(domain.baseline_json(r))
