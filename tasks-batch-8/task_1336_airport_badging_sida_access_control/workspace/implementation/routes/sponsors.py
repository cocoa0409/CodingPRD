"""Sponsor endpoints (PRD §3.1, §3.9)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_SPONSOR_NOT_FOUND,
    ERR_SPONSOR_NOT_ACTIVE,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services import logic
from services.serializers import serialize_sponsor, serialize_list
from util import (
    fetch_or_404,
    get_json_body,
    paginate,
    parse_pagination,
    require_int,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("sponsors", __name__)


@bp.route("/sponsors", methods=["POST"])
@require_roles("SecurityManager")
def create_sponsor(user_id: str, role: str):
    body = get_json_body()
    name = require_string(body, "name")
    sponsor_code = require_string(body, "sponsor_code")
    quota = require_int(body, "active_badge_quota", minimum=1)

    for existing in db.STORES["sponsors"].values():
        if existing["sponsor_code"] == sponsor_code:
            raise_err(ERR_INVALID_REQUEST, "sponsor_code is already in use")

    rec = {
        "name": name,
        "sponsor_code": sponsor_code,
        "status": "ACTIVE",
        "active_badge_quota": quota,
        "suspended_at": None,
    }
    db.stamp_new(rec)
    db.STORES["sponsors"][rec["id"]] = rec
    return success_object(serialize_sponsor(rec), 201)


@bp.route("/sponsors/<sid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_sponsor(user_id: str, role: str, sid: str):
    sponsor = fetch_or_404("sponsors", sid, ERR_SPONSOR_NOT_FOUND, "sponsor")
    return success_object(serialize_sponsor(sponsor))


@bp.route("/sponsors/<sid>/suspend", methods=["POST"])
@require_roles("SecurityManager")
def suspend_sponsor(user_id: str, role: str, sid: str):
    sponsor = fetch_or_404("sponsors", sid, ERR_SPONSOR_NOT_FOUND, "sponsor")
    if sponsor["status"] != "ACTIVE":
        raise_err(ERR_SPONSOR_NOT_ACTIVE, "Sponsor must be ACTIVE to suspend")

    now = db.clock_now()
    sponsor["status"] = "SUSPENDED"
    sponsor["suspended_at"] = db.fmt_clock(now)
    db.touch(sponsor)

    # Cascade 1: non-terminal applications of this sponsor -> DENIED.
    for app in db.STORES["applications"].values():
        if app["sponsor_id"] == sid and app["status"] in logic.NON_TERMINAL_APP_STATUSES:
            app["status"] = "DENIED"
            app["denial_reason"] = "SPONSOR_SUSPENDED"
            db.touch(app)

    # Cascade 2: ACTIVE badges -> SUSPENDED (SPONSOR_SUSPENDED). Badges already
    # SUSPENDED keep their original suspension fields untouched.
    for badge in db.STORES["badges"].values():
        if badge["sponsor_id"] == sid and badge["status"] == "ACTIVE":
            # Cascade 3 fires inside suspend_badge: GRANTED escort privilege ->
            # REVOKED (BADGE_SUSPENDED) for each newly suspended badge.
            logic.suspend_badge(badge, by=user_id, reason="SPONSOR_SUSPENDED", until_dt=None)

    return success_object(serialize_sponsor(sponsor))


@bp.route("/sponsors/<sid>/applicants", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_sponsor_applicants(user_id: str, role: str, sid: str):
    fetch_or_404("sponsors", sid, ERR_SPONSOR_NOT_FOUND, "sponsor")
    limit, offset = parse_pagination()
    items = [a for a in db.STORES["applicants"].values() if a["sponsor_id"] == sid]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)
