"""Logical clock and standing plant configuration (PRD 2.4, 3.1)."""
from flask import Blueprint

import lookup
from auth import ALL_ROLES, authorize
from calc import q2
from clock import clock, parse_instant
from db import create_row, store
from errors import api_error
from projections import recompute_pool
from response import ok
from serializers import serialize
from validators import F, bad, body

bp = Blueprint("config", __name__)

STATION_UNITS = ("UNIT_1", "UNIT_2")
FUNCTION_CODES = ("DECAY_HEAT_REMOVAL", "INVENTORY_CONTROL", "ELECTRICAL_POWER",
                  "CONTAINMENT", "REACTIVITY_CONTROL")


# ---------------------------------------------------------------------------
# POST /_clock/set_current_utc
# ---------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
@authorize("StationAdmin")
def set_clock():
    payload = body([F("to_iso8601", "iso")])
    clock.set(parse_instant(payload["to_iso8601"]))
    return ok({"current_utc": clock.now_iso()})


# ---------------------------------------------------------------------------
# spent fuel pools
# ---------------------------------------------------------------------------
@bp.route("/spent-fuel-pools", methods=["POST"])
@authorize("StationAdmin")
def create_spent_fuel_pool():
    payload = body([
        F("station_unit", "str", enum=STATION_UNITS),
        F("cells_total", "int", gt=0),
        F("cells_baseline_occupied", "int", ge=0),
        F("full_core_offload_reserve_cells", "int", ge=0),
    ])
    if payload["cells_baseline_occupied"] > payload["cells_total"]:
        raise bad("cells_baseline_occupied must not exceed cells_total.")
    pool = create_row(store.spent_fuel_pools, {
        "station_unit": payload["station_unit"],
        "cells_total": payload["cells_total"],
        "cells_baseline_occupied": payload["cells_baseline_occupied"],
        "full_core_offload_reserve_cells": payload["full_core_offload_reserve_cells"],
        "cells_occupied": 0,
        "cells_reserved": 0,
        "cells_available": 0,
        "protected_cells_available": 0,
    })
    recompute_pool(pool)
    return ok(serialize(pool), 201)


@bp.route("/spent-fuel-pools/<row_id>", methods=["GET"])
@authorize(*ALL_ROLES)
def get_spent_fuel_pool(row_id):
    return ok(serialize(lookup.spent_fuel_pool(row_id)))


# ---------------------------------------------------------------------------
# radiological areas
# ---------------------------------------------------------------------------
@bp.route("/rad-areas", methods=["POST"])
@authorize("StationAdmin")
def create_rad_area():
    payload = body([
        F("station_unit", "str", enum=STATION_UNITS),
        F("area_code", "str", min_len=1, max_len=32),
        F("dose_rate_mrem_per_hr", "num", gt=0),
        F("occupancy_limit_workers", "int", ge=1),
        F("survey_buffer_hours", "num", ge=0),
    ])
    for existing in store.rad_areas.values():
        if (existing["station_unit"] == payload["station_unit"]
                and existing["area_code"] == payload["area_code"]):
            raise bad("area_code must be unique within the station_unit.")
    area = create_row(store.rad_areas, {
        "station_unit": payload["station_unit"],
        "area_code": payload["area_code"],
        "dose_rate_mrem_per_hr": q2(payload["dose_rate_mrem_per_hr"]),
        "occupancy_limit_workers": payload["occupancy_limit_workers"],
        "survey_buffer_hours": q2(payload["survey_buffer_hours"]),
    })
    return ok(serialize(area), 201)


@bp.route("/rad-areas/<row_id>", methods=["GET"])
@authorize(*ALL_ROLES)
def get_rad_area(row_id):
    return ok(serialize(lookup.rad_area(row_id)))


# ---------------------------------------------------------------------------
# shutdown safety functions
# ---------------------------------------------------------------------------
@bp.route("/safety-functions", methods=["POST"])
@authorize("StationAdmin")
def create_safety_function():
    payload = body([
        F("station_unit", "str", enum=STATION_UNITS),
        F("function_code", "str", enum=FUNCTION_CODES),
        F("trains_total", "int", ge=1),
        F("min_trains_required", "int", ge=0),
    ])
    if payload["min_trains_required"] > payload["trains_total"]:
        raise bad("min_trains_required must not exceed trains_total.")
    for existing in store.safety_functions.values():
        if (existing["station_unit"] == payload["station_unit"]
                and existing["function_code"] == payload["function_code"]):
            raise bad("function_code must be unique within the station_unit.")
    function = create_row(store.safety_functions, {
        "station_unit": payload["station_unit"],
        "function_code": payload["function_code"],
        "trains_total": payload["trains_total"],
        "min_trains_required": payload["min_trains_required"],
        "max_concurrent_oos_trains": (payload["trains_total"]
                                      - payload["min_trains_required"]),
    })
    return ok(serialize(function), 201)


@bp.route("/safety-functions/<row_id>", methods=["GET"])
@authorize(*ALL_ROLES)
def get_safety_function(row_id):
    return ok(serialize(lookup.safety_function(row_id)))
