"""Capacity obligations: enrolment, unavailability and assessment (PRD 3.8)."""

from decimal import Decimal

from flask import Blueprint

import db
import errors
import middleware
import response
import validators as v
from errors import ApiError
from numeric import D, rnd, f
from services import calc, core

bp = Blueprint("obligations", __name__)

STATUSES = ("ACTIVE", "SHORTFALL", "PENALIZED", "FULFILLED")
MODES = ("PRELIMINARY", "FINAL")


@bp.post("/capacity-obligations")
def enrol():
    middleware.authorize("AssetManager", "MarketOperator")
    body = v.json_body()

    asset_id = v.ident(body, "asset_id")
    program_name = v.text(body, "program_name", min_len=1, max_len=120)
    program_year = v.integer(body, "program_year", ge=2000, le=2100)
    committed_mw = v.num(body, "committed_mw", gt=0)
    availability_required = v.num(body, "availability_hours_required", gt=0)
    penalty_rate = v.num(body, "penalty_rate_usd_per_mw_hour", ge=0)
    duration = v.num(body, "obligation_duration_hours", required=False,
                     default=4.0, gt=0)

    asset = core.get_asset(asset_id)

    if (D(committed_mw) > D(asset["power_rating_mw"])
            or D(availability_required) > calc.ANNUAL_HOURS):
        raise ApiError(errors.ERR_COMMITMENT_EXCEEDS_RATING, 422,
                       "The commitment exceeds the asset's rating or the annual "
                       "hour count.")

    for existing in core.obligations_of(asset_id):
        if (existing["program_name"] == program_name
                and existing["program_year"] == program_year):
            raise ApiError(errors.ERR_DUPLICATE_OBLIGATION, 409,
                           "The asset is already enrolled in this programme "
                           "for this programme year.")

    obligation = db.new_row()
    obligation.update({
        "asset_id": asset_id,
        "program_name": program_name,
        "program_year": program_year,
        "committed_mw": committed_mw,
        "obligation_duration_hours": duration,
        "availability_hours_required": availability_required,
        "penalty_rate_usd_per_mw_hour": penalty_rate,
        "unavailable_hours": 0.0,
        "accrual_started_at": None,
        "measured_available_hours": 0.0,
        "availability_pct": None,
        "shortfall_hours": 0.0,
        "penalty_exposure_usd": 0.0,
        "assessment_mode": None,
        "derated_committed_mw": None,
        "status": "ACTIVE",
    })
    db.obligations[obligation["id"]] = obligation
    return response.created(db.serialize(obligation))


@bp.get("/capacity-obligations/<obligation_id>")
def read_obligation(obligation_id):
    middleware.any_role()
    return response.ok(db.serialize(core.get_obligation(obligation_id)))


@bp.get("/capacity-obligations")
def list_obligations():
    middleware.any_role()
    limit, offset = v.pagination()
    asset_id = v.query_str("asset_id")
    program_year = v.query_int("program_year")
    status = v.query_enum("status", STATUSES)

    rows = list(db.obligations.values())
    if asset_id is not None:
        rows = [r for r in rows if r["asset_id"] == asset_id]
    if program_year is not None:
        rows = [r for r in rows if r["program_year"] == program_year]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = core.newest_first(rows)
    page, total = core.paginate(rows, limit, offset)
    return response.ok_list([db.serialize(r) for r in page], limit, offset, total)


@bp.post("/capacity-obligations/<obligation_id>/unavailability")
def record_unavailability(obligation_id):
    middleware.authorize("ControlRoomOperator", "MarketOperator")
    body = v.json_body()
    delta = v.num(body, "unavailable_hours_delta", ge=0)
    v.text(body, "reason", required=False, default=None, min_len=1, max_len=500)

    obligation = core.get_obligation(obligation_id)
    obligation["unavailable_hours"] = f(
        rnd(D(obligation["unavailable_hours"]) + D(delta), 2), 2)
    db.touch(obligation)
    return response.ok(db.serialize(obligation))


@bp.post("/capacity-obligations/<obligation_id>/assess")
def assess(obligation_id):
    middleware.authorize("MarketOperator")
    body = v.json_body()
    mode = v.enum(body, "mode", MODES)

    obligation = core.get_obligation(obligation_id)
    asset = db.assets.get(obligation["asset_id"])
    now = db.clock_now()

    if mode == "PRELIMINARY":
        period_hours = core.preliminary_period_hours(obligation, now)
    else:
        period_hours = calc.ANNUAL_HOURS

    derated = None
    if asset is not None:
        derated = calc.derated_committed(asset["available_energy_mwh"], obligation)

    result = calc.assess_obligation(obligation, mode, period_hours, derated)

    current = obligation["status"]
    new_status = result["status"]
    if current == "PENALIZED":
        new_status = "PENALIZED"
    elif current == "FULFILLED":
        new_status = "FULFILLED"

    obligation["measured_available_hours"] = result["measured_available_hours"]
    obligation["availability_pct"] = result["availability_pct"]
    obligation["shortfall_hours"] = result["shortfall_hours"]
    obligation["penalty_exposure_usd"] = result["penalty_exposure_usd"]
    obligation["assessment_mode"] = result["assessment_mode"]
    obligation["derated_committed_mw"] = result["derated_committed_mw"]
    obligation["status"] = new_status
    db.touch(obligation)
    return response.ok(db.serialize(obligation))
