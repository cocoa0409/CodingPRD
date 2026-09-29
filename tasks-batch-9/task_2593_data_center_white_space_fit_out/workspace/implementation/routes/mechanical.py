"""The mechanical chain: containment zones, leakage tests and cooling units."""

from flask import Blueprint

import db
import validation as v
from constants import (
    CONTAINMENT_KINDS,
    COOLING_REDUNDANCY_ROLES,
    LEAKAGE_PRESSURE_FLOOR,
    AIRFLOW_DESIGN_FLOOR,
    ROLE_MECHANICAL_CONTRACTOR,
    STAFF_ROLES,
    ZONE_TYPES,
)
from errors import ApiError
from middleware import endpoint
from output import created, filtered, listing, ok, require
from services import calc, cascade
from util import D, q

bp = Blueprint("mechanical", __name__)

READ_ROLES = list(STAFF_ROLES)
MC = [ROLE_MECHANICAL_CONTRACTOR]


# -------------------------------------------------------- containment zones ----

@bp.post("/containment-zones")
@endpoint(MC)
def create_zone():
    payload = v.body()
    hall_id = v.fk_field(payload, "hall_id")
    label = v.string_field(payload, "label", min_len=1, max_len=16)
    zone_type = v.enum_field(payload, "zone_type", ZONE_TYPES)
    kind = v.enum_field(payload, "containment_kind", CONTAINMENT_KINDS)
    target = v.number_field(
        payload, "target_leakage_pct", gt=0, le=D("25.00"), places=2
    )
    pressure = v.number_field(payload, "design_static_pressure_pa", gt=0, places=1)

    hall = require("halls", hall_id)
    for row in db.where("zones", hall_id=hall["id"]):
        if row["label"] == label:
            raise ApiError("ERR_DUPLICATE_CODE")

    zone = db.new_row(
        "zones",
        {
            "hall_id": hall["id"],
            "label": label,
            "zone_type": zone_type,
            "containment_kind": kind,
            "target_leakage_pct": target,
            "design_static_pressure_pa": pressure,
            "measured_leakage_pct": None,
            "measured_static_pressure_pa": None,
            "leakage_status": "UNTESTED",
            "test_count": 0,
        },
    )
    return created(zone)


@bp.get("/containment-zones")
@endpoint(READ_ROLES)
def list_zones():
    return listing(
        filtered(
            "zones",
            {
                "hall_id": "hall_id",
                "leakage_status": "leakage_status",
                "zone_type": "zone_type",
            },
        )
    )


@bp.get("/containment-zones/<zone_id>")
@endpoint(READ_ROLES)
def read_zone(zone_id):
    return ok(require("zones", zone_id))


@bp.post("/containment-zones/<zone_id>/leakage-test")
@endpoint(MC)
def leakage_test(zone_id):
    payload = v.body()
    leakage = v.number_field(payload, "measured_leakage_pct", ge=0)
    pressure = v.number_field(payload, "measured_static_pressure_pa", ge=0)
    zone = require("zones", zone_id)

    if zone["leakage_status"] not in ("UNTESTED", "REMEDIATION"):
        raise ApiError("ERR_INVALID_STATE")

    hall = db.get("halls", zone["hall_id"])
    cascade.require_covering_mop(hall, [zone["id"]])

    leakage = q(leakage, 2)
    pressure = q(pressure, 1)
    floor = q(D(zone["design_static_pressure_pa"]) * LEAKAGE_PRESSURE_FLOOR, 2)
    passed = leakage <= D(zone["target_leakage_pct"]) and pressure >= floor

    zone["measured_leakage_pct"] = leakage
    zone["measured_static_pressure_pa"] = pressure
    zone["test_count"] = zone["test_count"] + 1
    zone["leakage_status"] = "PASS" if passed else "FAIL"
    db.touch(zone)

    calc.thermal_chain(hall)
    return ok(zone)


@bp.post("/containment-zones/<zone_id>/remediate")
@endpoint(MC)
def remediate_zone(zone_id):
    payload = v.body()
    v.optional_string_or_null(payload, "remediation_note")
    zone = require("zones", zone_id)

    if zone["leakage_status"] != "FAIL":
        raise ApiError("ERR_INVALID_STATE")

    hall = db.get("halls", zone["hall_id"])
    cascade.require_covering_mop(hall, [zone["id"]])

    zone["leakage_status"] = "REMEDIATION"
    zone["measured_leakage_pct"] = None
    zone["measured_static_pressure_pa"] = None
    db.touch(zone)

    calc.thermal_chain(hall)
    return ok(zone)


# ------------------------------------------------------------ cooling units ----

@bp.post("/cooling-units")
@endpoint(MC)
def create_cooling_unit():
    payload = v.body()
    hall_id = v.fk_field(payload, "hall_id")
    name = v.string_field(payload, "name")
    rated = v.number_field(payload, "rated_sensible_kw", gt=0, places=2)
    airflow = v.int_field(payload, "design_airflow_cfm", ge=1)
    delta_t = v.number_field(payload, "supply_delta_t_f", gt=0, places=1)
    role = v.enum_field(payload, "redundancy_role", COOLING_REDUNDANCY_ROLES)

    hall = require("halls", hall_id)
    unit = db.new_row(
        "cooling_units",
        {
            "hall_id": hall["id"],
            "name": name,
            "rated_sensible_kw": rated,
            "design_airflow_cfm": airflow,
            "supply_delta_t_f": delta_t,
            "redundancy_role": role,
            "measured_airflow_cfm": None,
            "airflow_capacity_kw": q(0, 2),
            "status": "INSTALLED",
        },
    )
    return created(unit)


@bp.get("/cooling-units")
@endpoint(READ_ROLES)
def list_cooling_units():
    return listing(
        filtered(
            "cooling_units",
            {
                "hall_id": "hall_id",
                "status": "status",
                "redundancy_role": "redundancy_role",
            },
        )
    )


@bp.get("/cooling-units/<unit_id>")
@endpoint(READ_ROLES)
def read_cooling_unit(unit_id):
    return ok(require("cooling_units", unit_id))


@bp.post("/cooling-units/<unit_id>/commission")
@endpoint(MC)
def commission_cooling_unit(unit_id):
    payload = v.body()
    measured = v.int_field(payload, "measured_airflow_cfm", ge=0)
    unit = require("cooling_units", unit_id)

    if unit["status"] != "INSTALLED":
        raise ApiError("ERR_INVALID_STATE")

    hall = db.get("halls", unit["hall_id"])
    if hall["status"] not in ("FIT_OUT", "COMMISSIONING", "LIVE"):
        raise ApiError("ERR_HALL_PHASE_INVALID")

    cascade.require_covering_mop(hall, [unit["id"]])

    if D(measured) < D(unit["design_airflow_cfm"]) * AIRFLOW_DESIGN_FLOOR:
        raise ApiError("ERR_AIRFLOW_BELOW_DESIGN")

    unit["measured_airflow_cfm"] = measured
    unit["status"] = "COMMISSIONED"
    db.touch(unit)
    calc.apply_cooling(hall)
    return ok(unit)


@bp.post("/cooling-units/<unit_id>/place-in-service")
@endpoint(MC)
def place_in_service(unit_id):
    unit = require("cooling_units", unit_id)
    if unit["status"] != "COMMISSIONED":
        raise ApiError("ERR_INVALID_STATE")
    unit["status"] = "IN_SERVICE"
    db.touch(unit)
    calc.thermal_chain(db.get("halls", unit["hall_id"]))
    return ok(unit)
