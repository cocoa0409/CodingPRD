"""ProgressReport endpoints (PRD §3.7)."""
from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success
from services import common as c

bp = Blueprint("progress_reports", __name__)

READ_ROLES = ("GrantWriter", "ProgramManager", "AgencyOfficer")


def _serialize(rep):
    return c.serialize(rep)


def _load(rep_id):
    rep = db.progress_reports.get(rep_id)
    if rep is None:
        raise errors.not_found("Progress report not found.")
    return rep


@bp.route("/progress-reports", methods=["POST"])
@require_roles("GrantWriter")
def create_progress_report(user_id, role):
    body = c.get_body()

    award_id = body.get("award_id")
    if award_id is None or not isinstance(award_id, str) or award_id == "":
        raise errors.invalid_request("award_id is required.")
    with db.LOCK:
        if award_id not in db.awards:
            raise errors.not_found("Award not found.")

        period_label = c.require_nonempty_string(body, "period_label")
        milestones_met = c.require_int(body, "milestones_met", minimum=0)
        milestones_planned = c.require_int(body, "milestones_planned", minimum=1)

        record = {
            "award_id": award_id,
            "period_label": period_label,
            "milestones_met": milestones_met,
            "milestones_planned": milestones_planned,
            "status": "SUBMITTED",
        }
        db.stamp_create(record)
        db.progress_reports[record["id"]] = record
        return success(_serialize(record), status=201)


@bp.route("/progress-reports", methods=["GET"])
@require_roles(*READ_ROLES)
def list_progress_reports(user_id, role):
    limit, offset = c.parse_pagination()
    award_id = request.args.get("award_id")
    status = request.args.get("status")
    with db.LOCK:
        records = list(db.progress_reports.values())
    if award_id is not None:
        records = [r for r in records if r["award_id"] == award_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, pagination = c.paginate(records, limit, offset)
    return success([_serialize(r) for r in page], status=200, pagination=pagination)


@bp.route("/progress-reports/<rep_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_progress_report(rep_id, user_id, role):
    with db.LOCK:
        return success(_serialize(_load(rep_id)), status=200)


@bp.route("/progress-reports/<rep_id>/accept", methods=["POST"])
@require_roles("ProgramManager")
def accept_progress_report(rep_id, user_id, role):
    with db.LOCK:
        rep = _load(rep_id)
        if rep["status"] != "SUBMITTED":
            raise errors.invalid_state("Only a SUBMITTED progress report may be accepted.")
        rep["status"] = "ACCEPTED"
        db.touch(rep)
        return success(_serialize(rep), status=200)


@bp.route("/progress-reports/<rep_id>/return", methods=["POST"])
@require_roles("ProgramManager")
def return_progress_report(rep_id, user_id, role):
    with db.LOCK:
        rep = _load(rep_id)
        if rep["status"] != "SUBMITTED":
            raise errors.invalid_state("Only a SUBMITTED progress report may be returned.")
        rep["status"] = "RETURNED"
        db.touch(rep)
        return success(_serialize(rep), status=200)


@bp.route("/progress-reports/<rep_id>/resubmit", methods=["POST"])
@require_roles("GrantWriter")
def resubmit_progress_report(rep_id, user_id, role):
    with db.LOCK:
        rep = _load(rep_id)
        if rep["status"] != "RETURNED":
            raise errors.invalid_state("Only a RETURNED progress report may be resubmitted.")
        rep["status"] = "SUBMITTED"
        db.touch(rep)
        return success(_serialize(rep), status=200)
