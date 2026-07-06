from flask import Blueprint, request
from db import db
from middleware import require_user_context, require_role
from response import object_response, array_response
from services.common import bump, public, paginate, sorted_by_creation
from services.lookup import get_or_404
from errors import err

bp = Blueprint("referrals", __name__)

READ_ROLES = {"ProgramManager", "PatientNavigator", "ClinicalStaff"}


@bp.route("/referrals", methods=["GET"])
def list_referrals():
    _, role = require_user_context()
    require_role(role, READ_ROLES)
    items = list(db.referrals.values())
    for f in ("appointment_id", "participant_id", "status"):
        val = request.args.get(f)
        if val is not None:
            items = [r for r in items if r[f] == val]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(items)
    return array_response([public(r) for r in page], limit, offset, total)


@bp.route("/referrals/<rid>", methods=["GET"])
def get_referral(rid):
    _, role = require_user_context()
    require_role(role, READ_ROLES)
    return object_response(public(get_or_404("referrals", rid)), 200)


def _transition(rid, allowed_from, to):
    _, role = require_user_context()
    require_role(role, {"PatientNavigator"})
    ref = get_or_404("referrals", rid)
    if ref["status"] not in allowed_from:
        raise err("ERR_INVALID_STATE", "Referral not in %s" % list(allowed_from))
    ref["status"] = to
    bump(ref)
    return object_response(public(ref), 200)


@bp.route("/referrals/<rid>/contact", methods=["POST"])
def contact(rid):
    return _transition(rid, {"OPEN"}, "CONTACTED")


@bp.route("/referrals/<rid>/schedule-followup", methods=["POST"])
def schedule_followup(rid):
    return _transition(rid, {"CONTACTED"}, "SCHEDULED_FOLLOWUP")


@bp.route("/referrals/<rid>/resolve", methods=["POST"])
def resolve(rid):
    return _transition(rid, {"SCHEDULED_FOLLOWUP"}, "RESOLVED")


@bp.route("/referrals/<rid>/mark-lost", methods=["POST"])
def mark_lost(rid):
    return _transition(rid, {"OPEN", "CONTACTED", "SCHEDULED_FOLLOWUP"}, "LOST_TO_FOLLOWUP")
