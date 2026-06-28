"""Camp configuration root. PRD §3.1."""
from flask import Blueprint

import db
import errors
import response
from errors import ApiError
from middleware import get_identity, require_role, get_json_body
from services import validate, serialize, recompute
from services.store import base_fields, require, touch

bp = Blueprint("camps", __name__)


@bp.route("/camps", methods=["POST"])
def create_camp():
    _uid, role = get_identity()
    require_role(role, {"CampDirector"})
    body = get_json_body()
    name = validate.require_str(body, "name")
    ratio = validate.optional_int(body, "counselor_camper_ratio", 6)
    if ratio <= 0:
        raise validate.bad_request("counselor_camper_ratio must be positive.")
    cit_half = validate.optional_bool(body, "cit_counts_as_half", True)
    deposit = validate.optional_int(body, "deposit_cents", 25000)
    if deposit < 0:
        raise validate.bad_request("deposit_cents must be non-negative.")
    grace = validate.optional_int(body, "deposit_grace_days", 7)
    if grace < 0:
        raise validate.bad_request("deposit_grace_days must be non-negative.")
    low = validate.optional_int(body, "canteen_low_balance_cents", 1000)
    if low < 0:
        raise validate.bad_request("canteen_low_balance_cents must be non-negative.")

    c = base_fields()
    c.update({
        "name": name,
        "counselor_camper_ratio": ratio,
        "cit_counts_as_half": cit_half,
        "deposit_cents": deposit,
        "deposit_grace_days": grace,
        "canteen_low_balance_cents": low,
    })
    db.camps[c["id"]] = c
    return response.success(serialize.camp(c), 201)


@bp.route("/camps/<cid>", methods=["GET"])
def get_camp(cid):
    _uid, role = get_identity()
    require_role(role, {"Guardian", "CampDirector", "InfirmaryNurse"})
    c = require(db.camps, cid)
    return response.success(serialize.camp(c), 200)


@bp.route("/camps/<cid>", methods=["PATCH"])
def update_camp(cid):
    _uid, role = get_identity()
    require_role(role, {"CampDirector"})
    c = require(db.camps, cid)
    body = get_json_body()

    # expected_camp_version is required (PRD §2.8). OCC check (priority 13)
    # precedes the request-shape value checks below.
    if "expected_camp_version" not in body or body.get("expected_camp_version") is None:
        raise validate.bad_request("expected_camp_version is required.")
    expected = body.get("expected_camp_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise validate.bad_request("expected_camp_version must be an integer.")
    if expected != c["version"]:
        raise ApiError(errors.ERR_STALE_VERSION, 412, "Camp version is stale.")

    cit_changed = False
    if "counselor_camper_ratio" in body and body.get("counselor_camper_ratio") is not None:
        ratio = validate.require_int(body, "counselor_camper_ratio")
        if ratio <= 0:
            raise validate.bad_request("counselor_camper_ratio must be positive.")
        c["counselor_camper_ratio"] = ratio
    if "cit_counts_as_half" in body and body.get("cit_counts_as_half") is not None:
        new_cit = validate.optional_bool(body, "cit_counts_as_half", c["cit_counts_as_half"])
        if new_cit != c["cit_counts_as_half"]:
            cit_changed = True
        c["cit_counts_as_half"] = new_cit
    if "deposit_cents" in body and body.get("deposit_cents") is not None:
        deposit = validate.require_int(body, "deposit_cents")
        if deposit < 0:
            raise validate.bad_request("deposit_cents must be non-negative.")
        c["deposit_cents"] = deposit
    if "deposit_grace_days" in body and body.get("deposit_grace_days") is not None:
        grace = validate.require_int(body, "deposit_grace_days")
        if grace < 0:
            raise validate.bad_request("deposit_grace_days must be non-negative.")
        c["deposit_grace_days"] = grace
    if "canteen_low_balance_cents" in body and body.get("canteen_low_balance_cents") is not None:
        low = validate.require_int(body, "canteen_low_balance_cents")
        if low < 0:
            raise validate.bad_request("canteen_low_balance_cents must be non-negative.")
        c["canteen_low_balance_cents"] = low

    touch(c)

    # When cit_counts_as_half changes, recompute every cabin's staff weight &
    # is_staffable across the whole camp, then session postures (PRD §3.1).
    if cit_changed:
        affected_sessions = set()
        for cabin in db.cabins.values():
            session = db.sessions.get(cabin["session_id"])
            if session is None or session["camp_id"] != c["id"]:
                continue
            recompute.recompute_cabin_staffing(cabin, bump_version=True)
            affected_sessions.add(session["id"])
        for sid in affected_sessions:
            recompute.recompute_session_posture(db.sessions[sid], bump_version=True)

    return response.success(serialize.camp(c), 200)
