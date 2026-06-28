"""Cabins and bunk assignment. PRD §3.2, §3.6."""
from flask import Blueprint, request

import db
import errors
import response
from errors import ApiError
from middleware import get_identity, require_role, get_json_body, parse_pagination
from services import validate, serialize, recompute
from services.store import base_fields, require, touch, paginate

bp = Blueprint("cabins", __name__)

GENDER_BANDS = {"BOYS", "GIRLS", "ALL"}


def _gender_band_admits(band, camper_gender):
    if band == "ALL":
        return True
    if band == "BOYS":
        return camper_gender == "BOY"
    if band == "GIRLS":
        return camper_gender == "GIRL"
    return False


@bp.route("/sessions/<sid>/cabins", methods=["POST"])
def create_cabin(sid):
    _uid, role = get_identity()
    require_role(role, {"CampDirector"})
    session = require(db.sessions, sid)
    body = get_json_body()

    name = validate.require_str(body, "name")
    gender_band = validate.require_enum(body, "gender_band", GENDER_BANDS)
    min_age = validate.require_int(body, "min_age")
    max_age = validate.require_int(body, "max_age")
    bunk_capacity = validate.require_int(body, "bunk_capacity")
    if bunk_capacity < 0:
        raise validate.bad_request("bunk_capacity must be non-negative.")
    if max_age < min_age:
        raise validate.bad_request("max_age must be >= min_age.")

    c = base_fields()
    c.update({
        "session_id": session["id"],
        "name": name,
        "gender_band": gender_band,
        "min_age": min_age,
        "max_age": max_age,
        "bunk_capacity": bunk_capacity,
        "occupied_bunks": 0,
        "staff_weight_x10": 0,
        "is_staffable": True,  # empty cabin is always staffable (PRD §3.2)
    })
    db.cabins[c["id"]] = c
    return response.success(serialize.cabin(c), 201)


@bp.route("/sessions/<sid>/cabins", methods=["GET"])
def list_cabins(sid):
    _uid, role = get_identity()
    require_role(role, {"Guardian", "CampDirector", "InfirmaryNurse"})
    require(db.sessions, sid)
    limit, offset = parse_pagination()

    session_id_f = request.args.get("session_id")
    items = [c for c in db.cabins.values() if c["session_id"] == sid]
    if session_id_f is not None:
        items = [c for c in items if c["session_id"] == session_id_f]

    page, total = paginate(items, limit, offset)
    return response.success_list([serialize.cabin(c) for c in page], limit, offset, total)


@bp.route("/cabins/<cid>", methods=["GET"])
def get_cabin(cid):
    _uid, role = get_identity()
    require_role(role, {"Guardian", "CampDirector", "InfirmaryNurse"})
    c = require(db.cabins, cid)
    return response.success(serialize.cabin(c), 200)


@bp.route("/cabins/<cid>/assign-bunk", methods=["POST"])
def assign_bunk(cid):
    _uid, role = get_identity()
    require_role(role, {"CampDirector"})
    cabin = require(db.cabins, cid)
    body = get_json_body()

    # Body FK: application must exist (ERR_NOT_FOUND, priority 4).
    if "application_id" not in body or not isinstance(body.get("application_id"), str):
        raise validate.bad_request("application_id is required.")
    application = db.applications.get(body["application_id"])
    if application is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Application not found.")

    # Referential scope: cabin's session must match the application's session
    # (ERR_REFERENTIAL_MISMATCH, priority 5).
    if cabin["session_id"] != application["session_id"]:
        raise ApiError(errors.ERR_REFERENTIAL_MISMATCH, 409,
                       "Cabin does not belong to the application's session.")

    # State: application must be DEPOSIT_PAID or OFFERED-with-deposit. A bunk is
    # assignable from DEPOSIT_PAID (deposit has been paid). (PRD §3.6)
    if application["enroll_status"] != "DEPOSIT_PAID":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Application is not in a bunk-assignable state.")

    camper = db.campers[application["camper_id"]]

    # Eligibility: gender then age (priority 8).
    if not _gender_band_admits(cabin["gender_band"], camper["gender"]):
        raise ApiError(errors.ERR_CABIN_GENDER_MISMATCH, 422,
                       "Cabin gender band excludes the camper.")
    if not (cabin["min_age"] <= camper["age"] <= cabin["max_age"]):
        raise ApiError(errors.ERR_CABIN_AGE_MISMATCH, 422,
                       "Cabin age band excludes the camper.")

    # Capacity (priority 10): occupied_bunks must not exceed bunk_capacity.
    if cabin["occupied_bunks"] + 1 > cabin["bunk_capacity"]:
        raise ApiError(errors.ERR_CABIN_FULL, 409, "Cabin is full.")

    # OCC (priority 13): expected_cabin_version must match the cabin version.
    if "expected_cabin_version" not in body or body.get("expected_cabin_version") is None:
        raise validate.bad_request("expected_cabin_version is required.")
    expected = body.get("expected_cabin_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise validate.bad_request("expected_cabin_version must be an integer.")
    if expected != cabin["version"]:
        raise ApiError(errors.ERR_STALE_VERSION, 412, "Cabin version is stale.")

    # Side effects (PRD §3.6).
    application["cabin_id"] = cabin["id"]
    touch(application)
    cabin["occupied_bunks"] += 1
    recompute.recompute_cabin_is_staffable(cabin)
    touch(cabin)  # increments Cabin.version by 1
    session = db.sessions[cabin["session_id"]]
    recompute.recompute_session_posture(session, bump_version=True)

    return response.success(serialize.cabin(cabin), 200)
