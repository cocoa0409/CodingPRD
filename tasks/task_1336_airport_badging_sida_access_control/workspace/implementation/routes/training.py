"""Training completion endpoints (PRD §3.3)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import raise_err, ERR_APPLICANT_NOT_FOUND
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services import logic
from services.serializers import serialize, serialize_list
from util import (
    fetch_or_404,
    get_json_body,
    paginate,
    parse_pagination,
    require_datetime,
    require_enum,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("training", __name__)


@bp.route("/training-completions", methods=["POST"])
@require_roles("BadgingOfficer")
def create_training_completion(user_id: str, role: str):
    body = get_json_body()
    applicant_id = require_string(body, "applicant_id")
    course_code = require_enum(body, "course_code", logic.COURSE_CODES)
    completed_raw, completed_dt = require_datetime(body, "completed_at")

    applicant = db.STORES["applicants"].get(applicant_id)
    if applicant is None:
        raise_err(ERR_APPLICANT_NOT_FOUND, "No applicant with the given id")

    expires_dt = db.add_months(completed_dt, logic.VALIDITY_MONTHS[course_code])
    rec = {
        "applicant_id": applicant_id,
        "course_code": course_code,
        "completed_at": completed_raw,
        "expires_at": db.fmt_clock(expires_dt),
        "_completed_dt": completed_dt,
        "_expires_dt": expires_dt,
    }
    db.stamp_append_only(rec)
    db.STORES["training_completions"][rec["id"]] = rec

    # Readiness evaluation runs on training-completion recording.
    now = db.clock_now()
    for app in db.STORES["applications"].values():
        if app["applicant_id"] == applicant_id and app["status"] in (
            "PENDING_REQUIREMENTS",
            "READY",
        ):
            logic.ready_evaluate(app, now)

    return success_object(serialize(rec), 201)


@bp.route("/applicants/<aid>/training-completions", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_training_completions(user_id: str, role: str, aid: str):
    fetch_or_404("applicants", aid, ERR_APPLICANT_NOT_FOUND, "applicant")
    limit, offset = parse_pagination()
    items = [
        t
        for t in db.STORES["training_completions"].values()
        if t["applicant_id"] == aid
    ]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)
