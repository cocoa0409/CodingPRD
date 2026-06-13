"""ResultRecord endpoints + transitions."""
from flask import Blueprint, request

from db import db, new_id
from errors import (err, ERR_RELATION_MISMATCH, ERR_INVALID_STATE,
                    ERR_INVALID_TIMING, ERR_NOT_FOUND)
from middleware import auth, require_role, get_json
from response import object_response
from services.store import stamp_new, serialize_generic, touch, paginate_and_respond
from services.calculations import timing_result
from services.validate import require_str, require_int, lookup

bp = Blueprint("results", __name__)

READ_ROLES = {"RaceDirector", "Participant", "PacketStaff", "TimingOfficial"}


@bp.route("/results", methods=["POST"])
def create_result():
    user_id, role = auth()
    require_role(role, {"TimingOfficial"})
    body = get_json()
    registration_id = require_str(body, "registration_id")
    reg = db.registrations.get(registration_id)
    if reg is None:
        raise err(ERR_NOT_FOUND, "Registration not found")
    distance_id = require_str(body, "distance_id")
    distance = db.distances.get(distance_id)
    if distance is None:
        raise err(ERR_NOT_FOUND, "Distance not found")

    gun_start = require_int(body, "gun_start_clock_seconds")
    mat_cross = require_int(body, "mat_cross_clock_seconds")
    finish = require_int(body, "finish_clock_seconds")

    # relationship: result registration must belong to distance_id
    if reg["distance_id"] != distance_id:
        raise err(ERR_RELATION_MISMATCH, "Registration does not belong to the supplied distance")

    # timing well-ordering
    if not (mat_cross >= gun_start and finish > mat_cross):
        raise err(ERR_INVALID_TIMING, "Timing clocks are not well-ordered")

    gun_time, chip_time, pace = timing_result(gun_start, mat_cross, finish, distance["distance_km"])

    rid = new_id()
    rec = {
        "id": rid,
        "registration_id": registration_id,
        "distance_id": distance_id,
        "gun_start_clock_seconds": gun_start,
        "mat_cross_clock_seconds": mat_cross,
        "finish_clock_seconds": finish,
        "gun_time_seconds": gun_time,
        "chip_time_seconds": chip_time,
        "pace_seconds_per_km": pace,
        "status": "PROVISIONAL",
    }
    stamp_new(rec)
    db.result_records[rid] = rec
    return object_response(serialize_generic(rec), 201)


@bp.route("/results/<result_id>", methods=["GET"])
def get_result(result_id):
    user_id, role = auth()
    require_role(role, READ_ROLES)
    rec = lookup(db.result_records, result_id, "ResultRecord")
    return object_response(serialize_generic(rec), 200)


@bp.route("/results", methods=["GET"])
def list_results():
    user_id, role = auth()
    require_role(role, READ_ROLES)
    items = list(db.result_records.values())
    for f in ("registration_id", "distance_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [rec for rec in items if rec.get(f) == v]
    return paginate_and_respond("result", items, request.args)


@bp.route("/distances/<distance_id>/results", methods=["GET"])
def list_distance_results(distance_id):
    user_id, role = auth()
    require_role(role, READ_ROLES)
    lookup(db.distances, distance_id, "Distance")
    items = [rec for rec in db.result_records.values() if rec["distance_id"] == distance_id]
    status = request.args.get("status")
    if status is not None:
        items = [rec for rec in items if rec["status"] == status]
    return paginate_and_respond("result", items, request.args)


@bp.route("/results/<result_id>/finalize", methods=["POST"])
def finalize_result(result_id):
    user_id, role = auth()
    require_role(role, {"TimingOfficial"})
    rec = lookup(db.result_records, result_id, "ResultRecord")
    if rec["status"] != "PROVISIONAL":
        raise err(ERR_INVALID_STATE, "Result must be PROVISIONAL to finalize")

    reg = db.registrations.get(rec["registration_id"])
    event = db.events.get(reg["event_id"]) if reg else None
    if event is None or event["status"] != "RESULTS_POSTED":
        raise err(ERR_INVALID_STATE, "Owning event must be RESULTS_POSTED")
    if reg is None or reg["status"] != "BIB_ASSIGNED":
        raise err(ERR_INVALID_STATE, "Linked registration must be BIB_ASSIGNED")

    rec["status"] = "OFFICIAL"
    touch(rec)
    return object_response(serialize_generic(rec), 200)


@bp.route("/results/<result_id>/disqualify", methods=["POST"])
def disqualify_result(result_id):
    user_id, role = auth()
    require_role(role, {"TimingOfficial"})
    rec = lookup(db.result_records, result_id, "ResultRecord")
    if rec["status"] not in ("PROVISIONAL", "OFFICIAL"):
        raise err(ERR_INVALID_STATE, "Result must be PROVISIONAL or OFFICIAL to disqualify")
    rec["status"] = "DQ"
    touch(rec)
    return object_response(serialize_generic(rec), 200)
