"""HedgeProgram lifecycle plus instrument proposal under a programme (PRD 3.3, 3.4)."""

from decimal import Decimal

from flask import Blueprint, g

import calc
import domain
import fetch
import serializers as ser
import validators as v
from calc import ZERO, r0, r2
from db import db, rows_in_order
from errors import fail
from middleware import (FUEL_ANALYST, FUEL_OPS_CONTROLLER, HEDGE_ACCOUNTANT,
                        RISK_POLICY_ADMIN, TREASURY_RISK_MANAGER, endpoint,
                        new_row, touch)
from response import created, ok, ok_list
from validators import month_after

bp = Blueprint("programs", __name__)

PROGRAM_STATUSES = ("DRAFT", "SIZING", "PENDING_APPROVAL", "ACTIVE", "CLOSED")
COMPLIANCE_POSTURES = ("COMPLIANT", "BREACH")
TRADE_STATUSES = ("PROPOSED", "EXECUTED", "SETTLED", "TERMINATED")
ACCOUNTING_STATUSES = ("UNDESIGNATED", "DESIGNATED", "DEDESIGNATED")


# ------------------------------------------------------------------- programmes

@bp.post("/fuel/hedge-programs")
@endpoint(FUEL_ANALYST)
def create_program():
    data = v.body()
    policy_id = v.get_string(data, "policy_id", min_len=1)
    program_code = v.get_string(data, "program_code", min_len=1, max_len=32)
    start = v.get_month(data, "period_start_month")
    end = v.get_month(data, "period_end_month")
    route_groups = v.get_enum_array(data, "route_groups", calc.ROUTE_GROUPS)
    target = v.get_number(data, "target_coverage_pct", exclusive_minimum=0,
                          maximum=100, places=2)

    if end < start:
        fail("ERR_INVALID_REQUEST",
             "period_end_month must not be earlier than period_start_month.")

    policy = fetch.policy(policy_id)

    for row in db.programs.values():
        if row["program_code"] == program_code:
            fail("ERR_DUPLICATE_PROGRAM_CODE",
                 "program_code %r is already in use." % program_code)

    row = new_row()
    row.update({
        "policy_id": policy["id"],
        "program_code": program_code,
        "period_start_month": start,
        "period_end_month": end,
        "route_groups": route_groups,
        "target_coverage_pct": target,
        "consumption_basis_gallons": r0(0),
        "designated_mtm_usd": r2(0),
        "undesignated_mtm_usd": r2(0),
        "compliance_posture": "COMPLIANT",
        "status": "DRAFT",
        "submitted_by_user_id": None,
        "return_count": 0,
    })
    db.programs[row["id"]] = row
    return created(ser.program(row))


@bp.get("/fuel/hedge-programs/<program_id>")
@endpoint(RISK_POLICY_ADMIN, FUEL_ANALYST, TREASURY_RISK_MANAGER,
          HEDGE_ACCOUNTANT, FUEL_OPS_CONTROLLER)
def read_program(program_id):
    return ok(ser.program(fetch.program(program_id)))


@bp.get("/fuel/hedge-programs")
@endpoint(RISK_POLICY_ADMIN, FUEL_ANALYST, TREASURY_RISK_MANAGER, HEDGE_ACCOUNTANT)
def list_programs():
    limit, offset = v.pagination()
    policy_id = v.raw_filter("policy_id")
    status = v.enum_filter("status", PROGRAM_STATUSES)
    posture = v.enum_filter("compliance_posture", COMPLIANCE_POSTURES)

    rows = rows_in_order(db.programs)
    if policy_id is not None:
        rows = [r for r in rows if r["policy_id"] == policy_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if posture is not None:
        rows = [r for r in rows if r["compliance_posture"] == posture]
    page, total = v.paginate(rows, limit, offset)
    return ok_list([ser.program(r) for r in page], limit, offset, total)


@bp.post("/fuel/hedge-programs/<program_id>/size")
@endpoint(FUEL_ANALYST)
def size_program(program_id):
    program = fetch.program(program_id)
    policy = domain.governing_policy(program)

    if program["status"] not in ("DRAFT", "SIZING"):
        fail("ERR_PROGRAM_INVALID_STATE",
             "Sizing is declared only from DRAFT and SIZING; this programme is %s."
             % program["status"])
    if program["status"] == "DRAFT" and (policy is None or policy["status"] != "ACTIVE"):
        fail("ERR_PROGRAM_INVALID_STATE",
             "The programme's bound policy must still be ACTIVE for a first sizing run.")

    eligible_fleets = policy["eligible_fleet_types"] if policy else []
    window_end = month_after(program["period_end_month"])

    matched = []
    for forecast in rows_in_order(db.forecasts):
        if forecast["status"] != "PUBLISHED":
            continue
        if forecast["fleet_type"] not in eligible_fleets:
            continue
        if forecast["route_group"] not in program["route_groups"]:
            continue
        if forecast["period_start_month"] < program["period_start_month"]:
            continue
        if forecast["period_end_month"] > window_end:
            continue
        matched.append(forecast)

    if not matched:
        fail("ERR_NO_FORECAST_BASIS",
             "No PUBLISHED forecast satisfies this programme's sizing basis.")

    total = ZERO
    for forecast in matched:
        total += forecast["forecast_gallons"] * calc.SEASON_FACTOR[forecast["season"]]

    program["consumption_basis_gallons"] = r0(total)
    program["status"] = "SIZING"
    touch(program)
    return ok(ser.program(program))


@bp.post("/fuel/hedge-programs/<program_id>/submit")
@endpoint(FUEL_ANALYST)
def submit_program(program_id):
    program = fetch.program(program_id)

    if program["status"] != "SIZING":
        fail("ERR_PROGRAM_INVALID_STATE",
             "Submission is declared only from SIZING; this programme is %s."
             % program["status"])
    if domain.program_coverage(program)["open_instrument_count"] < 1:
        fail("ERR_PROGRAM_INVALID_STATE",
             "A programme must carry at least one open instrument to be submitted.")

    program["status"] = "PENDING_APPROVAL"
    program["submitted_by_user_id"] = g.user_id
    touch(program)
    return ok(ser.program(program))


@bp.post("/fuel/hedge-programs/<program_id>/return")
@endpoint(TREASURY_RISK_MANAGER)
def return_program(program_id):
    data = v.body()
    v.get_string(data, "return_note", min_len=1)

    program = fetch.program(program_id)
    if program["status"] != "PENDING_APPROVAL":
        fail("ERR_PROGRAM_INVALID_STATE",
             "Return is declared only from PENDING_APPROVAL; this programme is %s."
             % program["status"])

    program["status"] = "SIZING"
    program["return_count"] = program["return_count"] + 1
    program["submitted_by_user_id"] = None
    touch(program)
    return ok(ser.program(program))


@bp.post("/fuel/hedge-programs/<program_id>/activate")
@endpoint(TREASURY_RISK_MANAGER)
def activate_program(program_id):
    program = fetch.program(program_id)

    if program["status"] != "PENDING_APPROVAL":
        fail("ERR_PROGRAM_INVALID_STATE",
             "Activation is declared only from PENDING_APPROVAL; this programme is %s."
             % program["status"])
    if program["submitted_by_user_id"] is not None \
            and g.user_id == program["submitted_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The user who submitted this programme may not activate it.")

    policy = domain.governing_policy(program)
    planned = domain.program_coverage(program)["planned_coverage_pct_delta"]
    floor = policy["min_coverage_pct"] if policy else ZERO
    if planned < floor:
        fail("ERR_COVERAGE_FLOOR_NOT_MET",
             "planned_coverage_pct_delta %s is below the policy floor %s."
             % (planned, floor))

    program["status"] = "ACTIVE"
    touch(program)
    return ok(ser.program(program))


@bp.post("/fuel/hedge-programs/<program_id>/close")
@endpoint(TREASURY_RISK_MANAGER)
def close_program(program_id):
    program = fetch.program(program_id)

    if program["status"] != "ACTIVE":
        fail("ERR_PROGRAM_INVALID_STATE",
             "Closure is declared only from ACTIVE; this programme is %s."
             % program["status"])
    if domain.program_coverage(program)["open_instrument_count"] != 0:
        fail("ERR_PROGRAM_HAS_OPEN_INSTRUMENTS",
             "Every instrument must be settled or terminated before closure.")

    program["status"] = "CLOSED"
    touch(program)
    return ok(ser.program(program))


# ------------------------------------------------------- instruments on the leg

def _instrument_shape(data):
    """Step 3 for a proposal, including the conditional strike fields."""
    counterparty_id = v.get_string(data, "counterparty_id", min_len=1)
    instrument_type = v.get_enum(data, "instrument_type", calc.INSTRUMENT_TYPES)
    notional = v.get_number(data, "notional_gallons", exclusive_minimum=0)
    maturity = v.get_month(data, "maturity_month")
    expected = v.get_int(data, "expected_hedge_program_version")

    strike = None
    cap = None
    floor = None
    if instrument_type == "COLLAR":
        if v.present(data, "strike_usd_per_gal"):
            fail("ERR_INVALID_REQUEST",
                 "Field 'strike_usd_per_gal' must be omitted for a COLLAR.")
        floor = v.get_number(data, "floor_strike_usd_per_gal",
                             exclusive_minimum=0, places=4)
        cap = v.get_number(data, "cap_strike_usd_per_gal", places=4)
        if cap <= floor:
            fail("ERR_INVALID_REQUEST",
                 "Field 'cap_strike_usd_per_gal' must exceed 'floor_strike_usd_per_gal'.")
    else:
        for name in ("cap_strike_usd_per_gal", "floor_strike_usd_per_gal"):
            if v.present(data, name):
                fail("ERR_INVALID_REQUEST",
                     "Field '%s' must be omitted for a %s." % (name, instrument_type))
        strike = v.get_number(data, "strike_usd_per_gal", exclusive_minimum=0, places=4)

    premium = v.get_number(data, "premium_usd", required=False, minimum=0,
                           places=2, default=r2(0))
    if instrument_type in ("SWAP", "COLLAR") and premium != 0:
        fail("ERR_INVALID_REQUEST",
             "Field 'premium_usd' must be 0 for a %s." % instrument_type)

    return {
        "counterparty_id": counterparty_id,
        "instrument_type": instrument_type,
        "notional_gallons": notional,
        "maturity_month": maturity,
        "expected": expected,
        "strike_usd_per_gal": strike,
        "cap_strike_usd_per_gal": cap,
        "floor_strike_usd_per_gal": floor,
        "premium_usd": premium,
    }


@bp.post("/fuel/hedge-programs/<program_id>/instruments")
@endpoint(FUEL_ANALYST)
def create_instrument(program_id):
    shape = _instrument_shape(v.body())

    program = fetch.program(program_id)

    maturity = shape["maturity_month"]
    if maturity < program["period_start_month"] or maturity > program["period_end_month"]:
        fail("ERR_INVALID_REQUEST",
             "Field 'maturity_month' must fall inside the programme's hedged window.")

    counterparty = fetch.counterparty(shape["counterparty_id"])

    if program["status"] not in ("SIZING", "PENDING_APPROVAL", "ACTIVE"):
        fail("ERR_PROGRAM_INVALID_STATE",
             "An instrument may only be proposed while the programme is SIZING, "
             "PENDING_APPROVAL or ACTIVE; this one is %s." % program["status"])

    if shape["expected"] != program["version"]:
        fail("ERR_STALE_VERSION",
             "expected_hedge_program_version %s does not match current version %s."
             % (shape["expected"], program["version"]))

    policy = domain.governing_policy(program)
    permitted = policy["permitted_instrument_types"] if policy else []
    if shape["instrument_type"] not in permitted:
        fail("ERR_INSTRUMENT_TYPE_NOT_PERMITTED",
             "instrument_type %s is not permitted by the governing policy."
             % shape["instrument_type"])

    delta = calc.INSTRUMENT_DELTA[shape["instrument_type"]]
    row = new_row()
    row.update({
        "hedge_program_id": program["id"],
        "counterparty_id": counterparty["id"],
        "instrument_type": shape["instrument_type"],
        "notional_gallons": shape["notional_gallons"],
        "strike_usd_per_gal": shape["strike_usd_per_gal"],
        "cap_strike_usd_per_gal": shape["cap_strike_usd_per_gal"],
        "floor_strike_usd_per_gal": shape["floor_strike_usd_per_gal"],
        "premium_usd": shape["premium_usd"],
        "maturity_month": maturity,
        "trade_status": "PROPOSED",
        "accounting_status": "UNDESIGNATED",
        "delta_factor": delta,
        "delta_adjusted_gallons": r2(shape["notional_gallons"] * delta),
        "mtm_value_usd": r2(0),
        "margin_requirement_usd": r2(0),
        "cumulative_hedge_change_usd": r2(0),
        "cumulative_item_change_usd": r2(0),
        "proposed_by_user_id": g.user_id,
        "executed_at": None,
        "designated_at": None,
    })
    db.instruments[row["id"]] = row
    touch(program)
    return created(ser.instrument(row))


@bp.get("/fuel/hedge-programs/<program_id>/instruments")
@endpoint(RISK_POLICY_ADMIN, FUEL_ANALYST, TREASURY_RISK_MANAGER, HEDGE_ACCOUNTANT)
def list_program_instruments(program_id):
    limit, offset = v.pagination()
    trade_status = v.enum_filter("trade_status", TRADE_STATUSES)
    accounting_status = v.enum_filter("accounting_status", ACCOUNTING_STATUSES)
    counterparty_id = v.raw_filter("counterparty_id")

    program = fetch.program(program_id)
    rows = domain.program_instruments(program["id"])
    if trade_status is not None:
        rows = [r for r in rows if r["trade_status"] == trade_status]
    if accounting_status is not None:
        rows = [r for r in rows if r["accounting_status"] == accounting_status]
    if counterparty_id is not None:
        rows = [r for r in rows if r["counterparty_id"] == counterparty_id]
    page, total = v.paginate(rows, limit, offset)
    return ok_list([ser.instrument(r) for r in page], limit, offset, total)
