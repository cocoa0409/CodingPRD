"""Barn washes (PRD §3.6, §2.10): grower records on a WASH_REQUIRED barn;
verification starts the 72-hour downtime, rejection reverts to WASH_REQUIRED."""

from flask import Blueprint, request
from datetime import timedelta

from db import store
from errors import (
    conflict, malformed, segregation_of_duties,
    ERR_INVALID_STATE_TRANSITION, ERR_WASH_TYPE_INSUFFICIENT,
)
from middleware import (
    require_roles, check_grower_ownership, barn_owner_id,
    ROLE_INTEGRATOR_ADMIN, ROLE_GROWER, ROLE_FIELD_TECH,
)
from response import success_object, paginate
from services.core import new_record, touch, ser_barn_wash, BARN_DOWNTIME_HOURS
from util import get_body, req, as_str, as_datetime, as_enum, load_or_404

bp = Blueprint("barn_washes", __name__)

ROLES_READ = [ROLE_INTEGRATOR_ADMIN, ROLE_GROWER, ROLE_FIELD_TECH]
WASH_TYPES = {"FULL_DISINFECT", "WASH_ONLY"}


@bp.route("/barn-washes", methods=["POST"])
def create_barn_wash():
    role, user_id = require_roles([ROLE_GROWER])
    body = get_body()
    barn_id = as_str(req(body, "barn_id"), "barn_id")
    barn = load_or_404(store.barns, barn_id, "Barn")
    # grower ownership: the barn's ACTIVE contract must resolve to the caller
    check_grower_ownership(role, user_id, barn_owner_id(barn))
    wash_type = as_enum(req(body, "wash_type"), "wash_type", WASH_TYPES)
    completed_at = as_datetime(req(body, "completed_at"), "completed_at")
    if completed_at > store.now():
        raise malformed("completed_at must not lie in the future")
    # recording is accepted only while the barn is in WASH_REQUIRED
    if barn["barn_status"] != "WASH_REQUIRED":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       f"Cannot record a barn wash while the barn is {barn['barn_status']}")
    rec = new_record()
    rec.update({
        "barn_id": barn_id, "wash_type": wash_type, "completed_at": completed_at,
        "recorded_by": user_id, "verified_by": None, "wash_status": "RECORDED",
    })
    store.barn_washes[rec["id"]] = rec
    # the wash's arrival moves the barn WASH_REQUIRED -> WASHING
    barn["barn_status"] = "WASHING"
    touch(barn)
    return success_object(ser_barn_wash(rec), 201)


@bp.route("/barn-washes", methods=["GET"])
def list_barn_washes():
    require_roles(ROLES_READ)
    barn_id = request.args.get("barn_id")
    status = request.args.get("wash_status")
    items = list(store.barn_washes.values())
    if barn_id is not None:
        items = [w for w in items if w["barn_id"] == barn_id]
    if status is not None:
        items = [w for w in items if w["wash_status"] == status]
    return paginate(items, request.args, ser_barn_wash)


@bp.route("/barn-washes/<wid>", methods=["GET"])
def get_barn_wash(wid):
    require_roles(ROLES_READ)
    return success_object(ser_barn_wash(load_or_404(store.barn_washes, wid, "BarnWash")))


@bp.route("/barn-washes/<wid>/verify", methods=["POST"])
def verify_barn_wash(wid):
    role, user_id = require_roles([ROLE_INTEGRATOR_ADMIN])
    wash = load_or_404(store.barn_washes, wid, "BarnWash")
    if wash["wash_status"] != "RECORDED":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       f"Cannot verify a wash in {wash['wash_status']}")
    # SoD: verifier != recorder (§2.11)
    if user_id == wash["recorded_by"]:
        raise segregation_of_duties("Verifier must differ from the wash recorder")
    # biosecurity (8): only a FULL_DISINFECT wash returns a barn to service
    if wash["wash_type"] != "FULL_DISINFECT":
        raise conflict(ERR_WASH_TYPE_INSUFFICIENT, "WASH_ONLY never suffices")
    wash["wash_status"] = "VERIFIED"
    wash["verified_by"] = user_id
    touch(wash)
    # barn WASHING -> DOWNTIME with downtime_until := completed_at + 72h
    barn = store.barns.get(wash["barn_id"])
    if barn is not None and barn["barn_status"] == "WASHING":
        barn["barn_status"] = "DOWNTIME"
        barn["downtime_until"] = wash["completed_at"] + timedelta(hours=BARN_DOWNTIME_HOURS)
        touch(barn)
    return success_object(ser_barn_wash(wash))


@bp.route("/barn-washes/<wid>/reject", methods=["POST"])
def reject_barn_wash(wid):
    role, user_id = require_roles([ROLE_INTEGRATOR_ADMIN])
    wash = load_or_404(store.barn_washes, wid, "BarnWash")
    if wash["wash_status"] != "RECORDED":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       f"Cannot reject a wash in {wash['wash_status']}")
    if user_id == wash["recorded_by"]:
        raise segregation_of_duties("Rejecter must differ from the wash recorder")
    wash["wash_status"] = "REJECTED"
    touch(wash)
    # rejection sends the barn WASHING -> WASH_REQUIRED (it awaits a proper wash)
    barn = store.barns.get(wash["barn_id"])
    if barn is not None and barn["barn_status"] == "WASHING":
        barn["barn_status"] = "WASH_REQUIRED"
        touch(barn)
    return success_object(ser_barn_wash(wash))
