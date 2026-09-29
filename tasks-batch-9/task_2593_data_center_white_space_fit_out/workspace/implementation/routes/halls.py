"""Logical clock, halls and tenants."""

from flask import Blueprint

import db
import validation as v
from constants import (
    ALL_ROLES,
    HALL_COOLING_REDUNDANCY,
    HALL_PHASE_ORDER,
    HALL_STATUSES,
    ROLE_FACILITY_PLANNER,
    STAFF_ROLES,
    TENANT_MODES,
)
from errors import ApiError
from middleware import caller_tenant_id, endpoint, is_tenant_caller
from output import created, filtered, listing, ok, require
from services import calc
from util import D, q

bp = Blueprint("halls", __name__)

READ_ROLES = list(STAFF_ROLES)
ANY_ROLE = list(ALL_ROLES)


# ---------------------------------------------------------------- clock ----

@bp.post("/_clock/set_current_utc")
@endpoint(STAFF_ROLES)
def set_clock():
    payload = v.body()
    when = v.datetime_field(payload, "current_utc")
    db.set_clock(when)
    db.commit()
    from response import object_response
    return object_response({"current_utc": payload["current_utc"]})


# ---------------------------------------------------------------- halls ----

def hall_fields(payload):
    return {
        "name": v.string_field(payload, "name"),
        "code": v.string_field(payload, "code", min_len=1, max_len=16),
        "tenant_mode": v.enum_field(payload, "tenant_mode", TENANT_MODES),
        "design_kw_capacity": v.number_field(
            payload, "design_kw_capacity", gt=0, places=2
        ),
        "gross_area_sqm": v.number_field(payload, "gross_area_sqm", gt=0),
        "cooling_redundancy": v.enum_field(
            payload, "cooling_redundancy", HALL_COOLING_REDUNDANCY
        ),
        "planned_rack_count": v.int_field(payload, "planned_rack_count", ge=1),
    }


@bp.post("/halls")
@endpoint([ROLE_FACILITY_PLANNER])
def create_hall():
    fields = hall_fields(v.body())
    for row in db.all_rows("halls"):
        if row["code"] == fields["code"]:
            raise ApiError("ERR_DUPLICATE_CODE")
    hall = db.new_row(
        "halls",
        {
            "name": fields["name"],
            "code": fields["code"],
            "tenant_mode": fields["tenant_mode"],
            "design_kw_capacity": fields["design_kw_capacity"],
            "gross_area_sqm": fields["gross_area_sqm"],
            "cooling_redundancy": fields["cooling_redundancy"],
            "planned_rack_count": fields["planned_rack_count"],
            "status": "PLANNING",
            "committed_kw": q(0, 2),
            "commissioning_reserve_kw": q(0, 2),
            "spare_kw": q(0, 2),
            "chargeable_kw": q(0, 2),
            "thermal_load_kw": q(0, 2),
            "cooling_capacity_nameplate_kw": q(0, 2),
            "cooling_capacity_airflow_kw": q(0, 2),
            "cooling_capacity_kw": q(0, 2),
            "cooling_margin_kw": q(0, 2),
            "thermal_posture": "NOMINAL",
            "release_posture": "OPEN",
            "rack_total_count": 0,
            "custody_ops_count": 0,
            "custody_fitout_count": 0,
            "at_risk_rack_count": 0,
            "open_mop_count": 0,
        },
    )
    calc.apply_ledger(hall)
    return created(hall)


@bp.get("/halls")
@endpoint(ANY_ROLE)
def list_halls():
    rows = filtered("halls", {"status": "status", "tenant_mode": "tenant_mode"})
    return listing(rows)


@bp.get("/halls/<hall_id>")
@endpoint(ANY_ROLE)
def read_hall(hall_id):
    return ok(require("halls", hall_id))


@bp.post("/halls/<hall_id>/advance-phase")
@endpoint([ROLE_FACILITY_PLANNER])
def advance_phase(hall_id):
    payload = v.body()
    target = v.enum_field(payload, "target_status", HALL_STATUSES)
    hall = require("halls", hall_id)

    if target == "LIVE" or HALL_PHASE_ORDER[target] != HALL_PHASE_ORDER[hall["status"]] + 1:
        raise ApiError("ERR_HALL_PHASE_INVALID")

    busways = db.where("busways", hall_id=hall["id"])
    if target == "FIT_OUT":
        pdus = db.where("pdus", hall_id=hall["id"])
        if not any(p["feed_side"] == "A" for p in pdus):
            raise ApiError("ERR_PHASE_PREREQ_NOT_MET")
        if not any(p["feed_side"] == "B" for p in pdus):
            raise ApiError("ERR_PHASE_PREREQ_NOT_MET")
        if not busways:
            raise ApiError("ERR_PHASE_PREREQ_NOT_MET")
        if not db.where("zones", hall_id=hall["id"]):
            raise ApiError("ERR_PHASE_PREREQ_NOT_MET")
    else:
        zones = db.where("zones", hall_id=hall["id"])
        if any(z["leakage_status"] != "PASS" for z in zones):
            raise ApiError("ERR_PHASE_PREREQ_NOT_MET")
        if not db.where("cooling_units", hall_id=hall["id"], status="IN_SERVICE"):
            raise ApiError("ERR_PHASE_PREREQ_NOT_MET")
        if not db.where("racks", hall_id=hall["id"], status="POWERED"):
            raise ApiError("ERR_PHASE_PREREQ_NOT_MET")
        for busway in busways:
            ceiling = calc.busway_usable_kw(busway, "COMMISSIONED")
            if D(busway["committed_kw"]) > ceiling:
                raise ApiError("ERR_PHASE_PREREQ_NOT_MET")

    hall["status"] = target
    db.touch(hall)
    if target == "COMMISSIONING":
        for busway in busways:
            calc.apply_busway_ceiling(busway, "COMMISSIONED")
    calc.apply_ledger(hall)
    return ok(hall)


def tenant_owns_in_hall(hall, tenant_id):
    if any(c["tenant_id"] == tenant_id for c in db.where("cages", hall_id=hall["id"])):
        return True
    if any(r.get("tenant_id") == tenant_id for r in db.where("racks", hall_id=hall["id"])):
        return True
    return False


@bp.get("/halls/<hall_id>/capacity-summary")
@endpoint(ANY_ROLE)
def capacity_summary(hall_id):
    hall = require("halls", hall_id)
    if is_tenant_caller() and not tenant_owns_in_hall(hall, caller_tenant_id()):
        raise ApiError("ERR_TENANT_SCOPE_VIOLATION")
    summary = {
        "hall_id": hall["id"],
        "status": hall["status"],
        "design_kw_capacity": hall["design_kw_capacity"],
        "committed_kw": hall["committed_kw"],
        "commissioning_reserve_kw": hall["commissioning_reserve_kw"],
        "spare_kw": hall["spare_kw"],
        "chargeable_kw": hall["chargeable_kw"],
        "thermal_load_kw": hall["thermal_load_kw"],
        "cooling_capacity_nameplate_kw": hall["cooling_capacity_nameplate_kw"],
        "cooling_capacity_airflow_kw": hall["cooling_capacity_airflow_kw"],
        "cooling_capacity_kw": hall["cooling_capacity_kw"],
        "cooling_margin_kw": hall["cooling_margin_kw"],
        "thermal_posture": hall["thermal_posture"],
        "release_posture": hall["release_posture"],
        "rack_total_count": hall["rack_total_count"],
        "custody_ops_count": hall["custody_ops_count"],
        "custody_fitout_count": hall["custody_fitout_count"],
        "at_risk_rack_count": hall["at_risk_rack_count"],
        "open_mop_count": hall["open_mop_count"],
        "worst_leakage_pct": calc.worst_leakage_pct(hall),
    }
    return ok(summary)


# -------------------------------------------------------------- tenants ----

@bp.post("/tenants")
@endpoint([ROLE_FACILITY_PLANNER])
def create_tenant():
    payload = v.body()
    name = v.string_field(payload, "name")
    code = v.string_field(payload, "code", min_len=1, max_len=16)
    contracted = v.number_field(payload, "contracted_kw", gt=0, places=2)
    start = v.datetime_field(payload, "contract_start_date")
    for row in db.all_rows("tenants"):
        if row["code"] == code:
            raise ApiError("ERR_DUPLICATE_CODE")
    tenant = db.new_row(
        "tenants",
        {
            "name": name,
            "code": code,
            "contracted_kw": contracted,
            "contract_start_date": start,
            "allocated_kw": q(0, 2),
        },
    )
    return created(tenant)


@bp.get("/tenants")
@endpoint(READ_ROLES)
def list_tenants():
    return listing(filtered("tenants", {"code": "code"}))


@bp.get("/tenants/<tenant_id>")
@endpoint(ANY_ROLE)
def read_tenant(tenant_id):
    return ok(require("tenants", tenant_id))
