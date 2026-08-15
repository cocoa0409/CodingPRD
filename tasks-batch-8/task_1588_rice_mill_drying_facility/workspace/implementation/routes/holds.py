"""FoodSafetyHold endpoints (PRD §3.7)."""
from flask import Blueprint

from db import db
from errors import raise_error, ERR_BIN_NOT_FOUND, ERR_LOT_NOT_FOUND, ERR_HOLD_ALREADY_RELEASED
from middleware import authorized
from response import success_object
from routes.helpers import list_endpoint, get_endpoint, public, require_resource
from services import core
from util import new_id, next_seq
from validate import get_body, req_str, req_enum

bp = Blueprint("holds", __name__)


@bp.route("/mill/holds", methods=["POST"])
def create_hold():
    authorized(["SafetyOfficer"])
    body = get_body()
    season_id = req_str(body, "season_id")
    target_type = req_enum(body, "target_type", ("BIN", "LOT"))
    target_id = req_str(body, "target_id")
    reason_code = req_str(body, "reason_code")
    require_resource("seasons", season_id)
    if target_type == "BIN":
        target = db["bins"].get(target_id)
        if target is None or target["season_id"] != season_id:
            raise_error(ERR_BIN_NOT_FOUND, "target bin not found in this season")
    else:
        target = db["lots"].get(target_id)
        if target is None or target["season_id"] != season_id:
            raise_error(ERR_LOT_NOT_FOUND, "target lot not found in this season")
    rec = {
        "id": new_id(),
        "_seq": next_seq(),
        "season_id": season_id,
        "target_type": target_type,
        "target_id": target_id,
        "reason_code": reason_code,
        "resolution_note": None,
        "status": "ACTIVE",
    }
    core.touch_new(rec)
    db["holds"][rec["id"]] = rec
    return success_object(public(rec), 201)


@bp.route("/mill/holds", methods=["GET"])
def list_holds():
    return list_endpoint("holds", ["season_id", "target_type", "target_id", "status"])


@bp.route("/mill/holds/<rid>", methods=["GET"])
def get_hold(rid):
    return get_endpoint("holds", rid)


@bp.route("/mill/holds/<rid>/release", methods=["POST"])
def release_hold(rid):
    authorized(["SafetyOfficer"])
    body = get_body()
    note = req_str(body, "resolution_note")
    hold = require_resource("holds", rid)
    if hold["status"] != "ACTIVE":
        raise_error(ERR_HOLD_ALREADY_RELEASED,
                    f"release requires ACTIVE; hold is {hold['status']}")
    hold["resolution_note"] = note
    hold["status"] = "RELEASED"
    core.bump(hold)
    return success_object(public(hold))
