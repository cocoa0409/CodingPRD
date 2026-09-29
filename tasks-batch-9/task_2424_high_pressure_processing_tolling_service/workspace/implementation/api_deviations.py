"""Deviation adjudication and its three cascades (PRD 3.7)."""
from flask import Blueprint

import api_cycles
import calc
import clock
import errors
import response
import serializers
import services
import validation
from db import db, insert, ordered, touch
from middleware import (ROLE_ADMIN, ROLE_CUSTOMER, ROLE_OPERATOR, ROLE_QUALITY,
                        acting_user, endpoint)

bp = Blueprint("deviations", __name__)

DISPOSITIONS = ("ACCEPT", "REPROCESS", "REJECT")
DEVIATION_TYPES = ("UNDER_PRESSURE", "SHORT_HOLD", "TEMP_EXCURSION",
                   "PACKAGE_FAILURE_RATE")
SEVERITIES = ("MAJOR", "CRITICAL")
DEVIATION_STATUSES = ("OPEN", "ADJUDICATED_ACCEPT", "ADJUDICATED_REPROCESS",
                      "ADJUDICATED_REJECT")
ROOT_CAUSE_PATTERN = r"(EQUIP|PKG|OPS)_[A-Z0-9_]{2,20}"


@bp.post("/deviations/<row_id>/adjudicate")
@endpoint([ROLE_QUALITY])
def adjudicate(row_id):
    data = validation.body()
    disposition = validation.get_enum(data, "disposition", DISPOSITIONS)
    root_cause_code = validation.get_str(data, "root_cause_code",
                                         pattern=ROOT_CAUSE_PATTERN)

    deviation = services.find(db.deviations, row_id, "ERR_DEVIATION_NOT_FOUND")
    if deviation["status"] != "OPEN":
        raise errors.conflict("ERR_INVALID_DEVIATION_STATE",
                              "Only an OPEN deviation may be adjudicated.")

    if deviation["cycle_log_id"] is not None:
        log = db.cycle_logs.get(deviation["cycle_log_id"])
        if log is not None and log["logged_by_user_id"] == acting_user():
            raise errors.forbidden("ERR_SEGREGATION_OF_DUTIES",
                                   "The operator who logged the control-point record "
                                   "may not adjudicate its deviation.")

    if disposition == "ACCEPT" and deviation["severity"] == "CRITICAL":
        raise errors.unprocessable("ERR_DEVIATION_ACCEPT_NOT_PERMITTED",
                                   "A CRITICAL deviation may never be accepted.")
    if disposition in ("REPROCESS", "REJECT") and deviation["cycle_load_id"] is not None:
        raise errors.unprocessable("ERR_DEVIATION_DISPOSITION_NOT_PERMITTED",
                                   "A package-failure deviation can only be accepted.")

    party = "CUSTOMER" if root_cause_code.startswith("PKG_") else "FACILITY"
    deviation["root_cause_code"] = root_cause_code
    deviation["chargeback_party"] = party
    deviation["adjudicated_by_user_id"] = acting_user()
    deviation["adjudicated_at"] = clock.now()
    deviation["status"] = "ADJUDICATED_" + disposition
    touch(deviation)

    cycle = db.cycles.get(deviation["cycle_id"])
    if disposition == "REPROCESS":
        _reprocess(deviation, cycle, party)
    elif disposition == "REJECT":
        _reject(cycle)

    return response.object_response(serializers.plain(deviation))


def _reprocess(deviation, cycle, party):
    if cycle is None or cycle["state"] != "COMPLETED_DEVIATED":
        return
    loads = api_cycles.complete_disposition(cycle, reprocessed=True)

    customers = set()
    for load in loads:
        lot = services.lot_of(load)
        if party == "CUSTOMER" and lot is not None:
            insert(db.chargeback_lines, {
                "customer_id": lot["customer_id"],
                "cycle_load_id": load["id"],
                "contract_id": None,
                "deviation_id": deviation["id"],
                "basis": "REPROCESS",
                "amount_cents": calc.reprocess_chargeback_cents(
                    load["allocated_fee_cents"]),
                "status": "PENDING",
                "waived_by_user_id": None,
                "waive_reason": None,
            })
            customers.add(lot["customer_id"])
        if lot is None:
            continue
        lot["custody_state"] = "IN_COLD_STORAGE"
        services.move_units(lot, "units_treated", "units_untreated",
                            lot["units_treated"])
        if lot["release_state"] == "ON_HOLD_FOR_TEST":
            lot["release_state"] = "NOT_RELEASED"
            lot["hold_reason"] = None
        touch(lot)

    for customer_id in customers:
        services.recompute_customer_balance(db.customers.get(customer_id))


def _reject(cycle):
    if cycle is None or cycle["state"] != "COMPLETED_DEVIATED":
        return
    loads = services.pending_loads(cycle["id"])

    cycle["actual_tolling_fee_cents"] = 0
    cycle["state"] = "DISPOSITIONED"
    cycle["dispositioned_at"] = clock.now()
    touch(cycle)

    rooms = []
    for load in loads:
        load["allocated_fee_cents"] = 0
        load["disposition_state"] = "REJECTED"
        touch(load)
        lot = services.lot_of(load)
        if lot is None:
            continue
        services.move_units(lot, "units_treated", "units_disposed",
                            lot["units_treated"])
        lot["custody_state"] = "DISPOSED"
        if lot["release_state"] == "ON_HOLD_FOR_TEST":
            lot["release_state"] = "REJECTED"
        touch(lot)
        room = services.room_of_lot(lot)
        if room is not None and room not in rooms:
            rooms.append(room)

    for room in rooms:
        services.recompute_room(room)
    services.recompute_contracts_of(loads)


@bp.get("/deviations/<row_id>")
@endpoint([ROLE_QUALITY, ROLE_ADMIN, ROLE_OPERATOR, ROLE_CUSTOMER])
def get_deviation(row_id):
    row = services.find(db.deviations, row_id, "ERR_DEVIATION_NOT_FOUND")
    return response.object_response(serializers.plain(row))


@bp.get("/deviations")
@endpoint([ROLE_QUALITY, ROLE_ADMIN, ROLE_OPERATOR, ROLE_CUSTOMER])
def list_deviations():
    limit, offset = validation.pagination()
    cycle_id = validation.qs_str("cycle_id")
    cycle_log_id = validation.qs_str("cycle_log_id")
    cycle_load_id = validation.qs_str("cycle_load_id")
    deviation_type = validation.qs_enum("deviation_type", DEVIATION_TYPES)
    severity = validation.qs_enum("severity", SEVERITIES)
    status = validation.qs_enum("status", DEVIATION_STATUSES)

    rows = []
    for row in db.deviations.values():
        if cycle_id is not None and row["cycle_id"] != cycle_id:
            continue
        if cycle_log_id is not None and row["cycle_log_id"] != cycle_log_id:
            continue
        if cycle_load_id is not None and row["cycle_load_id"] != cycle_load_id:
            continue
        if deviation_type is not None and row["deviation_type"] != deviation_type:
            continue
        if severity is not None and row["severity"] != severity:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return response.page(ordered(rows), serializers.plain, limit, offset)
