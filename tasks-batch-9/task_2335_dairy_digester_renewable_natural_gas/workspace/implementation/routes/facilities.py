from decimal import Decimal

from flask import Blueprint

from db import db
from errors import fail
from middleware import endpoint, body
from response import created, ok
from routes.common import get_facility, paged_list
from services import calc, derive

bp = Blueprint("facilities", __name__)

FACILITY_READ_ROLES = ["PlatformAdmin", "ProjectOperator", "ProgramAdministrator",
                       "CreditVerifier", "FinanceController", "PipelineScheduler"]


@bp.post("/facilities")
@endpoint(["PlatformAdmin"])
def create_facility():
    b = body()
    regime = None
    name = b.string("name")
    volume = b.number("digester_volume_m3", None, gt=0)
    hydraulic = b.number("hydraulic_capacity_tonnes_per_day", 3, gt=0)
    regime = b.enum("thermal_regime", ("MESOPHILIC", "THERMOPHILIC"))
    target_temp = b.number("target_temperature_c", 1)
    reserve_target = b.integer("reserve_target_cents", ge=0)
    annual_debt = b.integer("annual_debt_service_cents", gt=0)
    dscr_min = b.number("dscr_minimum", 3, gt=0)

    row = db.new_row({
        "name": name,
        "digester_volume_m3": volume,
        "hydraulic_capacity_tonnes_per_day": hydraulic,
        "thermal_regime": regime,
        "target_temperature_c": target_temp,
        "design_max_olr": calc.design_olr_limit(regime),
        "ops_posture": "STABLE",
        "distribution_posture": "OPEN",
        "posture_override_active": False,
        "reserve_target_cents": reserve_target,
        "reserve_balance_cents": 0,
        "annual_debt_service_cents": annual_debt,
        "dscr_minimum": dscr_min,
        "dscr_current": Decimal("0.000"),
    })
    db.facilities[row["id"]] = row
    return created(derive.ser_facility(row))


@bp.get("/facilities")
@endpoint(FACILITY_READ_ROLES)
def list_facilities():
    return paged_list(db.facilities, derive.ser_facility,
                      ("ops_posture", "distribution_posture"))


@bp.get("/facilities/<facility_id>")
@endpoint(FACILITY_READ_ROLES)
def read_facility(facility_id):
    return ok(derive.ser_facility(get_facility(facility_id)))


@bp.get("/facilities/<facility_id>/financial-summary")
@endpoint(["PlatformAdmin", "ProjectOperator", "FinanceController"])
def financial_summary(facility_id):
    return ok(derive.ser_facility(get_facility(facility_id)))


@bp.post("/facilities/<facility_id>/reserve-funding")
@endpoint(["FinanceController"])
def reserve_funding(facility_id):
    facility = get_facility(facility_id)
    b = body()
    amount = b.integer("amount_cents")
    b.string("memo", required=False)
    if amount <= 0 or facility["reserve_balance_cents"] + amount > facility["reserve_target_cents"]:
        fail("ERR_RESERVE_TARGET_EXCEEDED",
             "Funding would overfund the debt-service reserve account.")
    facility["reserve_balance_cents"] += amount
    db.touch(facility)
    return ok(derive.ser_facility(facility))


@bp.post("/facilities/<facility_id>/posture-override")
@endpoint(["PlatformAdmin"])
def posture_override(facility_id):
    facility = get_facility(facility_id)
    b = body()
    dimension = b.enum("dimension", ("OPS", "DISTRIBUTION"))
    b.string("justification")
    if dimension == "OPS":
        if facility["ops_posture"] != "UPSET":
            fail("ERR_INVALID_STATE", "ops_posture must be UPSET to be overridden.")
        facility["ops_posture"] = "RESTRICTED"
    else:
        if facility["distribution_posture"] != "LOCKED":
            fail("ERR_INVALID_STATE", "distribution_posture must be LOCKED to be overridden.")
        facility["distribution_posture"] = "RESTRICTED"
    facility["posture_override_active"] = True
    db.touch(facility)
    return ok(derive.ser_facility(facility))
