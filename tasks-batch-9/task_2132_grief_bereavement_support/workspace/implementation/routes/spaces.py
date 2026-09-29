"""Meeting spaces (§3.3)."""

from flask import Blueprint

from core.auth import authenticate
from core.envelope import created, ok
from core.errors import ApiError
from core.shape import SPACE_STATUSES, body, opt_array, opt_int, req_enum, req_int, req_str
from core.store import public, store
from services.state import must_exist

bp = Blueprint("spaces", __name__)


@bp.route("/bereavement/meeting-spaces", methods=["POST"])
def create_space():
    authenticate(["ProgramDirector"])
    data = body()
    name = req_str(data, "name")
    capacity = req_int(data, "capacity", 1)
    buffer_minutes = opt_int(data, "turnover_buffer_minutes", 30, 0)
    features = opt_array(data, "accessibility_features", [])
    rec = store.create("MeetingSpace", {
        "name": name,
        "capacity": capacity,
        "turnover_buffer_minutes": buffer_minutes,
        "accessibility_features": features,
        "status": "AVAILABLE",
    })
    return created(public(rec))


@bp.route("/bereavement/meeting-spaces/<sid>", methods=["GET"])
def read_space(sid):
    authenticate(["ProgramDirector", "IntakeCoordinator"])
    return ok(public(must_exist("MeetingSpace", sid)))


@bp.route("/bereavement/meeting-spaces/<sid>/status", methods=["POST"])
def set_space_status(sid):
    authenticate(["ProgramDirector"])
    space = must_exist("MeetingSpace", sid)
    data = body()
    target = req_enum(data, "status", SPACE_STATUSES)
    if target == space["status"]:
        raise ApiError("ERR_INVALID_STATE", "The space is already %s." % target)
    space["status"] = target
    store.touch(space)
    return ok(public(space))
