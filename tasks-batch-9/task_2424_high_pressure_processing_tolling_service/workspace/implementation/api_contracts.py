"""Seasonal capacity contracts and the slot ledger (PRD 3.3)."""
from flask import Blueprint

import calc
import errors
import response
import serializers
import services
import validation
from db import db, insert, ordered, touch
from middleware import (ROLE_ADMIN, ROLE_CUSTOMER, ROLE_SCHEDULER, acting_user,
                        endpoint, is_customer, require_owner)

bp = Blueprint("contracts", __name__)

CONTRACT_STATUSES = ("DRAFT", "ACTIVE", "EXHAUSTED", "CLOSED")


@bp.post("/capacity-contracts")
@endpoint([ROLE_ADMIN])
def create_contract():
    data = validation.body()
    customer_id = validation.get_id(data, "customer_id")
    season_code = validation.get_str(data, "season_code")
    window_start = validation.get_datetime(data, "window_start")
    window_end = validation.get_datetime(data, "window_end")
    committed_slots = validation.get_int(data, "committed_slots", exclusive_minimum=0)
    slot_take_or_pay_cents = validation.get_int(data, "slot_take_or_pay_cents",
                                                minimum=0)
    priority_rank = validation.get_int(data, "priority_rank", minimum=1)
    peak_window_start = validation.get_datetime(data, "peak_window_start")
    peak_window_end = validation.get_datetime(data, "peak_window_end")
    peak_multiplier = validation.get_num(data, "peak_multiplier", minimum=1.0)
    if window_end <= window_start:
        raise errors.invalid_request("'window_end' must be later than 'window_start'.")

    services.find(db.customers, customer_id, "ERR_CUSTOMER_NOT_FOUND")

    for row in db.contracts.values():
        if row["customer_id"] == customer_id and row["season_code"] == season_code:
            raise errors.conflict("ERR_DUPLICATE_CONTRACT_SEASON",
                                  "That customer already has a contract for this "
                                  "season.")

    row = insert(db.contracts, {
        "customer_id": customer_id,
        "season_code": season_code,
        "window_start": window_start,
        "window_end": window_end,
        "committed_slots": committed_slots,
        "slot_take_or_pay_cents": slot_take_or_pay_cents,
        "priority_rank": priority_rank,
        "peak_window_start": peak_window_start,
        "peak_window_end": peak_window_end,
        "peak_multiplier": peak_multiplier,
        "reserved_slots": 0,
        "consumed_slots": 0,
        "available_slots": committed_slots,
        "shortfall_slots": 0,
        "take_or_pay_cents": 0,
        "status": "DRAFT",
    })
    return response.created(serializers.contract(row))


@bp.post("/capacity-contracts/<row_id>/activate")
@endpoint([ROLE_ADMIN])
def activate_contract(row_id):
    row = services.find(db.contracts, row_id, "ERR_CONTRACT_NOT_FOUND")
    if row["status"] != "DRAFT":
        raise errors.conflict("ERR_INVALID_CONTRACT_STATE",
                              "Only a DRAFT contract may be activated.")
    row["status"] = "ACTIVE"
    row["reserved_slots"] = 0
    row["consumed_slots"] = 0
    row["available_slots"] = row["committed_slots"]
    touch(row)
    return response.object_response(serializers.contract(row))


@bp.post("/capacity-contracts/<row_id>/close")
@endpoint([ROLE_ADMIN])
def close_contract(row_id):
    row = services.find(db.contracts, row_id, "ERR_CONTRACT_NOT_FOUND")
    if row["status"] not in ("ACTIVE", "EXHAUSTED"):
        raise errors.conflict("ERR_INVALID_CONTRACT_STATE",
                              "Only an ACTIVE or EXHAUSTED contract may be closed.")

    ledger = services.contract_ledger(row)
    row.update(ledger)
    shortfall_slots, take_or_pay_cents = calc.take_or_pay(
        row["committed_slots"], ledger["consumed_slots"], row["slot_take_or_pay_cents"])
    row["shortfall_slots"] = shortfall_slots
    row["take_or_pay_cents"] = take_or_pay_cents

    if take_or_pay_cents > 0:
        insert(db.chargeback_lines, {
            "customer_id": row["customer_id"],
            "cycle_load_id": None,
            "contract_id": row["id"],
            "deviation_id": None,
            "basis": "TAKE_OR_PAY_SHORTFALL",
            "amount_cents": take_or_pay_cents,
            "status": "PENDING",
            "waived_by_user_id": None,
            "waive_reason": None,
        })
        services.recompute_customer_balance(db.customers.get(row["customer_id"]))

    row["status"] = "CLOSED"
    touch(row)
    return response.object_response(serializers.contract(row))


@bp.get("/capacity-contracts/<row_id>")
@endpoint([ROLE_ADMIN, ROLE_CUSTOMER, ROLE_SCHEDULER])
def get_contract(row_id):
    row = services.find(db.contracts, row_id, "ERR_CONTRACT_NOT_FOUND")
    require_owner(row["customer_id"])
    return response.object_response(serializers.contract(row))


@bp.get("/capacity-contracts")
@endpoint([ROLE_ADMIN, ROLE_CUSTOMER, ROLE_SCHEDULER])
def list_contracts():
    limit, offset = validation.pagination()
    customer_id = validation.qs_str("customer_id")
    season_code = validation.qs_str("season_code")
    status = validation.qs_enum("status", CONTRACT_STATUSES)

    rows = []
    for row in db.contracts.values():
        if customer_id is not None and row["customer_id"] != customer_id:
            continue
        if season_code is not None and row["season_code"] != season_code:
            continue
        if status is not None and row["status"] != status:
            continue
        if is_customer() and row["customer_id"] != acting_user():
            continue
        rows.append(row)
    return response.page(ordered(rows), serializers.contract, limit, offset)
