"""SelfExclusion endpoints — drives the depth-3 cascade."""
from datetime import timedelta

from flask import Blueprint, request

import clock
import db
from auth import require_role
from common import (
    get_json_or_400, require_str, require_iso_datetime,
    parse_pagination, paginate, stamp_audit_create, stamp_update,
    get_or_404, fk_or_404,
)
from errors import (
    ApiError, ERR_INVALID_STATE, ERR_EXCLUSION_PERIOD_TOO_SHORT,
    ERR_UNAUTHORIZED,
)
from response import success_object, success_array
from services.serializers import self_exclusion_view
from services.cascades import cascade_on_exclusion


bp = Blueprint("self_exclusions", __name__)

MIN_EXCLUSION_DAYS = 365


@bp.route("/self-exclusions", methods=["POST"])
def create_self_exclusion():
    uid, role = require_role({"Member"})
    body = get_json_or_400()
    member_id = require_str(body, "member_id")
    exclusion_until_dt = require_iso_datetime(body, "exclusion_until")
    reason = require_str(body, "reason")

    with db.lock:
        member = fk_or_404(db.members, member_id, "member")

        # Member identity ownership.
        if uid != member_id:
            raise ApiError(ERR_UNAUTHORIZED, 403,
                           "members may only self-exclude their own member id")

        # priority 4: at most one ACTIVE SelfExclusion per member.
        for s in db.self_exclusions.values():
            if s["member_id"] == member_id and s["status"] == "ACTIVE":
                raise ApiError(ERR_INVALID_STATE, 409,
                               "active self-exclusion already exists for member")

        requested_at_dt = clock.now()

        # priority 8: regulator-mandated minimum exclusion period.
        if (exclusion_until_dt - requested_at_dt) < timedelta(days=MIN_EXCLUSION_DAYS):
            raise ApiError(ERR_EXCLUSION_PERIOD_TOO_SHORT, 422,
                           "exclusion_until must be at least 365 days from requested_at")

        row = {
            "member_id": member_id,
            "requested_at": clock.iso(requested_at_dt),
            "exclusion_until": clock.iso(exclusion_until_dt),
            "reason": reason,
            "status": "ACTIVE",
        }
        stamp_audit_create(row)
        db.self_exclusions[row["id"]] = row

        # State machine on member.exclusion_status (NOT_EXCLUDED|REINSTATED -> EXCLUDED).
        member["exclusion_status"] = "EXCLUDED"
        cascade_on_exclusion(member)
        stamp_update(member)

        return success_object(self_exclusion_view(row), 201)


@bp.route("/self-exclusions/<sid>/reinstate", methods=["POST"])
def reinstate_self_exclusion(sid):
    uid, _ = require_role({"Member"})
    with db.lock:
        s = get_or_404(db.self_exclusions, sid, "self exclusion")

        if uid != s["member_id"]:
            raise ApiError(ERR_UNAUTHORIZED, 403,
                           "members may only reinstate their own self-exclusion")

        if s["status"] != "ACTIVE":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "self-exclusion is not ACTIVE")

        exclusion_until_dt = clock.parse_iso(s["exclusion_until"])
        now = clock.now()
        if not (now >= exclusion_until_dt):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "exclusion_until has not yet elapsed")

        s["status"] = "REINSTATED"
        member = db.members.get(s["member_id"])
        if member is not None:
            member["exclusion_status"] = "REINSTATED"
            stamp_update(member)

        return success_object(self_exclusion_view(s), 200)


@bp.route("/self-exclusions/<sid>", methods=["GET"])
def get_self_exclusion(sid):
    uid, role = require_role({"Member", "ComplianceOfficer"})
    with db.lock:
        s = get_or_404(db.self_exclusions, sid, "self exclusion")
        if role == "Member" and uid != s["member_id"]:
            raise ApiError(ERR_UNAUTHORIZED, 403,
                           "members may only read their own self-exclusions")
        return success_object(self_exclusion_view(s), 200)


@bp.route("/self-exclusions", methods=["GET"])
def list_self_exclusions():
    uid, role = require_role({"ComplianceOfficer", "Member"})
    member_id = request.args.get("member_id")
    status = request.args.get("status")
    limit, offset = parse_pagination()
    with db.lock:
        rows = list(db.self_exclusions.values())
        if role == "Member":
            rows = [r for r in rows if r["member_id"] == uid]
        if member_id is not None:
            rows = [r for r in rows if r["member_id"] == member_id]
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        rows.sort(key=lambda r: r["created_at"])
        page, total = paginate(rows, limit, offset)
        return success_array([self_exclusion_view(r) for r in page], limit, offset, total, 200)
