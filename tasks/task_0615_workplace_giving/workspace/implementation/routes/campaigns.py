"""Campaign endpoints (PRD §3.4)."""
from flask import Blueprint, request

from db import db
from errors import (
    err,
    ERR_INVALID_STATE,
    ERR_CHARITY_NOT_APPROVED,
    ERR_PROGRAM_NOT_ACTIVE,
    ERR_INVALID_REQUEST,
)
from middleware import get_user_context, require_role
from response import object_response, array_response
from services.common import (
    get_json_body,
    require_fields,
    require_string,
    require_positive_int,
    require_datetime,
    stamp_create,
    touch,
    serialize,
    find_or_404,
    paginate,
)

bp = Blueprint("campaigns", __name__)


@bp.route("/campaigns", methods=["POST"])
def create_campaign():
    _uid, role = get_user_context()
    require_role(role, {"ProgramManager"})
    body = get_json_body()
    require_fields(body, ["program_id", "charity_id", "name", "goal_cents", "window_start", "window_end"])
    program_id = require_string(body, "program_id")
    charity_id = require_string(body, "charity_id")
    name = require_string(body, "name")
    goal = require_positive_int(body, "goal_cents")  # goal_cents > 0
    window_start = require_datetime(body, "window_start")
    window_end = require_datetime(body, "window_end")

    find_or_404(db.programs, program_id)
    find_or_404(db.charities, charity_id)

    rec = {
        "program_id": program_id,
        "charity_id": charity_id,
        "name": name,
        "goal_cents": goal,
        "window_start": window_start,
        "window_end": window_end,
        "raised_cents": 0,
        "status": "DRAFT",
    }
    stamp_create(rec)
    db.campaigns[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/campaigns/<campaign_id>", methods=["GET"])
def get_campaign(campaign_id):
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin", "ProgramManager", "Employee"})
    rec = find_or_404(db.campaigns, campaign_id)
    return object_response(serialize(rec), 200)


@bp.route("/campaigns", methods=["GET"])
def list_campaigns():
    _uid, role = get_user_context()
    require_role(role, {"GivingAdmin", "ProgramManager", "Employee"})
    program_id = request.args.get("program_id")
    charity_id = request.args.get("charity_id")
    status = request.args.get("status")
    items = []
    for c in db.campaigns.values():
        if program_id is not None and c["program_id"] != program_id:
            continue
        if charity_id is not None and c["charity_id"] != charity_id:
            continue
        if status is not None and c["status"] != status:
            continue
        items.append(c)
    page, limit, offset, total = paginate(items)
    return array_response([serialize(c) for c in page], limit, offset, total, 200)


@bp.route("/campaigns/<campaign_id>/launch", methods=["POST"])
def launch_campaign(campaign_id):
    _uid, role = get_user_context()
    require_role(role, {"ProgramManager"})
    rec = find_or_404(db.campaigns, campaign_id)
    # State first, then charity-approved, then program-active (PRD §3.4 order).
    if rec["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Campaign must be DRAFT to launch")
    charity = db.charities.get(rec["charity_id"])
    if charity is None or charity["status"] != "APPROVED":
        raise err(ERR_CHARITY_NOT_APPROVED, "Referenced charity must be APPROVED")
    program = db.programs.get(rec["program_id"])
    if program is None or program["status"] != "ACTIVE":
        raise err(ERR_PROGRAM_NOT_ACTIVE, "Owning program must be ACTIVE")
    rec["status"] = "LIVE"
    touch(rec)
    return object_response(serialize(rec), 200)


@bp.route("/campaigns/<campaign_id>/pause", methods=["POST"])
def pause_campaign(campaign_id):
    _uid, role = get_user_context()
    require_role(role, {"ProgramManager"})
    rec = find_or_404(db.campaigns, campaign_id)
    if rec["status"] != "LIVE":
        raise err(ERR_INVALID_STATE, "Campaign must be LIVE to pause")
    rec["status"] = "PAUSED"
    touch(rec)
    return object_response(serialize(rec), 200)


@bp.route("/campaigns/<campaign_id>/resume", methods=["POST"])
def resume_campaign(campaign_id):
    _uid, role = get_user_context()
    require_role(role, {"ProgramManager"})
    rec = find_or_404(db.campaigns, campaign_id)
    if rec["status"] != "PAUSED":
        raise err(ERR_INVALID_STATE, "Campaign must be PAUSED to resume")
    charity = db.charities.get(rec["charity_id"])
    if charity is None or charity["status"] != "APPROVED":
        raise err(ERR_CHARITY_NOT_APPROVED, "Referenced charity must be APPROVED to resume")
    rec["status"] = "LIVE"
    touch(rec)
    return object_response(serialize(rec), 200)


@bp.route("/campaigns/<campaign_id>/end", methods=["POST"])
def end_campaign(campaign_id):
    _uid, role = get_user_context()
    require_role(role, {"ProgramManager"})
    rec = find_or_404(db.campaigns, campaign_id)
    if rec["status"] not in ("LIVE", "PAUSED"):
        raise err(ERR_INVALID_STATE, "Campaign must be LIVE or PAUSED to end")
    rec["status"] = "ENDED"
    touch(rec)
    return object_response(serialize(rec), 200)
