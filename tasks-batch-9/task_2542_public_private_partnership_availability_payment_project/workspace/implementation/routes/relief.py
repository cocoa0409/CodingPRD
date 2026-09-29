"""Relief/compensation/change-in-law claims and the lifecycle reserve ledger."""

from flask import Blueprint

import calc
from db import db, insert, public, setf
from errors import fail
from middleware import (ROLE_AUTHORITY_OFFICER, ROLE_CONCESSIONAIRE, ROLE_PLATFORM_ADMIN,
                        body, concession_of, get_claim, get_concession, get_txn,
                        owner_guard, req_enum, req_instant, req_int, req_str,
                        require_auth, role)
from response import created, ok

bp = Blueprint("relief", __name__)

CLAIM_TYPES = ("RELIEF_EVENT", "COMPENSATION_EVENT", "CHANGE_IN_LAW")
APPENDABLE_TXN_TYPES = ("CONTRIBUTION", "WITHDRAWAL", "HANDBACK_TOPUP")
ALL_TXN_TYPES = ("CONTRIBUTION", "WITHDRAWAL", "HANDBACK_TOPUP", "REVERSAL")


# ------------------------------------------------------------------ claims
@bp.post("/ppp/concessions/<row_id>/relief-claims")
def create_claim(row_id):
    require_auth(ROLE_CONCESSIONAIRE)
    concession = get_concession(row_id)
    owner_guard(concession)
    data = body()
    claim_type = req_enum(data, "claim_type", CLAIM_TYPES)
    raw_start, start_dt = req_instant(data, "event_start")
    raw_end, end_dt = req_instant(data, "event_end")
    claimed_days = req_int(data, "claimed_relief_days", minimum=0)
    claimed_cost = req_int(data, "claimed_cost_cents", minimum=0)

    calc.relief_notification_guard(start_dt)
    if end_dt.date() < start_dt.date():
        fail("ERR_INVALID_INTERVAL")
    calc.relief_window_conflict_guard(concession["id"], claim_type, start_dt, end_dt)

    row = insert("claims", {
        "concession_id": concession["id"],
        "claim_type": claim_type,
        "event_start": raw_start,
        "event_end": raw_end,
        "notified_at": db.now_str(),
        "claimed_relief_days": claimed_days,
        "claimed_cost_cents": claimed_cost,
        "granted_relief_days": 0,
        "granted_cost_cents": 0,
        "status": "NOTIFIED",
        "determined_at": None,
        "determination_note": None,
    })
    return created(public(row))


@bp.post("/ppp/relief-claims/<row_id>/determine")
def determine_claim(row_id):
    require_auth(ROLE_AUTHORITY_OFFICER)
    claim = get_claim(row_id)
    concession = concession_of(claim)
    data = body()
    decision = req_enum(data, "decision", ("GRANT", "REJECT"))
    granted_days = req_int(data, "granted_relief_days", minimum=0, required=False, default=0)
    granted_cost = req_int(data, "granted_cost_cents", minimum=0, required=False, default=0)
    note = req_str(data, "determination_note", max_len=2000, required=False)
    if claim["status"] != "NOTIFIED":
        fail("ERR_INVALID_STATE_TRANSITION")

    if decision == "GRANT":
        budget = calc.granted_relief_days_total(concession["id"]) + granted_days
        if budget > calc.RELIEF_DAYS_ANNUAL_CAP:
            fail("ERR_RELIEF_DAYS_CAP_EXCEEDED")
        if (granted_days > claim["claimed_relief_days"]
                or granted_cost > claim["claimed_cost_cents"]):
            fail("ERR_GRANT_EXCEEDS_CLAIM")
        setf(claim, "granted_relief_days", granted_days)
        setf(claim, "granted_cost_cents", granted_cost)
        if (granted_days == claim["claimed_relief_days"]
                and granted_cost == claim["claimed_cost_cents"]):
            setf(claim, "status", "GRANTED")
        else:
            setf(claim, "status", "PARTIALLY_GRANTED")
    else:
        setf(claim, "granted_relief_days", 0)
        setf(claim, "granted_cost_cents", 0)
        setf(claim, "status", "REJECTED")

    setf(claim, "determined_at", db.now_str())
    setf(claim, "determination_note", note)

    if decision == "GRANT" and claim["claim_type"] == "COMPENSATION_EVENT":
        start_dt = calc.as_instant(claim["event_start"])
        end_dt = calc.as_instant(claim["event_end"])
        for period in calc.periods_touching_window(concession["id"], start_dt, end_dt):
            setf(period, "relief_credit_cents", calc.relief_credit_cents(period))
            net = period["gross_unitary_charge_cents"] - max(
                0, period["total_deduction_cents"] - period["relief_credit_cents"])
            setf(period, "net_payment_cents", net)
            calc.mark_adjusted_if_repriced(period, unconditional=True)
    return ok(public(claim))


# ------------------------------------------------------------------ reserve ledger
@bp.post("/ppp/concessions/<row_id>/reserve-transactions")
def append_reserve_txn(row_id):
    require_auth(ROLE_CONCESSIONAIRE)
    concession = get_concession(row_id)
    owner_guard(concession)
    data = body()
    txn_type = req_enum(data, "txn_type", ALL_TXN_TYPES)
    amount = req_int(data, "amount_cents", minimum=1)
    reason = req_str(data, "reason", max_len=500)
    if txn_type == "REVERSAL":
        fail("ERR_INVALID_REQUEST", "Reversals go through the dedicated endpoint.")

    if txn_type == "WITHDRAWAL":
        if concession["handback_status"] != "NOT_SURVEYED":
            fail("ERR_RESERVE_WITHDRAWAL_FORBIDDEN")
        if calc.reserve_balance(concession) - amount < 0:
            fail("ERR_RESERVE_WITHDRAWAL_FORBIDDEN")

    row = calc.append_ledger(concession, txn_type, amount, reason, role())
    return created(public(row))


@bp.post("/ppp/reserve-transactions/<row_id>/reverse")
def reverse_reserve_txn(row_id):
    require_auth(ROLE_PLATFORM_ADMIN)
    target = get_txn(row_id)
    concession = concession_of(target)
    data = body()
    reason = req_str(data, "reason", max_len=500)

    for txn in calc.concession_txns(concession["id"]):
        if txn["reverses_txn_id"] == target["id"]:
            fail("ERR_TRANSACTION_ALREADY_REVERSED")
    if target["txn_type"] == "REVERSAL":
        fail("ERR_CANNOT_REVERSE_REVERSAL")

    row = calc.append_ledger(
        concession, "REVERSAL", target["amount_cents"], reason, role(),
        reverses_txn_id=target["id"],
        signed_amount_cents=-target["signed_amount_cents"])
    return created(public(row))
