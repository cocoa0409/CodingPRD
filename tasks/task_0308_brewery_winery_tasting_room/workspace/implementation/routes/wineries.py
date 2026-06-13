"""Winery routes (PRD §3.1). Premises = TTB accounting root."""
from flask import Blueprint, request

from db import db, common_fields, touch
from errors import err, ERR_INVALID_STATE, ERR_STALE_WINERY_VERSION
from middleware import authenticate, authorize
from response import success
from serialize import public, public_list
from validate import get_json_body, require_str, require_int, require_enum, get_or_404
from pagination import paginate, sorted_by_creation

bp = Blueprint("wineries", __name__)


def _new_winery(name, ttb_permit_number, home_state_code):
    w = common_fields()
    w.update({
        "name": name,
        "ttb_permit_number": ttb_permit_number,
        "home_state_code": home_state_code,
        "bulk_volume_gallons": 0.0,
        "bottled_taxpaid_volume_gallons": 0.0,
        "excise_tax_owed_cents": 0,
        "loyalty_point_liability": 0,
        "status": "ACTIVE",
    })
    return w


@bp.route("/wineries", methods=["POST"])
def create_winery():
    _, role = authenticate()
    authorize(role, ["ComplianceOfficer"])
    body = get_json_body()
    name = require_str(body, "name")
    ttb = require_str(body, "ttb_permit_number")
    home_state = require_str(body, "home_state_code")
    with db.lock:
        w = _new_winery(name, ttb, home_state)
        db.wineries[w["id"]] = w
        return success(public(w), status=201)


@bp.route("/wineries/<winery_id>", methods=["GET"])
def get_winery(winery_id):
    _, role = authenticate()
    authorize(role, ["ComplianceOfficer", "CellarManager", "ClubManager", "TastingRoomStaff"])
    with db.lock:
        w = get_or_404(db.wineries, winery_id)
        return success(public(w))


@bp.route("/wineries/<winery_id>/transitions", methods=["POST"])
def transition_winery(winery_id):
    _, role = authenticate()
    authorize(role, ["ComplianceOfficer"])
    with db.lock:
        w = get_or_404(db.wineries, winery_id)
        body = get_json_body()
        action = require_enum(body, "action", {"SUSPEND", "REINSTATE"})
        expected_version = require_int(body, "expected_winery_version")

        if action == "SUSPEND":
            if w["status"] != "ACTIVE":
                raise err(ERR_INVALID_STATE, "Winery is not ACTIVE")
            if expected_version != w["version"]:
                raise err(ERR_STALE_WINERY_VERSION, "expected_winery_version is stale")
            w["status"] = "SUSPENDED"
            touch(w)
        else:  # REINSTATE
            if w["status"] != "SUSPENDED":
                raise err(ERR_INVALID_STATE, "Winery is not SUSPENDED")
            if expected_version != w["version"]:
                raise err(ERR_STALE_WINERY_VERSION, "expected_winery_version is stale")
            w["status"] = "ACTIVE"
            touch(w)
        return success(public(w))
