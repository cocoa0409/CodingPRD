"""Participant endpoints: register/list/get/activate/verify/suspend/reinstate/ban."""

import db
from middleware import require_roles
from response import success, parse_pagination, paginate_list
from routes import make_blueprint
from util import (
    get_payload, require_string, require_int, require_array,
    stamp_new, touch, check_unique,
)
from errors import (
    raise_error, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_INVALID_REQUEST,
    ERR_OPEN_BREACH_EXISTS,
)
from services.serializers import public
from services.cascade import suspend_participant_cascade, ban_participant_cascade

bp = make_blueprint("participants")


def _get_participant(pid):
    p = db.participants.get(pid)
    if p is None:
        raise_error(ERR_NOT_FOUND, "Participant not found")
    return p


@bp.route("/playtests/participants", methods=["POST"])
def create_participant():
    require_roles("ResearchOpsAdmin")
    body = get_payload()
    email = require_string(body, "email")
    full_name = require_string(body, "full_name")
    age_years = require_int(body, "age_years", minimum=13)
    region_code = require_string(body, "region_code")
    platform_tags = require_array(body, "platform_tags")
    check_unique(db.participants, "email", email)
    rec = {
        "email": email,
        "full_name": full_name,
        "age_years": age_years,
        "region_code": region_code,
        "platform_tags": list(platform_tags),
        "verified_platform_tags": [],
        "status": "REGISTERED",
        "no_show_strikes": 0,
        "risk_score": 0,
    }
    stamp_new(rec)
    db.participants[rec["id"]] = rec
    return success(public(rec, "participant"), status=201)


@bp.route("/playtests/participants", methods=["GET"])
def list_participants():
    require_roles("ResearchOpsAdmin", "Researcher", "IncentiveOfficer", "LegalCounsel", "Moderator")
    from flask import request
    limit, offset = parse_pagination(request.args)
    items = list(db.participants.values())
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    region = request.args.get("region_code")
    if region is not None:
        items = [p for p in items if p["region_code"] == region]
    page, pagination = paginate_list(items, limit, offset)
    return success([public(p, "participant") for p in page], status=200, pagination=pagination)


@bp.route("/playtests/participants/<pid>", methods=["GET"])
def get_participant(pid):
    require_roles("ResearchOpsAdmin", "Researcher", "IncentiveOfficer", "LegalCounsel",
                  "Moderator", "Participant")
    p = _get_participant(pid)
    return success(public(p, "participant"), status=200)


@bp.route("/playtests/participants/<pid>/activate", methods=["POST"])
def activate_participant(pid):
    require_roles("ResearchOpsAdmin")
    p = _get_participant(pid)
    if p["status"] != "REGISTERED":
        raise_error(ERR_INVALID_STATE, "Participant must be REGISTERED to activate")
    p["status"] = "ACTIVE"
    touch(p)
    return success(public(p, "participant"), status=200)


@bp.route("/playtests/participants/<pid>/verify-attributes", methods=["POST"])
def verify_attributes(pid):
    require_roles("ResearchOpsAdmin")
    p = _get_participant(pid)
    body = get_payload()
    tags = require_array(body, "verified_platform_tags")
    p["verified_platform_tags"] = list(tags)
    touch(p)
    return success(public(p, "participant"), status=200)


@bp.route("/playtests/participants/<pid>/suspend", methods=["POST"])
def suspend_participant(pid):
    require_roles("ResearchOpsAdmin")
    p = _get_participant(pid)
    if p["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "Participant must be ACTIVE to suspend")
    suspend_participant_cascade(p)
    return success(public(p, "participant"), status=200)


@bp.route("/playtests/participants/<pid>/reinstate", methods=["POST"])
def reinstate_participant(pid):
    require_roles("ResearchOpsAdmin")
    p = _get_participant(pid)
    if p["status"] != "SUSPENDED":
        raise_error(ERR_INVALID_STATE, "Participant must be SUSPENDED to reinstate")
    # Compliance gate: blocked while any breach case is open
    for case in db.breach_cases.values():
        if case["participant_id"] == p["id"] and case["status"] in (
            "REPORTED", "UNDER_INVESTIGATION", "SUBSTANTIATED",
        ):
            raise_error(ERR_OPEN_BREACH_EXISTS,
                        "Reinstate blocked while a breach case is open")
    p["status"] = "ACTIVE"
    p["no_show_strikes"] = 0
    touch(p)
    return success(public(p, "participant"), status=200)


@bp.route("/playtests/participants/<pid>/ban", methods=["POST"])
def ban_participant(pid):
    require_roles("LegalCounsel")
    p = _get_participant(pid)
    if p["status"] not in ("ACTIVE", "SUSPENDED"):
        raise_error(ERR_INVALID_STATE, "Participant must be ACTIVE or SUSPENDED to ban")
    ban_participant_cascade(p)
    return success(public(p, "participant"), status=200)
