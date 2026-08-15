"""Track endpoints: create, get, and the two parallel state dimensions
(status ACTIVE/OUT_OF_SERVICE; derail_protection ENGAGED/DISENGAGED)."""

from flask import Blueprint

from db import STORE, new_entity, touch, public
from errors import raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_TRACK_OCCUPIED
from middleware import auth_context, require_role, ALL_ROLES
from response import ok
from validate import body, req_str, req_pos_int

bp = Blueprint("tracks", __name__)


@bp.route("/transload/tracks", methods=["POST"])
def create_track():
    _, role = auth_context()
    require_role(role, ["FacilityAdmin"])
    data = body()
    name = req_str(data, "name")
    spot_capacity = req_pos_int(data, "spot_capacity")
    track = new_entity(STORE.tracks, {
        "name": name,
        "spot_capacity": spot_capacity,
        "status": "ACTIVE",
        "derail_protection": "DISENGAGED",
        "occupied_spots": 0,
        "reserved_spots": 0,
    })
    return ok(public(track), status=201)


@bp.route("/transload/tracks/<tid>", methods=["GET"])
def get_track(tid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    track = STORE.tracks.get(tid)
    if track is None:
        raise_err(ERR_NOT_FOUND, "track id does not exist")
    return ok(public(track))


@bp.route("/transload/tracks/<tid>/take-out-of-service", methods=["POST"])
def take_out_of_service(tid):
    _, role = auth_context()
    require_role(role, ["YardMaster"])
    track = STORE.tracks.get(tid)
    if track is None:
        raise_err(ERR_NOT_FOUND, "track id does not exist")
    if track["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "track is not ACTIVE")
    if track["occupied_spots"] != 0:
        raise_err(ERR_TRACK_OCCUPIED, "track has cars spotted")
    track["status"] = "OUT_OF_SERVICE"
    touch(track)
    return ok(public(track))


@bp.route("/transload/tracks/<tid>/restore-service", methods=["POST"])
def restore_service(tid):
    _, role = auth_context()
    require_role(role, ["YardMaster"])
    track = STORE.tracks.get(tid)
    if track is None:
        raise_err(ERR_NOT_FOUND, "track id does not exist")
    if track["status"] != "OUT_OF_SERVICE":
        raise_err(ERR_INVALID_STATE, "track is not OUT_OF_SERVICE")
    track["status"] = "ACTIVE"
    touch(track)
    return ok(public(track))


@bp.route("/transload/tracks/<tid>/engage-derail", methods=["POST"])
def engage_derail(tid):
    _, role = auth_context()
    require_role(role, ["SafetyOfficer"])
    track = STORE.tracks.get(tid)
    if track is None:
        raise_err(ERR_NOT_FOUND, "track id does not exist")
    if track["derail_protection"] != "DISENGAGED":
        raise_err(ERR_INVALID_STATE, "derail protection is not DISENGAGED")
    track["derail_protection"] = "ENGAGED"
    touch(track)
    return ok(public(track))


@bp.route("/transload/tracks/<tid>/disengage-derail", methods=["POST"])
def disengage_derail(tid):
    _, role = auth_context()
    require_role(role, ["SafetyOfficer"])
    track = STORE.tracks.get(tid)
    if track is None:
        raise_err(ERR_NOT_FOUND, "track id does not exist")
    if track["derail_protection"] != "ENGAGED":
        raise_err(ERR_INVALID_STATE, "derail protection is not ENGAGED")
    track["derail_protection"] = "DISENGAGED"
    touch(track)
    return ok(public(track))
