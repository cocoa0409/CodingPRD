"""Capital retrofits, measured savings and verification (PRD 3.10)."""

from flask import Blueprint, g

import calc
import cascade
import common
import derive
import envelope
import serial
import validate as v
from common import APPROVAL_DECISIONS, MEASURE_TYPES
from db import db, new_row
from errors import ApiError
from security import ENERGY_ANALYST, ENERGY_MANAGER, roles

bp = Blueprint("retrofits", __name__)


@bp.route("/stores/<store_id>/retrofit-projects", methods=["POST"])
@roles(ENERGY_ANALYST, ENERGY_MANAGER)
def propose(store_id):
    body = v.body()
    measure_type = v.get_enum(body, "measure_type", MEASURE_TYPES)
    capex_usd = v.get_num(body, "capex_usd", 2, gt=0)
    projected = v.get_num(body, "projected_annual_savings_kwh", 2, gt=0)
    store = common.get_store(store_id)
    annual_savings_usd, payback_years, score = calc.retrofit_simple_payback(
        projected, capex_usd, store["blended_rate_usd_per_kwh"])
    project = new_row(db.retrofits, {
        "store_id": store_id,
        "measure_type": measure_type,
        "capex_usd": capex_usd,
        "projected_annual_savings_kwh": projected,
        "annual_savings_usd": annual_savings_usd,
        "payback_years": payback_years,
        "priority_score": score,
        "priority_basis": "SIMPLE_PAYBACK",
        "state": "PROPOSED",
        "escalated_review": False,
        "proposed_by_user_id": g.user_id,
        "approved_by_user_id": None,
        "install_completed_iso": None,
        "baseline_period_kwh": None,
        "post_period_kwh": None,
        "mv_period_days": None,
        "adjusted_baseline_kwh": None,
        "measured_savings_kwh": None,
        "realization_rate": None,
        "revocation_reason": None,
    })
    return envelope.created(serial.retrofit(project))


@bp.route("/retrofit-projects/<project_id>/approve", methods=["POST"])
@roles(ENERGY_MANAGER)
def approve(project_id):
    body = v.body()
    decision = v.get_enum(body, "decision", APPROVAL_DECISIONS)
    project = common.get_retrofit(project_id)
    if project["proposed_by_user_id"] == g.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if project["state"] != "PROPOSED":
        raise ApiError("ERR_RETROFIT_STATE_INVALID")
    store = db.stores.get(project["store_id"])
    if store is not None:
        common.require_bms_commissioned(store)
    project["approved_by_user_id"] = g.user_id
    if decision == "REJECT":
        project["state"] = "REJECTED"
    else:
        project["state"] = "APPROVED"
        project["priority_basis"] = "RISK_ADJUSTED"
        density = derive.refrigeration_fault_density(project["store_id"])
        annual_savings_usd, payback_years, score = calc.retrofit_risk_adjusted(
            project["projected_annual_savings_kwh"], project["capex_usd"],
            store["blended_rate_usd_per_kwh"], density)
        project["annual_savings_usd"] = annual_savings_usd
        project["payback_years"] = payback_years
        project["priority_score"] = score
    cascade.touch(project)
    return envelope.ok(serial.retrofit(project))


@bp.route("/retrofit-projects/<project_id>/submit-measurement", methods=["POST"])
@roles(ENERGY_ANALYST)
def submit_measurement(project_id):
    body = v.body()
    install_completed_iso = v.get_dt(body, "install_completed_iso")
    baseline_period_kwh = v.get_num(body, "baseline_period_kwh", 2, ge=0)
    post_period_kwh = v.get_num(body, "post_period_kwh", 2, ge=0)
    mv_period_days = v.get_int(body, "mv_period_days", min_=1)
    project = common.get_retrofit(project_id)
    if project["state"] not in ("APPROVED", "SHORTFALL_REVIEW"):
        raise ApiError("ERR_RETROFIT_STATE_INVALID")
    if mv_period_days < calc.MV_MIN_PERIOD_DAYS:
        raise ApiError("ERR_MV_PERIOD_TOO_SHORT")
    if install_completed_iso > db.clock:
        raise ApiError("ERR_MV_PERIOD_TOO_SHORT")
    store = db.stores.get(project["store_id"])
    adjusted, measured, expected, rate = calc.measured_savings(
        store["climate_zone"], baseline_period_kwh, post_period_kwh,
        mv_period_days, project["projected_annual_savings_kwh"])
    project["install_completed_iso"] = install_completed_iso
    project["baseline_period_kwh"] = baseline_period_kwh
    project["post_period_kwh"] = post_period_kwh
    project["mv_period_days"] = mv_period_days
    project["adjusted_baseline_kwh"] = adjusted
    project["measured_savings_kwh"] = measured
    project["realization_rate"] = rate
    project["state"] = ("VERIFIED" if rate >= calc.VERIFY_FLOOR_RATE
                        else "SHORTFALL_REVIEW")
    cascade.touch(project)
    cascade.touch(store)
    return envelope.ok(serial.retrofit(project))


@bp.route("/retrofit-projects/<project_id>/revoke-verification", methods=["POST"])
@roles(ENERGY_MANAGER)
def revoke_verification(project_id):
    body = v.body()
    reason = v.get_str(body, "revocation_reason", min_len=1)
    project = common.get_retrofit(project_id)
    if project["state"] != "VERIFIED":
        raise ApiError("ERR_RETROFIT_STATE_INVALID")
    project["state"] = "SHORTFALL_REVIEW"
    project["revocation_reason"] = reason
    cascade.touch(project)
    cascade.touch(db.stores.get(project["store_id"]))
    return envelope.ok(serial.retrofit(project))
