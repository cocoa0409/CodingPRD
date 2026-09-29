"""State programs, fee adequacy and the logical clock."""

from flask import Blueprint

import calc
import response
import services
from db import clock, db
from errors import ApiError
from middleware import ADMIN, ALL_ROLES, AUDITOR, auth, get_program
from util import F, base_record, parse_dt, public, touch, validate_body

bp = Blueprint("programs", __name__)


CREATE_SPEC = [
    F("state_code", "string", pattern=r"^[A-Z]{2}$"),
    F("program_name", "string"),
    F("forecast_annual_cost_cents", "int", minimum=1),
    F("forecast_annual_units", "int", minimum=1),
    F("forecast_other_revenue_cents", "int", required=False, minimum=0),
    F("reserve_target_months", "int", minimum=1, maximum=12),
    F("reserve_opening_cents", "int", minimum=0),
    F("site_credit_cents_per_unit", "int", minimum=0),
    F("volume_bonus_threshold_units", "int", minimum=1),
    F("delinquency_alert_threshold", "int", required=False, minimum=1),
]

FORECAST_SPEC = [
    F("forecast_annual_cost_cents", "int", required=False, minimum=1),
    F("forecast_annual_units", "int", required=False, minimum=1),
    F("forecast_other_revenue_cents", "int", required=False, minimum=0),
    F("reserve_target_months", "int", required=False, minimum=1, maximum=12),
]


@bp.post("/state-programs")
def create_program():
    auth([ADMIN])
    body = validate_body(CREATE_SPEC)
    rec = base_record()
    rec.update({
        "state_code": body["state_code"],
        "program_name": body["program_name"],
        "forecast_annual_cost_cents": body["forecast_annual_cost_cents"],
        "forecast_annual_units": body["forecast_annual_units"],
        "forecast_other_revenue_cents": body.get("forecast_other_revenue_cents", 0),
        "reserve_target_months": body["reserve_target_months"],
        "reserve_opening_cents": body["reserve_opening_cents"],
        "site_credit_cents_per_unit": body["site_credit_cents_per_unit"],
        "volume_bonus_threshold_units": body["volume_bonus_threshold_units"],
        "delinquency_alert_threshold": body.get("delinquency_alert_threshold", 1),
        "fee_collected_cents": 0,
        "site_credit_paid_cents": 0,
        "hauler_payment_paid_cents": 0,
        "reserve_balance_cents": 0,
        "receivable_cents": 0,
        "reserve_coverage_months": 0.0,
        "recommended_rate_cents": 0,
        "enrolled_site_count": 0,
        "reported_units_total": 0,
        "delinquent_registrant_count": 0,
        "enforcement_posture": "NORMAL",
    })
    db.state_programs[rec["id"]] = rec
    services.refresh_program(rec)
    return response.obj(public(rec), 201)


@bp.get("/state-programs/<program_id>")
def read_program(program_id):
    auth(ALL_ROLES)
    program = get_program(program_id)
    return response.obj(public(program))


@bp.patch("/state-programs/<program_id>/cost-forecast")
def revise_forecast(program_id):
    auth([ADMIN])
    body = validate_body(FORECAST_SPEC)
    program = get_program(program_id)
    for field in ("forecast_annual_cost_cents", "forecast_annual_units",
                  "forecast_other_revenue_cents", "reserve_target_months"):
        if field in body:
            program[field] = body[field]
    services.refresh_program_and_touch(program)
    return response.obj(public(program))


@bp.get("/state-programs/<program_id>/fee-adequacy")
def fee_adequacy(program_id):
    auth([ADMIN, AUDITOR])
    program = get_program(program_id)
    result = calc.fee_rate_recommendation(program)
    data = {
        "recommended_rate_cents": result["recommended_rate_cents"],
        "band_low_cents": result["band_low_cents"],
        "band_high_cents": result["band_high_cents"],
        "base_rate_cents": result["base_rate_cents"],
        "admin_surcharge_pct": result["admin_surcharge_pct"],
        "reserve_target_cents": result["reserve_target_cents"],
        "reserve_gap_cents": result["reserve_gap_cents"],
        "reserve_balance_cents": program["reserve_balance_cents"],
        "reserve_coverage_months": program["reserve_coverage_months"],
    }
    return response.obj(data)


@bp.post("/_clock/set_current_utc")
def set_clock():
    auth([ADMIN])
    body = validate_body([F("to_iso8601", "datetime")])
    raw = body["to_iso8601"]
    clock.set(raw, parse_dt(raw))
    return response.obj({"current_utc": clock.raw})
