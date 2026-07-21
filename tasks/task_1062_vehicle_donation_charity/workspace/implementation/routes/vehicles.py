"""Asset records and the fair-market-value estimate (PRD section 3.3)."""

from flask import Blueprint, request

import db
import middleware as mw
import response as resp
from errors import ApiError
from services import calc, domain

bp = Blueprint("vehicles", __name__)

CONDITIONS = {"EXCELLENT", "GOOD", "FAIR", "POOR", "SALVAGE"}

READ_ROLES = (
    "IntakeAgent",
    "AuctionManager",
    "FinanceOfficer",
    "ProgramAdmin",
    "TitleClerk",
)


def _apply_estimate(vehicle, donation, variant):
    if variant == "BASE_CONDITION":
        grade = donation["declared_condition"]
        miles = None
    else:
        grade = vehicle["condition_grade"]
        miles = vehicle["odometer_miles"]
    vehicle["fmv_estimate_cents"] = calc.vehicle_fmv_estimate(
        vehicle["base_book_value_cents"], grade, miles, vehicle["salvage_flag"]
    )
    vehicle["fmv_variant"] = variant
    donation["fmv_estimate_cents"] = vehicle["fmv_estimate_cents"]
    db.touch(donation)


@bp.post("/api/vehicles")
def create_vehicle():
    mw.auth("IntakeAgent", "AuctionManager")
    data = mw.body()
    donation_id = mw.req_string(data, "donation_id")
    vin = mw.req_string(data, "vin")
    year = mw.req_int(data, "year", minimum=1900, maximum=2100)
    make = mw.req_string(data, "make")
    model = mw.req_string(data, "model")
    base_book = mw.req_int(data, "base_book_value_cents", minimum=1)
    salvage_flag = mw.opt_bool(data, "salvage_flag", False)
    keys_present = mw.opt_bool(data, "keys_present", True)

    donation = mw.resolve(db.donations, donation_id, "ERR_DONATION_NOT_FOUND")

    if domain.vehicle_for_donation(donation_id) is not None:
        raise ApiError("ERR_DUPLICATE_VEHICLE", "This donation already has an asset record.")
    if any(v["vin"] == vin for v in db.vehicles.values()):
        raise ApiError("ERR_DUPLICATE_VIN", "This VIN is already registered.")

    rec = db.new_record()
    rec["donation_id"] = donation_id
    rec["vin"] = vin
    rec["year"] = year
    rec["make"] = make
    rec["model"] = model
    rec["base_book_value_cents"] = base_book
    rec["odometer_miles"] = None
    rec["condition_grade"] = None
    rec["salvage_flag"] = salvage_flag
    rec["keys_present"] = keys_present
    rec["inspected"] = False
    rec["fmv_estimate_cents"] = None
    rec["fmv_variant"] = "BASE_CONDITION"
    db.vehicles[rec["id"]] = rec

    _apply_estimate(rec, donation, "BASE_CONDITION")
    return resp.created(rec)


@bp.get("/api/vehicles/<vehicle_id>")
def get_vehicle(vehicle_id):
    mw.auth(*READ_ROLES)
    rec = mw.resolve(db.vehicles, vehicle_id, "ERR_VEHICLE_NOT_FOUND")
    return resp.ok(rec)


@bp.get("/api/vehicles")
def list_vehicles():
    mw.auth(*READ_ROLES)
    donation_filter = request.args.get("donation_id")
    limit, offset = mw.pagination()
    rows = [
        v
        for v in db.vehicles.values()
        if donation_filter is None or v["donation_id"] == donation_filter
    ]
    return resp.listing(db.ordered(rows), limit, offset)


@bp.patch("/api/vehicles/<vehicle_id>")
def inspect_vehicle(vehicle_id):
    mw.auth("AuctionManager", "IntakeAgent")
    rec = mw.resolve(db.vehicles, vehicle_id, "ERR_VEHICLE_NOT_FOUND")
    data = mw.body()
    odometer = mw.opt_int(data, "odometer_miles", default=rec["odometer_miles"], minimum=0)
    grade = mw.opt_enum(data, "condition_grade", CONDITIONS, default=rec["condition_grade"])
    salvage_flag = mw.opt_bool(data, "salvage_flag", rec["salvage_flag"])
    keys_present = mw.opt_bool(data, "keys_present", rec["keys_present"])

    rec["odometer_miles"] = odometer
    rec["condition_grade"] = grade
    rec["salvage_flag"] = salvage_flag
    rec["keys_present"] = keys_present
    rec["inspected"] = True

    donation = db.donations.get(rec["donation_id"])
    if donation is not None:
        _apply_estimate(rec, donation, "POST_INSPECTION")
    db.touch(rec)
    return resp.ok(rec)
