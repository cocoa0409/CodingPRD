"""ScheduleMilestone endpoints."""

from flask import Blueprint, request

from db import store
from middleware import require_roles, check_contractor_ownership
from response import success_object, success_created, success_list
from errors import (
    not_found, invalid_request, invalid_state, APIError,
    ERR_SCHEDULE_OVERLAP, ERR_INVALID_WINDOW, ERR_MILESTONE_WINDOW_NOT_ENDED,
)
from services.util import (
    make_common_fields, bump_version, get_pagination_params, paginate,
    require_fields, is_str, parse_iso8601, to_iso_z, logical_clock_dt,
)
from services import calc

bp = Blueprint("milestones", __name__)


def _get_ms_or_404(mid):
    m = store.schedule_milestones.get(mid)
    if not m:
        raise not_found("ScheduleMilestone not found")
    return m


@bp.route("/api/contractor-engagements/<id>/milestones", methods=["POST"])
def create_milestone(id):
    user_id, role = require_roles("ContractorRep")
    eng = store.contractor_engagements.get(id)
    if not eng:
        raise not_found("ContractorEngagement not found")
    check_contractor_ownership(user_id, eng["id"])

    body = request.get_json(silent=True) or {}
    require_fields(body, ["milestone_name", "window_start", "window_end", "work_type"])
    if not is_str(body["milestone_name"]):
        raise invalid_request("milestone_name must be a string")
    try:
        ws = parse_iso8601(body["window_start"])
    except Exception:
        raise invalid_request("window_start must be valid ISO8601")
    try:
        we = parse_iso8601(body["window_end"])
    except Exception:
        raise invalid_request("window_end must be valid ISO8601")
    if body["work_type"] not in ("STANDARD", "NOISY", "HOT_WORK", "FREIGHT"):
        raise invalid_request("work_type must be STANDARD, NOISY, HOT_WORK, or FREIGHT")

    ws_iso = to_iso_z(ws)
    we_iso = to_iso_z(we)

    # Overlap check before window shape (per PRD §2.7)
    if not calc.check_milestone_overlap(id, ws_iso, we_iso):
        raise APIError(ERR_SCHEDULE_OVERLAP, 409,
                       "Milestone window overlaps another PLANNED/CONFIRMED milestone")
    if we <= ws:
        raise APIError(ERR_INVALID_WINDOW, 422,
                       "window_end must be strictly after window_start")

    # Engagement must be ACTIVE for confirmation
    initial_status = "PLANNED"
    if body["work_type"] == "STANDARD":
        if eng["status"] != "ACTIVE":
            raise invalid_state("Engagement must be ACTIVE for STANDARD milestone auto-confirm")
        initial_status = "CONFIRMED"

    rec = make_common_fields()
    rec.update({
        "engagement_id": id,
        "milestone_name": body["milestone_name"],
        "window_start": ws_iso,
        "window_end": we_iso,
        "work_type": body["work_type"],
        "status": initial_status,
    })
    store.schedule_milestones[rec["id"]] = rec
    return success_created(rec)


@bp.route("/api/contractor-engagements/<id>/milestones", methods=["GET"])
def list_milestones(id):
    user_id, role = require_roles(
        "LandlordPM", "LandlordApprover", "ContractorRep", "BuildingEngineer"
    )
    eng = store.contractor_engagements.get(id)
    if not eng:
        raise not_found("ContractorEngagement not found")
    if role == "ContractorRep":
        check_contractor_ownership(user_id, eng["id"])
    limit, offset = get_pagination_params()
    items = [m for m in store.schedule_milestones.values() if m["engagement_id"] == id]
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/api/schedule-milestones/<id>", methods=["GET"])
def get_milestone(id):
    user_id, role = require_roles(
        "LandlordPM", "LandlordApprover", "ContractorRep", "BuildingEngineer"
    )
    m = _get_ms_or_404(id)
    if role == "ContractorRep":
        check_contractor_ownership(user_id, m["engagement_id"])
    return success_object(m)


@bp.route("/api/schedule-milestones/<id>/confirm", methods=["POST"])
def confirm_milestone(id):
    require_roles("LandlordPM")
    m = _get_ms_or_404(id)
    if m["status"] != "PLANNED":
        raise invalid_state("Milestone must be in PLANNED to confirm")

    eng = store.contractor_engagements.get(m["engagement_id"])
    if not eng:
        raise not_found("ContractorEngagement not found")
    if eng["status"] != "ACTIVE":
        raise invalid_state("Engagement must be ACTIVE to confirm milestone")

    # Overlap check
    if not calc.check_milestone_overlap(
        m["engagement_id"], m["window_start"], m["window_end"], exclude_id=m["id"]
    ):
        raise APIError(ERR_SCHEDULE_OVERLAP, 409,
                       "Milestone window overlaps another PLANNED/CONFIRMED milestone")

    m["status"] = "CONFIRMED"
    bump_version(m)
    return success_object(m)


@bp.route("/api/schedule-milestones/<id>/complete", methods=["POST"])
def complete_milestone(id):
    user_id, role = require_roles("ContractorRep")
    m = _get_ms_or_404(id)
    check_contractor_ownership(user_id, m["engagement_id"])
    if m["status"] != "CONFIRMED":
        raise invalid_state("Milestone must be in CONFIRMED to complete")

    # Clock must be >= window_end
    clock = logical_clock_dt()
    we = parse_iso8601(m["window_end"])
    if clock < we:
        raise APIError(ERR_MILESTONE_WINDOW_NOT_ENDED, 422,
                       "Current logical clock has not reached window_end")

    m["status"] = "COMPLETED"
    bump_version(m)
    return success_object(m)


@bp.route("/api/schedule-milestones/<id>/cancel", methods=["POST"])
def cancel_milestone(id):
    require_roles("LandlordPM")
    m = _get_ms_or_404(id)
    if m["status"] not in ("PLANNED", "CONFIRMED"):
        raise invalid_state("Milestone must be in PLANNED or CONFIRMED to cancel")
    m["status"] = "CANCELLED"
    bump_version(m)
    return success_object(m)
