"""Chargeback lines, the end-of-day sweep and the logical clock (PRD 3.9)."""
from flask import Blueprint

import calc
import clock
import errors
import response
import serializers
import services
import validation
from db import db, ordered, touch
from middleware import (ROLE_ADMIN, ROLE_CUSTOMER, ROLE_QUALITY, acting_user,
                        endpoint, is_customer, require_owner)

bp = Blueprint("money", __name__)

BASES = ("PACKAGE_LEAKER", "REPROCESS", "TAKE_OR_PAY_SHORTFALL")
CHARGEBACK_STATUSES = ("PENDING", "WAIVED")


@bp.post("/chargeback-lines/<row_id>/waive")
@endpoint([ROLE_ADMIN])
def waive_line(row_id):
    data = validation.body()
    waive_reason = validation.get_str(data, "waive_reason")

    row = services.find(db.chargeback_lines, row_id, "ERR_CHARGEBACK_LINE_NOT_FOUND")
    if row["status"] != "PENDING":
        raise errors.conflict("ERR_INVALID_CHARGEBACK_STATE",
                              "Only a PENDING chargeback line may be waived.")

    row["status"] = "WAIVED"
    row["waived_by_user_id"] = acting_user()
    row["waive_reason"] = waive_reason
    touch(row)
    services.recompute_customer_balance(db.customers.get(row["customer_id"]))
    return response.object_response(serializers.plain(row))


@bp.get("/chargeback-lines/<row_id>")
@endpoint([ROLE_ADMIN, ROLE_QUALITY, ROLE_CUSTOMER])
def get_line(row_id):
    row = services.find(db.chargeback_lines, row_id, "ERR_CHARGEBACK_LINE_NOT_FOUND")
    require_owner(row["customer_id"])
    return response.object_response(serializers.plain(row))


@bp.get("/chargeback-lines")
@endpoint([ROLE_ADMIN, ROLE_QUALITY, ROLE_CUSTOMER])
def list_lines():
    limit, offset = validation.pagination()
    customer_id = validation.qs_str("customer_id")
    cycle_load_id = validation.qs_str("cycle_load_id")
    contract_id = validation.qs_str("contract_id")
    deviation_id = validation.qs_str("deviation_id")
    basis = validation.qs_enum("basis", BASES)
    status = validation.qs_enum("status", CHARGEBACK_STATUSES)

    rows = []
    for row in db.chargeback_lines.values():
        if customer_id is not None and row["customer_id"] != customer_id:
            continue
        if cycle_load_id is not None and row["cycle_load_id"] != cycle_load_id:
            continue
        if contract_id is not None and row["contract_id"] != contract_id:
            continue
        if deviation_id is not None and row["deviation_id"] != deviation_id:
            continue
        if basis is not None and row["basis"] != basis:
            continue
        if status is not None and row["status"] != status:
            continue
        if is_customer() and row["customer_id"] != acting_user():
            continue
        rows.append(row)
    return response.page(ordered(rows), serializers.plain, limit, offset)


# ------------------------------------------------------------ operational sweep
@bp.post("/operations/day-close")
@endpoint([ROLE_ADMIN])
def day_close():
    now = clock.now()

    expired = 0
    for row in ordered(list(db.qualifications.values())):
        if (row["status"] == "QUALIFIED" and row["expires_at"] is not None
                and row["expires_at"] <= now):
            row["status"] = "EXPIRED"
            touch(row)
            expired += 1

    window_start = clock.plus_days(now, -calc.TRAILING_WINDOW_DAYS)
    rescored = 0
    for customer in ordered(list(db.customers.values())):
        leakers = 0
        inspected = 0
        for load in db.loads.values():
            if load["inspection_state"] != "INSPECTED":
                continue
            lot = services.lot_of(load)
            if lot is None or lot["customer_id"] != customer["id"]:
                continue
            cycle = db.cycles.get(load["cycle_id"])
            if cycle is None or cycle["dispositioned_at"] is None:
                continue
            if not (window_start <= cycle["dispositioned_at"] <= now):
                continue
            leakers += int(load["leaker_units"] or 0)
            inspected += int(load["units_inspected"] or 0)
        ppm = calc.pooled_ppm(leakers, inspected) if inspected else 0
        if customer["trailing_leaker_ppm"] != ppm:
            customer["trailing_leaker_ppm"] = ppm
            touch(customer)
        rescored += 1

    return response.object_response({
        "expired_qualification_count": expired,
        "customers_rescored": rescored,
        "closed_at": clock.fmt(now),
    })


# --------------------------------------------------------------- logical clock
@bp.post("/_clock/set_current_utc")
@endpoint([ROLE_ADMIN])
def set_clock():
    data = validation.body()
    current_utc = validation.get_datetime(data, "current_utc")
    clock.set_now(current_utc)
    return response.object_response({"current_utc": clock.fmt(current_utc)})
