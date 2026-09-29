"""PolicyException endpoints (PRD 3.9)."""

from flask import Blueprint, g

import calc
import domain
import fetch
import serializers as ser
import validators as v
from db import db, now_iso, rows_in_order
from errors import fail
from middleware import (FUEL_ANALYST, FUEL_OPS_CONTROLLER, HEDGE_ACCOUNTANT,
                        RISK_POLICY_ADMIN, TREASURY_RISK_MANAGER, endpoint,
                        new_row, touch)
from response import created, ok, ok_list

bp = Blueprint("exceptions", __name__)

EXCEPTION_STATUSES = ("REQUESTED", "APPROVED", "DENIED")
EXCEPTION_ORIGINS = ("MANUAL", "SYSTEM_BREACH")


def _touch_governing_policy(exception):
    program_id = exception.get("hedge_program_id")
    if not program_id:
        return
    program = db.programs.get(program_id)
    if program is None:
        return
    policy = domain.governing_policy(program)
    if policy is not None:
        touch(policy)


@bp.post("/fuel/policy-exceptions")
@endpoint(FUEL_ANALYST, TREASURY_RISK_MANAGER, HEDGE_ACCOUNTANT, FUEL_OPS_CONTROLLER)
def create_exception():
    data = v.body()
    reason_code = v.get_enum(data, "reason_code", calc.REASON_CODES)
    justification = v.get_string(data, "justification", min_len=10, max_len=500)
    program_id = v.get_string(data, "hedge_program_id", required=False)
    instrument_id = v.get_string(data, "hedge_instrument_id", required=False)
    directive_id = v.get_string(data, "tankering_directive_id", required=False)
    limit_value = v.get_number(data, "requested_limit_value", required=False)

    program = fetch.program(program_id) if program_id is not None else None
    instrument = fetch.instrument(instrument_id) if instrument_id is not None else None
    directive = fetch.directive(directive_id) if directive_id is not None else None

    row = new_row()
    row.update({
        "reason_code": reason_code,
        "hedge_program_id": program["id"] if program else None,
        "hedge_instrument_id": instrument["id"] if instrument else None,
        "tankering_directive_id": directive["id"] if directive else None,
        "justification": justification,
        "requested_limit_value": limit_value,
        "status": "REQUESTED",
        "origin": "MANUAL",
        "requested_by_user_id": g.user_id,
        "decided_by_user_id": None,
        "decided_at": None,
    })
    db.exceptions[row["id"]] = row
    _touch_governing_policy(row)
    return created(ser.exception(row))


@bp.get("/fuel/policy-exceptions/<exception_id>")
@endpoint(RISK_POLICY_ADMIN, FUEL_ANALYST, TREASURY_RISK_MANAGER,
          HEDGE_ACCOUNTANT, FUEL_OPS_CONTROLLER)
def read_exception(exception_id):
    return ok(ser.exception(fetch.exception(exception_id)))


@bp.get("/fuel/policy-exceptions")
@endpoint(RISK_POLICY_ADMIN, FUEL_ANALYST, TREASURY_RISK_MANAGER,
          HEDGE_ACCOUNTANT, FUEL_OPS_CONTROLLER)
def list_exceptions():
    limit, offset = v.pagination()
    program_id = v.raw_filter("hedge_program_id")
    instrument_id = v.raw_filter("hedge_instrument_id")
    directive_id = v.raw_filter("tankering_directive_id")
    status = v.enum_filter("status", EXCEPTION_STATUSES)
    reason_code = v.enum_filter("reason_code", calc.REASON_CODES)
    origin = v.enum_filter("origin", EXCEPTION_ORIGINS)

    rows = rows_in_order(db.exceptions)
    if program_id is not None:
        rows = [r for r in rows if r["hedge_program_id"] == program_id]
    if instrument_id is not None:
        rows = [r for r in rows if r["hedge_instrument_id"] == instrument_id]
    if directive_id is not None:
        rows = [r for r in rows if r["tankering_directive_id"] == directive_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if reason_code is not None:
        rows = [r for r in rows if r["reason_code"] == reason_code]
    if origin is not None:
        rows = [r for r in rows if r["origin"] == origin]
    page, total = v.paginate(rows, limit, offset)
    return ok_list([ser.exception(r) for r in page], limit, offset, total)


def _decide(exception_id, new_status):
    data = v.body()
    v.get_string(data, "decision_note", min_len=1)

    row = fetch.exception(exception_id)
    if row["status"] != "REQUESTED":
        fail("ERR_EXCEPTION_INVALID_STATE",
             "Only a REQUESTED exception may be decided; this one is %s." % row["status"])
    if row["requested_by_user_id"] is not None \
            and g.user_id == row["requested_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The requester of an exception may not decide it.")

    row["status"] = new_status
    row["decided_by_user_id"] = g.user_id
    row["decided_at"] = now_iso()
    touch(row)
    _touch_governing_policy(row)
    return ok(ser.exception(row))


@bp.post("/fuel/policy-exceptions/<exception_id>/approve")
@endpoint(RISK_POLICY_ADMIN)
def approve_exception(exception_id):
    return _decide(exception_id, "APPROVED")


@bp.post("/fuel/policy-exceptions/<exception_id>/deny")
@endpoint(RISK_POLICY_ADMIN)
def deny_exception(exception_id):
    return _decide(exception_id, "DENIED")
