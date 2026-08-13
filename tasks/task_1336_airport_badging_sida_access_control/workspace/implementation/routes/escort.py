"""Escort privilege endpoints (PRD §3.6, §2.11)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_BADGE_NOT_ACTIVE,
    ERR_BADGE_NOT_FOUND,
    ERR_ESCORT_NOT_GRANTED,
    ERR_ESCORT_PRIVILEGE_NOT_FOUND,
    ERR_STALE_VERSION,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services import logic
from services.serializers import serialize, serialize_list
from util import (
    fetch_or_404,
    get_json_body,
    paginate,
    parse_pagination,
    require_int,
    sort_by_created_at,
)

bp = Blueprint("escort", __name__)


@bp.route("/badges/<bid>/escort-privileges", methods=["POST"])
@require_roles("SecurityManager")
def grant_escort_privilege(user_id: str, role: str, bid: str):
    badge = fetch_or_404("badges", bid, ERR_BADGE_NOT_FOUND, "badge")
    body = get_json_body()
    max_escortees = require_int(body, "max_escortees", minimum=1, maximum=10)
    expected_version = require_int(body, "expected_badge_version")

    # Priority 5: state gate (evaluated before the OCC check, PRD §2.11).
    if badge["status"] != "ACTIVE":
        raise_err(ERR_BADGE_NOT_ACTIVE, "escort grant requires the badge to be ACTIVE")

    # Priority 6: optimistic concurrency.
    if expected_version != badge["version"]:
        raise_err(
            ERR_STALE_VERSION,
            "expected_badge_version does not match the badge's current version",
        )

    # A new grant supersedes any currently GRANTED privilege.
    logic.revoke_granted_privilege(badge["id"], "SUPERSEDED")

    rec = {
        "badge_id": badge["id"],
        "max_escortees": max_escortees,
        "status": "GRANTED",
        "granted_by": user_id,
        "revoked_reason": None,
    }
    db.stamp_new(rec)
    db.STORES["escort_privileges"][rec["id"]] = rec

    # The grant advances the badge's version by one.
    db.touch(badge)

    return success_object(serialize(rec), 201)


@bp.route("/badges/<bid>/escort-privileges", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_escort_privileges(user_id: str, role: str, bid: str):
    fetch_or_404("badges", bid, ERR_BADGE_NOT_FOUND, "badge")
    limit, offset = parse_pagination()
    items = [
        p
        for p in db.STORES["escort_privileges"].values()
        if p["badge_id"] == bid
    ]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/escort-privileges/<pid>/revoke", methods=["POST"])
@require_roles("SecurityManager")
def revoke_escort_privilege(user_id: str, role: str, pid: str):
    priv = fetch_or_404(
        "escort_privileges", pid, ERR_ESCORT_PRIVILEGE_NOT_FOUND, "escort privilege"
    )
    if priv["status"] != "GRANTED":
        raise_err(ERR_ESCORT_NOT_GRANTED, "revoke requires the privilege to be GRANTED")
    priv["status"] = "REVOKED"
    priv["revoked_reason"] = "MANUAL"
    db.touch(priv)
    return success_object(serialize(priv))
