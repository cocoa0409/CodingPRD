from flask import Blueprint

import db
from db import new_entity, touch
from errors import (
    ApiError,
    ERR_DEVICE_WINDOW_OVERLAP,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_TIMING_CONFIG_LOCKED,
)
from middleware import endpoint
from response import ok
from serializers import ser_timing_point
from validators import get_body, get_or_404, v_dt, v_int, v_num, v_str, v_enum

bp = Blueprint("timing_points", __name__)

_PRE_LOCK_STATES = ("DRAFT", "REGISTRATION_OPEN")


def _check_frozen(race):
    if race["status"] not in _PRE_LOCK_STATES:
        raise ApiError(
            ERR_TIMING_CONFIG_LOCKED,
            409,
            "Timing-point create/deploy/delete is only permitted before timing lock",
        )


@bp.post("/race-timing/timing-points")
@endpoint("TimingOperator")
def create_timing_point():
    body = get_body(
        (
            "race_id",
            "point_index",
            "kind",
            "distance_km",
            "device_id",
            "deploy_at",
            "expected_teardown_at",
        )
    )
    race = get_or_404(db.races, body.get("race_id"))
    point_index = v_int(body, "point_index")
    if point_index < 1:
        raise ApiError(ERR_INVALID_REQUEST, 400, "point_index must be at least 1")
    kind = v_enum(body, "kind", ("START", "SPLIT", "FINISH"))
    distance_km = v_num(body, "distance_km")
    if distance_km < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "distance_km must be non-negative")
    device_id = v_str(body, "device_id")
    deploy_at = v_dt(body, "deploy_at")
    teardown_at = v_dt(body, "expected_teardown_at")

    # 1) device scheduling: same device_id windows must not overlap (half-open,
    #    fleet-wide; teardown == deploy adjacency allowed)
    for p in db.timing_points.values():
        if p["device_id"] != device_id:
            continue
        if deploy_at < p["expected_teardown_at"] and p["deploy_at"] < teardown_at:
            raise ApiError(
                ERR_DEVICE_WINDOW_OVERLAP,
                409,
                "Deployment window overlaps another window of the same device",
            )
    # 2) window shape
    if teardown_at <= deploy_at:
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            "expected_teardown_at must be later than deploy_at",
        )
    # 3) configuration freeze
    _check_frozen(race)

    # structural: kind/distance coherence, uniqueness, strict increase
    race_distance = float(race["distance_km"])
    d = float(distance_km)
    if kind == "START" and d != 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "A START point sits at distance zero")
    if kind == "FINISH" and d != race_distance:
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            "A FINISH point sits at exactly the race distance",
        )
    if kind == "SPLIT" and not (0 < d < race_distance):
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            "A SPLIT point sits strictly between start and finish",
        )
    for p in db.timing_points.values():
        if p["race_id"] != race["id"]:
            continue
        if p["point_index"] == point_index:
            raise ApiError(
                ERR_INVALID_REQUEST,
                400,
                "point_index is already used in this race",
            )
        if (p["point_index"] - point_index) * (float(p["distance_km"]) - d) <= 0:
            raise ApiError(
                ERR_INVALID_REQUEST,
                400,
                "point_index must strictly increase with distance_km",
            )

    point = new_entity()
    point.update(
        {
            "race_id": race["id"],
            "point_index": point_index,
            "kind": kind,
            "distance_km": distance_km,
            "device_id": device_id,
            "deploy_at": deploy_at,
            "expected_teardown_at": teardown_at,
            "status": "PLANNED",
        }
    )
    db.timing_points[point["id"]] = point
    return ok(ser_timing_point(point), 201)


@bp.post("/race-timing/timing-points/<point_id>/deploy")
@endpoint("TimingOperator")
def deploy_timing_point(point_id):
    point = get_or_404(db.timing_points, point_id)
    if point["status"] != "PLANNED":
        raise ApiError(ERR_INVALID_STATE, 409, "Timing point is not PLANNED")
    race = db.races.get(point["race_id"])
    if race is not None:
        _check_frozen(race)
    point["status"] = "DEPLOYED"
    touch(point)
    return ok(ser_timing_point(point))


@bp.delete("/race-timing/timing-points/<point_id>")
@endpoint("TimingOperator")
def delete_timing_point(point_id):
    point = get_or_404(db.timing_points, point_id)
    race = db.races.get(point["race_id"])
    if race is not None:
        _check_frozen(race)
    del db.timing_points[point_id]
    return "", 204
