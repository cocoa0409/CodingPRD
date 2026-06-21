"""TouchUp fetch and schedule/deny state machine (PRD §3.10)."""
from flask import Blueprint

import db
from errors import ApiError
from helpers import get_json_body
from lookups import get_touchup, get_appointment
from middleware import require_auth
from response import success
from serializers import serialize_touchup

bp = Blueprint("touchups", __name__)


@bp.route("/studio/touchups/<touchup_id>", methods=["GET"])
@require_auth(["StudioManager", "Artist", "Client"])
def fetch_touchup(touchup_id):
    t = get_touchup(touchup_id)
    return success(serialize_touchup(t), 200)


@bp.route("/studio/touchups/<touchup_id>/schedule", methods=["POST"])
@require_auth(["StudioManager"])
def schedule_touchup(touchup_id):
    t = get_touchup(touchup_id)
    get_json_body()
    if t["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "schedule not allowed from %s" % t["status"])
    parent = db.appointments.get(t["parent_appointment_id"])
    if parent is None or parent["status"] != "COMPLETED":
        raise ApiError("ERR_TOUCHUP_PARENT_NOT_COMPLETED",
                       "Parent appointment is not COMPLETED")
    t["status"] = "SCHEDULED"
    db.touch(t)
    return success(serialize_touchup(t), 200)


@bp.route("/studio/touchups/<touchup_id>/deny", methods=["POST"])
@require_auth(["StudioManager"])
def deny_touchup(touchup_id):
    t = get_touchup(touchup_id)
    get_json_body()
    if t["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "deny not allowed from %s" % t["status"])
    t["status"] = "DENIED"
    db.touch(t)
    return success(serialize_touchup(t), 200)
