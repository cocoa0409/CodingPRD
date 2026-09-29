"""Cycle loads: post-cycle package inspection and the leaker chargeback (PRD 3.8)."""
from decimal import Decimal

from flask import Blueprint

import calc
import errors
import response
import serializers
import services
import validation
from db import db, insert, ordered, touch
from middleware import (ROLE_ADMIN, ROLE_CUSTOMER, ROLE_QUALITY, ROLE_SCHEDULER,
                        acting_user, endpoint, is_customer, require_owner)

bp = Blueprint("loads", __name__)

INSPECTION_STATES = ("PENDING_INSPECTION", "INSPECTED")
DISPOSITION_STATES = ("PENDING", "ALLOCATED", "REPROCESSED", "REJECTED", "VOIDED")


@bp.post("/cycle-loads/<row_id>/inspection")
@endpoint([ROLE_QUALITY])
def record_inspection(row_id):
    data = validation.body()
    units_inspected = validation.get_int(data, "units_inspected", exclusive_minimum=0)
    leaker_units = validation.get_int(data, "leaker_units", minimum=0)

    load = services.find(db.loads, row_id, "ERR_CYCLE_LOAD_NOT_FOUND")
    cycle = db.cycles.get(load["cycle_id"])
    if cycle is None or cycle["state"] != "DISPOSITIONED":
        raise errors.conflict("ERR_CYCLE_NOT_DISPOSITIONED",
                              "Package inspection is gated behind cycle disposition.")
    if load["inspection_state"] == "INSPECTED":
        raise errors.conflict("ERR_LOAD_ALREADY_INSPECTED",
                              "This load has already been inspected.")
    if leaker_units > units_inspected:
        raise errors.unprocessable("ERR_LEAKERS_EXCEED_INSPECTED",
                                   "'leaker_units' cannot exceed 'units_inspected'.")

    lot = services.lot_of(load)
    customer = db.customers.get(lot["customer_id"]) if lot else None
    trailing = customer["trailing_leaker_ppm"] if customer else 0

    ppm = calc.leaker_ppm(leaker_units, units_inspected)
    party = calc.decide_chargeback_party(ppm, trailing)

    load["units_inspected"] = units_inspected
    load["leaker_units"] = leaker_units
    load["leaker_ppm"] = ppm
    load["chargeback_party"] = party

    if party == "CUSTOMER":
        amount = calc.leaker_chargeback_cents(ppm, leaker_units,
                                              load["allocated_fee_cents"])
        load["chargeback_cents"] = amount
        insert(db.chargeback_lines, {
            "customer_id": customer["id"],
            "cycle_load_id": load["id"],
            "contract_id": None,
            "deviation_id": None,
            "basis": "PACKAGE_LEAKER",
            "amount_cents": amount,
            "status": "PENDING",
            "waived_by_user_id": None,
            "waive_reason": None,
        })
        services.recompute_customer_balance(customer)
    else:
        load["chargeback_cents"] = 0

    if ppm >= calc.LEAKER_CHARGEBACK_PPM:
        insert(db.deviations, {
            "cycle_id": cycle["id"],
            "cycle_log_id": None,
            "cycle_load_id": load["id"],
            "deviation_type": "PACKAGE_FAILURE_RATE",
            "severity": "MAJOR",
            "worst_shortfall_pct": Decimal("0.00"),
            "status": "OPEN",
            "root_cause_code": None,
            "chargeback_party": None,
            "adjudicated_by_user_id": None,
            "adjudicated_at": None,
        })

    load["inspection_state"] = "INSPECTED"
    touch(load)
    return response.object_response(serializers.plain(load))


@bp.get("/cycle-loads/<row_id>")
@endpoint([ROLE_QUALITY, ROLE_SCHEDULER, ROLE_ADMIN, ROLE_CUSTOMER])
def get_load(row_id):
    load = services.find(db.loads, row_id, "ERR_CYCLE_LOAD_NOT_FOUND")
    require_owner(services.customer_of_load(load))
    return response.object_response(serializers.plain(load))


@bp.get("/cycle-loads")
@endpoint([ROLE_QUALITY, ROLE_SCHEDULER, ROLE_ADMIN, ROLE_CUSTOMER])
def list_loads():
    limit, offset = validation.pagination()
    cycle_id = validation.qs_str("cycle_id")
    lot_id = validation.qs_str("lot_id")
    contract_id = validation.qs_str("contract_id")
    inspection_state = validation.qs_enum("inspection_state", INSPECTION_STATES)
    disposition_state = validation.qs_enum("disposition_state", DISPOSITION_STATES)

    rows = []
    for row in db.loads.values():
        if cycle_id is not None and row["cycle_id"] != cycle_id:
            continue
        if lot_id is not None and row["lot_id"] != lot_id:
            continue
        if contract_id is not None and row["contract_id"] != contract_id:
            continue
        if inspection_state is not None and row["inspection_state"] != inspection_state:
            continue
        if (disposition_state is not None
                and row["disposition_state"] != disposition_state):
            continue
        if is_customer() and services.customer_of_load(row) != acting_user():
            continue
        rows.append(row)
    return response.page(ordered(rows), serializers.plain, limit, offset)
