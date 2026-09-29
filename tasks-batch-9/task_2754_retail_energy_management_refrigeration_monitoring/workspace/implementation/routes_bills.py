"""Utility bill recording, recomputation and dispute settlement (PRD 3.6)."""

from decimal import Decimal

from flask import Blueprint, g

import calc
import cascade
import common
import derive
import envelope
import serial
import validate as v
from db import db, new_row
from errors import ApiError
from security import ENERGY_ANALYST, ENERGY_MANAGER, roles
from util import rhu

bp = Blueprint("bills", __name__)


@bp.route("/utility-accounts/<account_id>/utility-bills", methods=["POST"])
@roles(ENERGY_ANALYST)
def record_bill(account_id):
    body = v.body()
    period_start = v.get_dt(body, "period_start_iso")
    period_end = v.get_dt(body, "period_end_iso")
    on_peak_kwh = v.get_num(body, "on_peak_kwh", 2, ge=0)
    off_peak_kwh = v.get_num(body, "off_peak_kwh", 2, ge=0)
    billed_kwh = v.get_num(body, "billed_kwh", 2, ge=0)
    billed_peak_kw = v.get_num(body, "billed_peak_kw", 1, ge=0)
    billed_amount_usd = v.get_num(body, "billed_amount_usd", 2, ge=0)
    v.window(period_start, period_end, "period_start_iso", "period_end_iso")
    common.get_account(account_id)
    bill = new_row(db.bills, {
        "utility_account_id": account_id,
        "period_start_iso": period_start,
        "period_end_iso": period_end,
        "on_peak_kwh": on_peak_kwh,
        "off_peak_kwh": off_peak_kwh,
        "billed_kwh": billed_kwh,
        "billed_peak_kw": billed_peak_kw,
        "billed_amount_usd": billed_amount_usd,
        "recomputed_energy_cost_usd": None,
        "recomputed_demand_cost_usd": None,
        "recomputed_rider_cost_usd": None,
        "recomputed_surcharge_usd": None,
        "recomputed_amount_usd": None,
        "billable_demand_kw": None,
        "peak_basis": None,
        "variance_pct": None,
        "validation_state": "RECEIVED",
        "recomputed_by_user_id": None,
        "dispute_reason": None,
        "adjusted_amount_usd": None,
        "adjusted_by_user_id": None,
    })
    return envelope.created(serial.bill(bill))


@bp.route("/utility-bills/<bill_id>/recompute", methods=["POST"])
@roles(ENERGY_ANALYST)
def recompute_bill(bill_id):
    bill = common.get_bill(bill_id)
    if bill["validation_state"] != "RECEIVED":
        raise ApiError("ERR_BILL_STATE_INVALID")
    account = derive.account_of_bill(bill)
    intervals = calc.period_intervals(account["id"], bill["period_start_iso"],
                                      bill["period_end_iso"])
    demand, basis = calc.period_peak_demand(intervals, account["rate_family"],
                                            account["ratchet_peak_kw"])
    if demand is None:
        raise ApiError("ERR_DEMAND_DATA_MISSING")
    parts = calc.bill_recompute(bill["on_peak_kwh"], bill["off_peak_kwh"],
                               account["rate_on_peak"], account["rate_off_peak"],
                               demand, account["demand_charge_per_kw"])
    bill.update(parts)
    bill["billable_demand_kw"] = demand
    bill["peak_basis"] = basis
    if parts["recomputed_amount_usd"] == 0:
        variance = rhu(0, 2)
    else:
        variance = calc.bill_variance_pct(bill["billed_amount_usd"],
                                          parts["recomputed_amount_usd"])
    bill["variance_pct"] = variance
    tolerance = calc.BILL_VARIANCE_TOLERANCE_PCT
    bill["validation_state"] = ("VALIDATED" if abs(variance) <= tolerance
                               else "VARIANCE_FLAGGED")
    bill["recomputed_by_user_id"] = g.user_id
    cascade.touch(bill)
    return envelope.ok(serial.bill(bill))


@bp.route("/utility-bills/<bill_id>/dispute", methods=["POST"])
@roles(ENERGY_ANALYST)
def dispute_bill(bill_id):
    body = v.body()
    dispute_reason = v.get_str(body, "dispute_reason", min_len=1)
    bill = common.get_bill(bill_id)
    if bill["validation_state"] != "VARIANCE_FLAGGED":
        raise ApiError("ERR_BILL_STATE_INVALID")
    bill["validation_state"] = "DISPUTED"
    bill["dispute_reason"] = dispute_reason
    cascade.touch(bill)
    return envelope.ok(serial.bill(bill))


@bp.route("/utility-bills/<bill_id>/adjustment", methods=["POST"])
@roles(ENERGY_MANAGER)
def adjust_bill(bill_id):
    body = v.body()
    adjusted_amount_usd = v.get_num(body, "adjusted_amount_usd", 2, ge=0)
    bill = common.get_bill(bill_id)
    if bill["recomputed_by_user_id"] is not None \
            and g.user_id == bill["recomputed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if bill["validation_state"] != "DISPUTED":
        raise ApiError("ERR_BILL_STATE_INVALID")
    account = derive.account_of_bill(bill)
    if account is not None and account["tariff_state"] == "PENDING_SWITCH":
        raise ApiError("ERR_TARIFF_SWITCH_IN_PROGRESS")
    bill["validation_state"] = "ADJUSTED"
    bill["adjusted_amount_usd"] = adjusted_amount_usd
    bill["adjusted_by_user_id"] = g.user_id
    cascade.touch(bill)
    return envelope.ok(serial.bill(bill))
