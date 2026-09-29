from datetime import timedelta

from flask import Blueprint

import config
from db import db
from errors import fail
from middleware import endpoint, body
from numeric import D
from response import created, ok
from routes.common import (get_application, get_dairy, get_facility, get_ops_day,
                           paged_list, resolve_refs)
from services import calc, derive
from validation import date_of, require_range

bp = Blueprint("applications", __name__)

READ_ROLES = ["PlatformAdmin", "ProjectOperator", "DairyPartner", "CreditVerifier"]


def _recompute_pan(application, day):
    liquid_n, solids_n, pan = calc.plant_available_nitrogen(
        application["liquid_tonnes_applied"], application["solids_tonnes_applied"],
        day["lab_total_nitrogen_mg_per_l"], application["pan_basis"])
    application["liquid_total_nitrogen_kg"] = liquid_n
    application["solids_total_nitrogen_kg"] = solids_n
    application["plant_available_nitrogen_kg"] = pan


@bp.post("/nutrient-applications")
@endpoint(["ProjectOperator"])
def create_application():
    b = body()
    dairy, facility, day = resolve_refs(b, (("dairy_id", get_dairy),
                                            ("facility_id", get_facility),
                                            ("ops_day_id", get_ops_day)))
    land_unit = b.string("land_unit_code")
    start = b.date("application_start_date")
    end = b.date("application_end_date")
    solids = b.number("solids_tonnes_applied", 3, ge=0)
    liquid = b.number("liquid_tonnes_applied", 3, ge=0)
    pan_basis = b.enum("pan_basis", ("LAB", "AGRONOMIC"))
    require_range(start, end)

    setback = timedelta(days=config.REAPPLICATION_SETBACK_DAYS)
    for other in db.applications.values():
        if other["dairy_id"] != dairy["id"] or other["land_unit_code"] != land_unit:
            continue
        if other["status"] not in ("PLANNED", "APPLIED"):
            continue
        o_start = date_of(other["application_start_date"])
        o_end = date_of(other["application_end_date"])
        if start <= o_end and o_start <= end:
            fail("ERR_LAND_UNIT_SETBACK_CONFLICT",
                 "The application window overlaps an existing window on this land unit.")
        if o_end < start and start <= o_end + setback:
            fail("ERR_LAND_UNIT_SETBACK_CONFLICT",
                 "The land unit is still inside its mandatory soil rest period.")

    row = db.new_row({
        "dairy_id": dairy["id"],
        "facility_id": facility["id"],
        "ops_day_id": day["id"],
        "land_unit_code": land_unit,
        "application_start_date": b.raw["application_start_date"],
        "application_end_date": b.raw["application_end_date"],
        "solids_tonnes_applied": solids,
        "liquid_tonnes_applied": liquid,
        "pan_basis": pan_basis,
        "liquid_total_nitrogen_kg": None,
        "solids_total_nitrogen_kg": None,
        "plant_available_nitrogen_kg": None,
        "status": "PLANNED",
    })
    _recompute_pan(row, day)
    db.applications[row["id"]] = row
    return created(derive.ser_application(row))


@bp.get("/nutrient-applications")
@endpoint(READ_ROLES)
def list_applications():
    return paged_list(db.applications, derive.ser_application,
                      ("dairy_id", "facility_id", "ops_day_id", "status", "land_unit_code"))


@bp.get("/nutrient-applications/<application_id>")
@endpoint(READ_ROLES)
def read_application(application_id):
    return ok(derive.ser_application(get_application(application_id)))


@bp.post("/nutrient-applications/<application_id>/apply")
@endpoint(["ProjectOperator"])
def apply_application(application_id):
    application = get_application(application_id)
    b = body()
    b.string("applicator_name", required=False)
    day = db.ops_days[application["ops_day_id"]]
    facility = db.facilities[application["facility_id"]]
    dairy = db.dairies[application["dairy_id"]]

    if application["status"] != "PLANNED":
        fail("ERR_INVALID_STATE", "Only a PLANNED application may be committed.")
    if not day["separation_recorded"]:
        fail("ERR_SEPARATION_NOT_RECORDED",
             "The source operations day has no recorded separation.")

    _recompute_pan(application, day)

    mass = derive.facility_mass(facility["id"])
    if D(application["solids_tonnes_applied"]) > mass["digestate_solids_on_hand_tonnes"] or \
            D(application["liquid_tonnes_applied"]) > mass["digestate_liquid_on_hand_tonnes"]:
        fail("ERR_DIGESTATE_INVENTORY_INSUFFICIENT",
             "The digestate inventory on hand is insufficient.")

    ytd = derive.dairy_pan_ytd(dairy["id"])
    if ytd + D(application["plant_available_nitrogen_kg"]) > D(dairy["annual_nitrogen_budget_kg"]):
        fail("ERR_NITROGEN_BUDGET_EXCEEDED",
             "The application would exceed the dairy's annual nitrogen budget.")

    application["status"] = "APPLIED"
    db.touch(application)
    db.touch(facility)
    db.touch(dairy)
    return ok(derive.ser_application(application))


@bp.post("/nutrient-applications/<application_id>/void")
@endpoint(["ProjectOperator"])
def void_application(application_id):
    application = get_application(application_id)
    b = body()
    b.string("void_reason")

    if application["status"] not in ("PLANNED", "APPLIED"):
        fail("ERR_INVALID_STATE", "Only a PLANNED or APPLIED application may be voided.")

    was_applied = application["status"] == "APPLIED"
    application["status"] = "VOIDED"
    db.touch(application)
    if was_applied:
        db.touch(db.facilities[application["facility_id"]])
        db.touch(db.dairies[application["dairy_id"]])
    return ok(derive.ser_application(application))
