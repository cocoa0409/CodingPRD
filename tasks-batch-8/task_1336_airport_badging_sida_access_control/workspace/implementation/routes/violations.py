"""Violation endpoints (PRD §3.8, §2.9)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_BADGE_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_VIOLATION_NOT_FOUND,
    ERR_VIOLATION_NOT_OPEN,
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
    require_datetime,
    require_enum,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("violations", __name__)


@bp.route("/violations", methods=["POST"])
@require_roles("BadgingOfficer")
def create_violation(user_id: str, role: str):
    body = get_json_body()
    badge_id = require_string(body, "badge_id")
    violation_type = require_enum(body, "violation_type", set(logic.POINTS))
    occurred_raw, occurred_dt = require_datetime(body, "occurred_at")

    badge = db.STORES["badges"].get(badge_id)
    if badge is None:
        raise_err(ERR_BADGE_NOT_FOUND, "No badge with the given id")

    rec = {
        "badge_id": badge_id,
        "violation_type": violation_type,
        "points": logic.POINTS[violation_type],
        "occurred_at": occurred_raw,
        "status": "RECORDED",
        "recorded_by": user_id,
        "sustained_by": None,
        "dismissed_by": None,
        "_occurred_dt": occurred_dt,
    }
    db.stamp_new(rec)
    db.STORES["violations"][rec["id"]] = rec
    return success_object(serialize(rec), 201)


@bp.route("/badges/<bid>/violations", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_violations(user_id: str, role: str, bid: str):
    fetch_or_404("badges", bid, ERR_BADGE_NOT_FOUND, "badge")
    limit, offset = parse_pagination()
    items = [v for v in db.STORES["violations"].values() if v["badge_id"] == bid]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/violations/<vid>/sustain", methods=["POST"])
@require_roles("SecurityManager")
def sustain_violation(user_id: str, role: str, vid: str):
    violation = fetch_or_404("violations", vid, ERR_VIOLATION_NOT_FOUND, "violation")
    if violation["status"] != "RECORDED":
        raise_err(ERR_VIOLATION_NOT_OPEN, "sustain requires a RECORDED violation")

    violation["status"] = "SUSTAINED"
    violation["sustained_by"] = user_id
    db.touch(violation)

    # Recompute holder windowed points and run the threshold cascade against
    # the badge this violation was recorded on.
    now = db.clock_now()
    badge = db.STORES["badges"].get(violation["badge_id"])
    if badge is not None:
        logic.apply_threshold_cascade(badge, user_id, now)

    return success_object(serialize(violation))


@bp.route("/violations/<vid>/dismiss", methods=["POST"])
@require_roles("SecurityManager")
def dismiss_violation(user_id: str, role: str, vid: str):
    violation = fetch_or_404("violations", vid, ERR_VIOLATION_NOT_FOUND, "violation")
    if violation["status"] not in ("RECORDED", "SUSTAINED"):
        raise_err(
            ERR_VIOLATION_NOT_OPEN,
            "dismiss requires a RECORDED or SUSTAINED violation",
        )

    # Priority 7: segregation of duties.
    if violation["status"] == "RECORDED" and violation["recorded_by"] == user_id:
        raise_err(
            ERR_SEGREGATION_OF_DUTIES,
            "Dismissing manager must differ from the recording officer",
        )
    if violation["status"] == "SUSTAINED" and violation["sustained_by"] == user_id:
        raise_err(
            ERR_SEGREGATION_OF_DUTIES,
            "Dismissing manager must differ from the sustaining manager",
        )

    violation["status"] = "DISMISSED"
    violation["dismissed_by"] = user_id
    db.touch(violation)
    # Points are recomputed on demand; a badge already suspended or revoked by
    # the threshold cascade is NOT automatically restored.
    return success_object(serialize(violation))
