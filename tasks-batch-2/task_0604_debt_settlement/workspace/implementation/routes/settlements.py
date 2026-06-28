from decimal import Decimal

from flask import Blueprint, g, request

from db import store, stamp_new, touch, round_half_up
from errors import (
    fail,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_ACCOUNT_DEFAULTED,
    ERR_INSUFFICIENT_RESERVE,
    ERR_OFFER_NOT_ACCEPTED,
    ERR_NOT_PROGRAM_OWNER,
)
from middleware import require_roles
from response import success
from routes.helpers import get_body, require_fields, lookup, paginate, sort_by_created
from services import core
from services.cascades import complete_settlement_cascade, void_settlement_cascade
from services.serialize import settlement_out

bp = Blueprint("settlements", __name__)


@bp.post("/settlements")
@require_roles("NegotiationAgent")
def fund_settlement():
    body = get_body()
    require_fields(body, ["program_id", "offer_id"])
    program_id = body["program_id"]
    program = lookup(store.programs, program_id)
    offer = lookup(store.offers, body["offer_id"])

    if offer["program_id"] != program_id:
        fail(ERR_NOT_FOUND, "offer does not belong to the named program")

    debt = store.debts[offer["debt_id"]]

    # Account standing: DEFAULTED blocks funding
    core.recompute_account_standing(program)
    if program["account_standing"] == "DEFAULTED":
        fail(ERR_ACCOUNT_DEFAULTED, "Program is DEFAULTED")

    # Offer must be ACCEPTED and not already have produced a non-VOIDED settlement
    if offer["status"] != "ACCEPTED":
        fail(ERR_OFFER_NOT_ACCEPTED, "Offer is not ACCEPTED")
    for s in store.settlements.values():
        if s["offer_id"] == offer["id"] and s["status"] != "VOIDED":
            fail(ERR_OFFER_NOT_ACCEPTED, "Offer already produced a settlement")

    settlement_amount = Decimal(str(offer["settlement_amount"]))
    projected_fee = Decimal(str(offer["projected_fee"]))
    acct = core.account_for_program(program_id)
    reserve_floor = Decimal(str(acct["reserve_floor"])) if acct else Decimal("0")

    # Instantaneous funding reserve check
    balance = core.account_balance(program_id)
    if balance < settlement_amount + projected_fee + reserve_floor:
        fail(ERR_INSUFFICIENT_RESERVE, "Insufficient account balance for funding")

    funded_amount = settlement_amount
    forgiven = Decimal(str(debt["original_balance"])) - funded_amount

    s = stamp_new({
        "program_id": program_id,
        "offer_id": offer["id"],
        "debt_id": offer["debt_id"],
        "funded_amount": funded_amount,
        "forgiven_amount": forgiven,
        "status": "FUNDED",
    })
    store.settlements[s["id"]] = s

    # SettlementFee OUTSTANDING at effective rate (fee on funded principal)
    eff_rate = core.effective_rate(Decimal(str(debt["fee_rate_pct"])), debt["status"])
    fee_amount = round_half_up(funded_amount * eff_rate, 2)
    f = stamp_new({
        "program_id": program_id,
        "settlement_id": s["id"],
        "amount": fee_amount,
        "status": "OUTSTANDING",
    })
    store.fees[f["id"]] = f

    return success(settlement_out(s), status=201)


@bp.get("/settlements/<sid>")
@require_roles("ProgramAdmin", "NegotiationAgent", "Client")
def get_settlement(sid):
    s = lookup(store.settlements, sid)
    _scope(s["program_id"])
    return success(settlement_out(s))


@bp.get("/settlements")
@require_roles("ProgramAdmin", "NegotiationAgent", "Client")
def list_settlements():
    items = list(store.settlements.values())
    program_id = request.args.get("program_id")
    offer_id = request.args.get("offer_id")
    debt_id = request.args.get("debt_id")
    status = request.args.get("status")
    if program_id is not None:
        items = [s for s in items if s["program_id"] == program_id]
    if offer_id is not None:
        items = [s for s in items if s["offer_id"] == offer_id]
    if debt_id is not None:
        items = [s for s in items if s["debt_id"] == debt_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    if g.role == "Client":
        items = [s for s in items
                 if store.programs.get(s["program_id"], {}).get("client_id") == g.user_id]
    items = sort_by_created(items)
    page, pagination = paginate(items)
    return success([settlement_out(s) for s in page], pagination=pagination)


@bp.post("/settlements/<sid>/complete")
@require_roles("NegotiationAgent")
def complete_settlement(sid):
    s = lookup(store.settlements, sid)
    program = store.programs[s["program_id"]]
    if s["status"] != "FUNDED":
        fail(ERR_INVALID_STATE, "Settlement is not FUNDED")
    core.recompute_account_standing(program)
    if program["account_standing"] == "DEFAULTED":
        fail(ERR_ACCOUNT_DEFAULTED, "Program is DEFAULTED")
    s["status"] = "COMPLETED"
    touch(s)
    complete_settlement_cascade(s)
    return success(settlement_out(s))


@bp.post("/settlements/<sid>/void")
@require_roles("ProgramAdmin")
def void_settlement(sid):
    s = lookup(store.settlements, sid)
    if s["status"] != "FUNDED":
        fail(ERR_INVALID_STATE, "Settlement is not FUNDED")
    s["status"] = "VOIDED"
    touch(s)
    void_settlement_cascade(s)
    return success(settlement_out(s))


def _scope(program_id):
    if g.role == "Client":
        p = store.programs.get(program_id)
        if p is None or p["client_id"] != g.user_id:
            fail(ERR_NOT_PROGRAM_OWNER, "Client may only read their own resources")
