"""BadgeAward routes (PRD §3.7)."""
from flask import Blueprint

import errors
from errors import err
from db import db
from response import success
from serialize import out
from middleware import get_auth, require_role
from validators import get_body, parse_pagination
from services import lookup
from services.member_service import recompute_active_badge_count
from routes.common import arg, paginate

bp = Blueprint("badge_awards", __name__)


@bp.route("/badge-awards", methods=["POST"])
def create_badge_award():
    _, role = get_auth()
    require_role(role, {"Instructor", "CenterAdmin"})
    body = get_body()
    enrollment_id = body.get("enrollment_id")
    enrollment = lookup.require_enrollment(enrollment_id)
    badge_id = body.get("badge_id")
    lookup.require_badge(badge_id)
    rec = db.make({
        "enrollment_id": enrollment_id,
        "badge_id": badge_id,
        "status": "ACTIVE",
    })
    db.badge_awards[rec["id"]] = rec
    # cascade: recompute member.active_badge_count; bump member version.
    member = db.members.get(enrollment["member_id"])
    if member is not None:
        recompute_active_badge_count(member)
        db.touch(member)
    return success(out(rec), status=201)


@bp.route("/badge-awards/<rid>", methods=["GET"])
def get_badge_award(rid):
    _, role = get_auth()
    require_role(role, {"CenterAdmin", "Instructor", "Guardian"})
    rec = lookup.require_badge_award(rid)
    return success(out(rec))


@bp.route("/badge-awards", methods=["GET"])
def list_badge_awards():
    _, role = get_auth()
    require_role(role, {"CenterAdmin", "Instructor", "Guardian"})
    limit, offset = parse_pagination()
    enrollment_id = arg("enrollment_id")
    badge_id = arg("badge_id")
    items = [a for a in db.badge_awards.values()
             if (enrollment_id is None or a["enrollment_id"] == enrollment_id)
             and (badge_id is None or a["badge_id"] == badge_id)]
    return paginate(items, limit, offset)


@bp.route("/badge-awards/<rid>/revoke", methods=["POST"])
def revoke_badge_award(rid):
    _, role = get_auth()
    require_role(role, {"Instructor", "CenterAdmin"})
    award = lookup.require_badge_award(rid)
    if award["status"] != "ACTIVE":
        raise err(errors.ERR_INVALID_STATE, "BadgeAward is not ACTIVE.")
    award["status"] = "REVOKED"
    db.touch(award)
    enrollment = db.enrollments.get(award["enrollment_id"])
    if enrollment is not None:
        member = db.members.get(enrollment["member_id"])
        if member is not None:
            recompute_active_badge_count(member)
            db.touch(member)
    return success(out(award))
