"""Weld jigs, test lanes and the jig occupancy calendar (PRD 3.2, 3.6)."""
from flask import Blueprint

import errors
import lookups
import validators as v
from db import (add_minutes, db, fmt_dt, new_id, public, public_list, stamp_new,
                touch)
from middleware import endpoint
from response import created, listing, ok
from services import calc, rollups

bp = Blueprint("assets", __name__)

SURFACES = ("ASPHALT", "GRAVEL", "WASHBOARD")
RESERVATION_STATUSES = ("RESERVED", "CONSUMED", "RELEASED")
ROAD_TEST_STATUSES = ("SCHEDULED", "PASSED", "FAILED")


@bp.route("/weld-jigs", methods=["POST"])
@endpoint(["PlantEngineer"])
def create_jig():
    data = v.body()
    jig_code = v.req_code(data, "jig_code", 4, 16)
    frame_design_code = v.req_str(data, "frame_design_code", 2, 2, v.FRAME_RE)
    buffer_min = v.opt_int(data, "changeover_buffer_min", 45, 0)

    lookups.unique_or_409(db.jigs, "jig_code", jig_code)
    row = {
        "id": new_id(),
        "jig_code": jig_code,
        "frame_design_code": frame_design_code,
        "changeover_buffer_min": buffer_min,
        "reserved_minutes_total": 0,
    }
    stamp_new(row)
    db.jigs[row["id"]] = row
    return created(public(row))


@bp.route("/weld-jigs/<jig_id>", methods=["GET"])
@endpoint(["PlantEngineer", "WeldSupervisor"])
def get_jig(jig_id):
    return ok(public(lookups.jig_or_404(jig_id)))


@bp.route("/test-lanes", methods=["POST"])
@endpoint(["PlantEngineer"])
def create_lane():
    data = v.body()
    lane_code = v.req_code(data, "lane_code", 4, 16)
    surface_type = v.req_enum(data, "surface_type", SURFACES)
    max_concurrent = v.opt_int(data, "max_concurrent_tests", 2, 1)

    lookups.unique_or_409(db.lanes, "lane_code", lane_code)
    row = {
        "id": new_id(),
        "lane_code": lane_code,
        "max_concurrent_tests": max_concurrent,
        "surface_type": surface_type,
    }
    stamp_new(row)
    db.lanes[row["id"]] = row
    return created(public(row))


@bp.route("/test-lanes/<lane_id>", methods=["GET"])
@endpoint(["PlantEngineer", "QualityInspector"])
def get_lane(lane_id):
    return ok(public(lookups.lane_or_404(lane_id)))


@bp.route("/weld-jigs/<jig_id>/jig-reservations", methods=["POST"])
@endpoint(["WeldSupervisor"])
def create_reservation(jig_id):
    jig = lookups.jig_or_404(jig_id)
    data = v.body()
    unit = lookups.unit_or_404(v.req_id(data, "unit_id"))

    _raw_start, start_dt = v.req_dt(data, "window_start_at")
    _raw_end, end_dt = v.req_dt(data, "window_end_at")
    if not end_dt > start_dt:
        raise errors.invalid("window_end_at must be strictly later than window_start_at")
    expected = v.req_version(data, "expected_weld_jig_version")

    if expected != jig["version"]:
        raise errors.ApiError("ERR_STALE_JIG_VERSION", 412,
                              "expected_weld_jig_version %s does not match the jig's current version %s"
                              % (expected, jig["version"]))
    if unit["build_status"] != "PLANNED":
        raise errors.ApiError("ERR_UNIT_BUILD_STATE_INVALID", 409,
                              "A unit in build_status %s may not reserve a weld jig"
                              % unit["build_status"])
    model = db.models.get(unit["model_id"])
    if model["certification_status"] != "CERTIFIED":
        raise errors.ApiError("ERR_MODEL_NOT_CERTIFIED", 409,
                              "The unit's model is in certification_status %s"
                              % model["certification_status"])
    if jig["frame_design_code"] != model["frame_design_code"]:
        raise errors.ApiError("ERR_JIG_DESIGN_MISMATCH", 422,
                              "Jig %s is tooled for frame design %s, not %s"
                              % (jig["jig_code"], jig["frame_design_code"],
                                 model["frame_design_code"]))

    buffer_min = jig["changeover_buffer_min"]
    new_occ_end = add_minutes(end_dt, buffer_min)
    for res in rollups.reservations_of_jig(jig_id):
        if res["status"] not in ("RESERVED", "CONSUMED"):
            continue
        existing_occ_end = add_minutes(res["_window_end_dt"], buffer_min)
        if start_dt < existing_occ_end and res["_window_start_dt"] < new_occ_end:
            raise errors.ApiError("ERR_JIG_WINDOW_CONFLICT", 409,
                                  "The requested welding window collides with an existing reservation")

    row = {
        "id": new_id(),
        "jig_id": jig_id,
        "unit_id": unit["id"],
        "window_start_at": _raw_start,
        "window_end_at": _raw_end,
        "duration_minutes": calc.whole_minutes(start_dt, end_dt),
        "occupancy_end_at": fmt_dt(new_occ_end),
        "status": "RESERVED",
        "_window_start_dt": start_dt,
        "_window_end_dt": end_dt,
    }
    stamp_new(row)
    db.reservations[row["id"]] = row

    rollups.recompute_jig_minutes(jig)

    unit["build_status"] = "JIG_RESERVED"
    unit["model_version_pinned"] = model["version"]
    unit["gvwr_lbs"] = model["certified_gvwr_lbs"]
    unit["curb_weight_lbs"] = model["base_curb_weight_lbs"]
    unit["payload_capacity_lbs"] = unit["gvwr_lbs"] - unit["curb_weight_lbs"]
    touch(unit)
    rollups.recompute_unit_weights(unit)
    return created(public(row))


def _window_sorted(rows):
    # Jig reservations carry `_window_start_dt`; road tests carry `_window_start`.
    rows.sort(key=lambda r: (r.get("_window_start_dt") or r["_window_start"], r["_seq"]))
    return rows


def _window(rows, limit, offset):
    total = len(rows)
    return public_list(rows[offset:offset + limit]), total


@bp.route("/weld-jigs/<jig_id>/jig-reservations", methods=["GET"])
@endpoint(["WeldSupervisor", "PlantEngineer"])
def list_jig_reservations(jig_id):
    lookups.jig_or_404(jig_id)
    status = v.query_enum("status", RESERVATION_STATUSES)
    limit, offset = v.pagination()
    rows = rollups.reservations_of_jig(jig_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    _window_sorted(rows)
    items, total = _window(rows, limit, offset)
    return listing(items, limit, offset, total)


@bp.route("/test-lanes/<lane_id>/road-tests", methods=["GET"])
@endpoint(["QualityInspector", "PlantEngineer"])
def list_lane_road_tests(lane_id):
    lookups.lane_or_404(lane_id)
    status = v.query_enum("status", ROAD_TEST_STATUSES)
    limit, offset = v.pagination()
    rows = rollups.road_tests_of_lane(lane_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    _window_sorted(rows)
    items, total = _window(rows, limit, offset)
    return listing(items, limit, offset, total)
