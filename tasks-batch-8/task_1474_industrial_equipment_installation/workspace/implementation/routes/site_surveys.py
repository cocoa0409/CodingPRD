"""SiteSurvey endpoints."""
from flask import Blueprint

import db
from errors import (ApiError, ERR_ANCHOR_OUT_OF_TOLERANCE,
                    ERR_FOUNDATION_NOT_CURED, ERR_INVALID_STATE)
from helpers import project_or_404, sorted_items, survey_or_404, touch
from middleware import ROLES, require_roles
from response import success, success_list
from serialize import foundation_cured, survey_json
from util import new_id, now_iso
from validators import (get_body, opt_str, pagination, req_date, req_datetime,
                        req_int, req_num, req_enum, req_str)

bp = Blueprint("site_surveys", __name__)


@bp.post("/v1/site-surveys")
@require_roles("SiteSupervisor")
def create_survey():
    body = get_body()
    # existence (priority 3): a string project_id must resolve before schema runs
    pid = body.get("project_id")
    if isinstance(pid, str):
        project_or_404(pid)
    # schema (priority 7)
    pid = req_str(body, "project_id")
    survey_date = req_date(body, "survey_date")
    anchor_bolt_count = req_int(body, "anchor_bolt_count", gt=0)
    tol_raw, tol_d = req_num(body, "anchor_tolerance_mm", gt=0)
    dev_raw, dev_d = req_num(body, "anchor_measured_max_deviation_mm", ge=0)
    oh_raw, oh_d = req_num(body, "overhead_clearance_mm", gt=0)
    pour_dt = req_datetime(body, "foundation_pour_date")
    ts = now_iso()
    s = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "project_id": pid,
        "survey_date": survey_date.isoformat(),
        "anchor_bolt_count": anchor_bolt_count,
        "anchor_tolerance_mm": tol_raw,
        "anchor_measured_max_deviation_mm": dev_raw,
        "overhead_clearance_mm": oh_raw,
        "foundation_pour_date": body["foundation_pour_date"],
        # anchor_check_passed computed at creation; equality passes (PRD 3.2)
        "anchor_check_passed": bool(dev_d <= tol_d),
        "status": "DRAFT",
        "reviewer_note": None,
        "_pour_dt": pour_dt,
        "_seq": db.next_seq(),
    }
    db.site_surveys[s["id"]] = s
    return success(survey_json(s), 201)


@bp.get("/v1/projects/<pid>/site-surveys")
@require_roles(*ROLES)
def list_surveys(pid):
    project_or_404(pid)
    limit, offset = pagination()
    items = sorted_items(s for s in db.site_surveys.values() if s["project_id"] == pid)
    total = len(items)
    return success_list([survey_json(s) for s in items[offset:offset + limit]],
                        limit, offset, total)


@bp.post("/v1/site-surveys/<sid>/submit")
@require_roles("SiteSupervisor")
def submit_survey(sid):
    s = survey_or_404(sid)
    if s["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "only a DRAFT survey can be submitted")
    s["status"] = "SUBMITTED"
    touch(s)
    return success(survey_json(s))


@bp.post("/v1/site-surveys/<sid>/review")
@require_roles("ProjectManager")
def review_survey(sid):
    s = survey_or_404(sid)
    # state (priority 5)
    if s["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "only a SUBMITTED survey can be reviewed")
    # schema (priority 7)
    body = get_body()
    outcome = req_enum(body, "outcome", ("ACCEPTED", "REJECTED"))
    note = opt_str(body, "reviewer_note")
    if outcome == "ACCEPTED":
        # measurement constraints (priorities 18-19)
        if not s["anchor_check_passed"]:
            raise ApiError(ERR_ANCHOR_OUT_OF_TOLERANCE, 409,
                           "measured anchor deviation exceeds tolerance")
        if not foundation_cured(s):
            raise ApiError(ERR_FOUNDATION_NOT_CURED, 409,
                           "foundation has not cured for the minimum 7 days")
    s["status"] = outcome
    s["reviewer_note"] = note
    touch(s)
    return success(survey_json(s))
