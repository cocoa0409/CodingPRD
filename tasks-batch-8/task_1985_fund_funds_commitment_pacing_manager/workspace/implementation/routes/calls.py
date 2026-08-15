"""CapitalCall endpoints: issue, pay, cancel."""

from flask import Blueprint, request

import db
from db import STORE, new_entity, touch, public
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_COMMITMENT_NOT_EXECUTED,
    ERR_OVERFUNDED, ERR_BUFFER_BREACH, ERR_CALL_OVERDUE, ERR_POSTURE_GATED,
)  # ERR_COMMITMENT_NOT_EXECUTED still used by pay_call
from middleware import auth_context, require_role, ALL_ROLES
from response import ok, list_response
from services import domain
from util import dec, parse_datetime
from validate import body, req_positive_num, req_enum, req_datetime

bp = Blueprint("calls", __name__)

PURPOSES = ["INVESTMENT", "FEES", "EXPENSES"]


def get_program_or_404(pid):
    prog = STORE.programs.get(pid)
    if prog is None:
        raise_err(ERR_NOT_FOUND, "program id does not exist")
    return prog


def get_commitment_or_404(pid, cid):
    c = STORE.commitments.get(cid)
    if c is None or c["program_id"] != pid:
        raise_err(ERR_NOT_FOUND, "commitment id does not exist")
    return c


def get_call_or_404(call_id):
    c = STORE.calls.get(call_id)
    if c is None:
        raise_err(ERR_NOT_FOUND, "capital call id does not exist")
    return c


@bp.route("/fof/programs/<pid>/commitments/<cid>/calls", methods=["POST"])
def issue_call(pid, cid):
    _, role = auth_context()
    require_role(role, ["OperationsAnalyst"])
    prog = get_program_or_404(pid)
    get_commitment_or_404(pid, cid)
    if prog["posture"] == "FROZEN":
        raise_err(ERR_POSTURE_GATED, "program posture is FROZEN")
    # PRD 3.5: calls may be issued ahead of execution; the EXECUTED gate
    # applies to pay, not to issue.
    data = body()
    amount = req_positive_num(data, "amount")
    purpose = req_enum(data, "purpose", PURPOSES)
    due_date = req_datetime(data, "due_date")
    issued_on = db.now()
    if not (due_date > issued_on):
        raise_err(ERR_CALL_OVERDUE,
                  "due_date must be strictly after issued_on")
    prior = [c for c in STORE.calls.values() if c["commitment_id"] == cid]
    call_number = max((c["call_number"] for c in prior), default=0) + 1
    call = new_entity(STORE.calls, {
        "commitment_id": cid,
        "program_id": pid,
        "call_number": call_number,
        "amount": amount,
        "purpose": purpose,
        "issued_on": db.iso(issued_on),
        "due_date": db.iso(due_date),
        "status": "ISSUED",
        "paid_at": None,
    })
    return ok(public(call), status=201)


@bp.route("/fof/programs/<pid>/commitments/<cid>/calls", methods=["GET"])
def list_calls(pid, cid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    get_program_or_404(pid)
    get_commitment_or_404(pid, cid)
    rows = [c for c in STORE.calls.values() if c["commitment_id"] == cid]
    return list_response(rows, filters={"status": request.args.get("status")})


@bp.route("/fof/calls/<call_id>", methods=["GET"])
def get_call(call_id):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    return ok(public(get_call_or_404(call_id)))


@bp.route("/fof/calls/<call_id>/pay", methods=["POST"])
def pay_call(call_id):
    _, role = auth_context()
    require_role(role, ["OperationsAnalyst"])
    call = get_call_or_404(call_id)
    if call["status"] not in ("ISSUED", "OVERDUE"):
        raise_err(ERR_INVALID_STATE, "call is not ISSUED or OVERDUE")
    commitment = STORE.commitments.get(call["commitment_id"])
    prog = STORE.programs.get(call["program_id"])
    if commitment is None or commitment["status"] != "EXECUTED":
        raise_err(ERR_COMMITMENT_NOT_EXECUTED,
                  "commitment must be EXECUTED")
    if dec(call["amount"]) > dec(commitment["unfunded_amount"]):
        raise_err(ERR_OVERFUNDED,
                  "call amount exceeds commitment unfunded_amount")
    if prog is not None and (
            dec(prog["unrestricted_cash"]) - dec(call["amount"])
            < dec(prog["liquidity_buffer_min"])):
        raise_err(ERR_BUFFER_BREACH,
                  "payment would leave unrestricted_cash below the buffer")
    call["status"] = "PAID"
    call["paid_at"] = db.now_iso()
    touch(call)
    commitment["unfunded_amount"] = float(
        domain.money2_dec(dec(commitment["unfunded_amount"]) - dec(call["amount"])))
    touch(commitment)
    domain.append_ledger(prog, "CAPITAL_CALL_PAYMENT", -dec(call["amount"]),
                         ref_entity="CapitalCall", ref_id=call["id"])
    return ok(public(call))


@bp.route("/fof/calls/<call_id>/cancel", methods=["POST"])
def cancel_call(call_id):
    _, role = auth_context()
    require_role(role, ["OperationsAnalyst"])
    call = get_call_or_404(call_id)
    if call["status"] != "ISSUED":
        raise_err(ERR_INVALID_STATE, "call is not ISSUED")
    due = parse_datetime(call["due_date"])
    if due is not None and db.now() > due:
        raise_err(ERR_CALL_OVERDUE,
                  "call may be cancelled only at or before its due_date")
    call["status"] = "CANCELLED"
    touch(call)
    return ok(public(call))
