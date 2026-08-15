"""TimeSlot endpoints: get, block, unblock."""

from flask import Blueprint

import db
import errors
import middleware
import response
import serializers
import util
from services import core

bp = Blueprint("slots", __name__)

ALL_ROLES = {"SchoolAdmin", "FrontOfficeStaff", "Teacher", "FamilyGuardian", "Interpreter"}
BLOCK_ROLES = {"SchoolAdmin", "FrontOfficeStaff", "Teacher"}


@bp.route("/conf/slots/<sid>", methods=["GET"])
def get_slot(sid):
    role, _uid = middleware.get_auth()
    middleware.require_roles(role, ALL_ROLES)
    slot = core.get_slot_or_404(sid)
    return response.success_object(serializers.slot_view(slot))


@bp.route("/conf/slots/<sid>/block", methods=["POST"])
def block_slot(sid):
    role, uid = middleware.get_auth()
    middleware.require_roles(role, BLOCK_ROLES)
    util.get_body()  # optional reason
    slot = core.get_slot_or_404(sid)
    window = core.get_window_or_404(slot["window_id"])
    middleware.check_teacher_owns(role, uid, slot["teacher_id"])
    if window["status"] not in ("PUBLISHED", "BOOKING_OPEN"):
        raise errors.invalid_window_state("block requires PUBLISHED or BOOKING_OPEN")
    if slot["status"] != "OPEN":
        raise errors.slot_not_available("only an OPEN slot can be blocked")
    slot["status"] = "BLOCKED"
    slot["version"] += 1
    slot["updated_at"] = util.now_iso()
    return response.success_object(serializers.slot_view(slot))


@bp.route("/conf/slots/<sid>/unblock", methods=["POST"])
def unblock_slot(sid):
    role, uid = middleware.get_auth()
    middleware.require_roles(role, BLOCK_ROLES)
    util.get_body()
    slot = core.get_slot_or_404(sid)
    window = core.get_window_or_404(slot["window_id"])
    middleware.check_teacher_owns(role, uid, slot["teacher_id"])
    if window["status"] not in ("PUBLISHED", "BOOKING_OPEN"):
        raise errors.invalid_window_state("unblock requires PUBLISHED or BOOKING_OPEN")
    if slot["status"] != "BLOCKED":
        raise errors.invalid_state("only a BLOCKED slot can be unblocked")
    slot["status"] = "OPEN"
    slot["version"] += 1
    slot["updated_at"] = util.now_iso()
    core.run_promotion(slot)
    return response.success_object(serializers.slot_view(slot))
