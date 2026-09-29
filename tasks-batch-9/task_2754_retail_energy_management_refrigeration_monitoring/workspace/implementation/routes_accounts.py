"""Utility accounts, metered demand intervals and tariff switching (PRD 3.6, 3.7)."""

from decimal import Decimal

from flask import Blueprint

import calc
import cascade
import common
import derive
import envelope
import serial
import validate as v
from common import (DR_ENROLLMENT_STATES, EVENT_STATES, RATE_FAMILIES,
                    SETTLEMENT_STATES, TARIFF_STATES, VALIDATION_STATES)
from db import db, new_event_row, new_row
from errors import ApiError
from security import (BMS_GATEWAY, ENERGY_ANALYST, ENERGY_MANAGER,
                      NON_GATEWAY_ROLES, ALL_ROLES, PLATFORM_ADMIN, roles)

bp = Blueprint("accounts", __name__)

DEFAULT_RATCHET_PEAK_KW = Decimal("0.0")


@bp.route("/stores/<store_id>/utility-accounts", methods=["POST"])
@roles(ENERGY_MANAGER)
def attach_account(store_id):
    body = v.body()
    utility_name = v.get_str(body, "utility_name", min_len=1)
    rate_schedule_code = v.get_str(body, "rate_schedule_code", min_len=1)
    rate_family = v.get_enum(body, "rate_family", RATE_FAMILIES)
    demand_charge = v.get_num(body, "demand_charge_per_kw", 2, gt=0)
    rate_on_peak = v.get_num(body, "rate_on_peak", 4, gt=0)
    rate_off_peak = v.get_num(body, "rate_off_peak", 4, gt=0)
    ratchet_peak_kw = v.get_num(body, "ratchet_peak_kw", 1, required=False,
                                default=DEFAULT_RATCHET_PEAK_KW, ge=0)
    cand_code = v.get_str(body, "candidate_rate_schedule_code", required=False)
    cand_family = v.get_enum(body, "candidate_rate_family", RATE_FAMILIES, required=False)
    cand_demand_charge = v.get_num(body, "candidate_demand_charge_per_kw", 2,
                                   required=False, gt=0)
    cand_on_peak = v.get_num(body, "candidate_rate_on_peak", 4, required=False, gt=0)
    cand_off_peak = v.get_num(body, "candidate_rate_off_peak", 4, required=False, gt=0)
    common.get_store(store_id)
    account = new_row(db.accounts, {
        "store_id": store_id,
        "utility_name": utility_name,
        "rate_schedule_code": rate_schedule_code,
        "rate_family": rate_family,
        "demand_charge_per_kw": demand_charge,
        "rate_on_peak": rate_on_peak,
        "rate_off_peak": rate_off_peak,
        "ratchet_peak_kw": ratchet_peak_kw,
        "candidate_rate_schedule_code": cand_code,
        "candidate_rate_family": cand_family,
        "candidate_demand_charge_per_kw": cand_demand_charge,
        "candidate_rate_on_peak": cand_on_peak,
        "candidate_rate_off_peak": cand_off_peak,
        "tariff_state": "STABLE",
        "tariff_switch_effective_from_iso": None,
        "tariff_locked_until_iso": None,
        "dr_enrollment_state": "ENROLLED",
    })
    return envelope.created(serial.account(account))


@bp.route("/utility-accounts/<account_id>", methods=["GET"])
@roles(*NON_GATEWAY_ROLES)
def get_account(account_id):
    account = common.get_account(account_id)
    return envelope.ok(serial.account(account))


@bp.route("/utility-accounts/<account_id>/utility-bills", methods=["GET"])
@roles(*NON_GATEWAY_ROLES)
def list_account_bills(account_id):
    limit, offset = v.query_pagination()
    validation_state = v.query_enum("validation_state", VALIDATION_STATES)
    common.get_account(account_id)
    items = derive.account_bills(account_id)
    items = common.apply_eq(items, "validation_state", validation_state)
    return common.list_response(items, serial.bill, limit, offset)


@bp.route("/utility-accounts/<account_id>/demand-intervals", methods=["GET"])
@roles(*ALL_ROLES)
def list_account_intervals(account_id):
    limit, offset = v.query_pagination()
    is_on_peak = v.query_bool("is_on_peak")
    is_dr_event_day = v.query_bool("is_dr_event_day")
    common.get_account(account_id)
    items = derive.account_intervals(account_id)
    if is_on_peak is not None:
        items = [i for i in items if i["is_on_peak"] == is_on_peak]
    if is_dr_event_day is not None:
        items = [i for i in items if i["is_dr_event_day"] == is_dr_event_day]
    return common.list_response(items, serial.interval, limit, offset)


@bp.route("/utility-accounts/<account_id>/demand-response-events", methods=["GET"])
@roles(*NON_GATEWAY_ROLES)
def list_account_events(account_id):
    limit, offset = v.query_pagination()
    event_state = v.query_enum("event_state", EVENT_STATES)
    settlement_state = v.query_enum("settlement_state", SETTLEMENT_STATES)
    common.get_account(account_id)
    items = derive.account_events(account_id)
    items = common.apply_eq(items, "event_state", event_state)
    items = common.apply_eq(items, "settlement_state", settlement_state)
    return common.list_response(items, serial.dr_event, limit, offset)


@bp.route("/utility-accounts/<account_id>/tariff-comparison", methods=["GET"])
@roles(PLATFORM_ADMIN, ENERGY_MANAGER, ENERGY_ANALYST)
def tariff_comparison(account_id):
    account = common.get_account(account_id)
    projection = calc.tariff_projection(account)
    return envelope.ok({
        "reference_bill_id": projection["reference_bill_id"],
        "current_annual_cost_usd": projection["current_annual_cost_usd"],
        "candidate_annual_cost_usd": projection["candidate_annual_cost_usd"],
        "annual_delta_usd": projection["annual_delta_usd"],
        "switch_recommended": projection["switch_recommended"],
        "candidate_peak_basis": projection["candidate_peak_basis"],
        "candidate_billable_demand_kw": projection["candidate_billable_demand_kw"],
    })


# ------------------------------------------------------- demand intervals -----

@bp.route("/utility-accounts/<account_id>/demand-intervals", methods=["POST"])
@roles(BMS_GATEWAY, ENERGY_ANALYST)
def ingest_intervals(account_id):
    body = v.body()
    if "intervals" not in body or body["intervals"] is None:
        v.bad("field 'intervals' is required")
    raw_intervals = body["intervals"]
    if not isinstance(raw_intervals, list) or len(raw_intervals) == 0:
        v.bad("field 'intervals' must be a non-empty array")
    parsed = []
    for index, element in enumerate(raw_intervals):
        if not isinstance(element, dict):
            v.bad("element %d of 'intervals' must be an object" % index)
        parsed.append({
            "interval_start_iso": v.get_dt(element, "interval_start_iso"),
            "kw_demand": v.get_num(element, "kw_demand", 1, ge=0),
            "is_on_peak": v.get_bool(element, "is_on_peak"),
            "is_dr_event_day": v.get_bool(element, "is_dr_event_day",
                                          required=False, default=False),
        })
    common.get_account(account_id)
    created = []
    for fields in parsed:
        fields["utility_account_id"] = account_id
        created.append(new_event_row(db.intervals, fields))
    return envelope.created([serial.interval(row) for row in created])


# ---------------------------------------------------------- tariff switch -----

@bp.route("/utility-accounts/<account_id>/tariff-switch", methods=["POST"])
@roles(ENERGY_MANAGER)
def tariff_switch(account_id):
    body = v.body()
    effective_from = v.get_dt(body, "effective_from_iso")
    expected_version = v.get_int(body, "expected_utility_account_version")
    account = common.get_account(account_id)
    if expected_version != account["version"]:
        raise ApiError("ERR_STALE_ACCOUNT_VERSION")
    locked_until = account["tariff_locked_until_iso"]
    if locked_until is not None and db.clock < locked_until:
        raise ApiError("ERR_TARIFF_LOCK_ACTIVE")
    if not effective_from > db.clock:
        raise ApiError("ERR_TARIFF_LOCK_ACTIVE")
    projection = calc.tariff_projection(account)
    if not projection["switch_recommended"]:
        raise ApiError("ERR_TARIFF_SWITCH_NOT_JUSTIFIED")
    account["tariff_state"] = "PENDING_SWITCH"
    account["tariff_switch_effective_from_iso"] = effective_from
    cascade.touch(account)
    return envelope.ok(serial.account(account))
