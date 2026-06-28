from decimal import Decimal

from flask import Blueprint, g, request

from db import store, stamp_new
from errors import fail, ERR_DUPLICATE_ACCOUNT_NUMBER, ERR_NOT_PROGRAM_OWNER
from middleware import require_roles
from response import success
from routes.helpers import (
    get_body,
    require_fields,
    require_string,
    positive_decimal,
    lookup,
    paginate,
    sort_by_created,
)
from services import core
from services.serialize import debt_out

bp = Blueprint("debts", __name__)


@bp.post("/debts")
@require_roles("ProgramAdmin")
def create_debt():
    body = get_body()
    require_fields(body, ["program_id", "creditor_name", "account_number", "original_balance"])
    program_id = body["program_id"]
    lookup(store.programs, program_id)
    creditor_name = require_string(body["creditor_name"], "creditor_name")
    account_number = require_string(body["account_number"], "account_number")
    original_balance = positive_decimal(body["original_balance"], "original_balance")

    # Unique account_number within the program
    for d in core.program_debts(program_id):
        if d["account_number"] == account_number:
            fail(ERR_DUPLICATE_ACCOUNT_NUMBER, "account_number already used in this program")

    # Fee tier snapshot: existing open balances + this new debt's balance.
    total = core.total_enrolled_balance(program_id, extra=original_balance)
    fee_rate = core.fee_tier_for_total(total)

    d = stamp_new({
        "program_id": program_id,
        "creditor_name": creditor_name,
        "account_number": account_number,
        "original_balance": original_balance,
        "settled_amount": Decimal("0"),
        "forgiven_amount": Decimal("0"),
        "fee_rate_pct": fee_rate,
        "status": "ENROLLED",
        "settled_offer_id": None,
    })
    store.debts[d["id"]] = d
    return success(debt_out(d), status=201)


@bp.get("/debts/<did>")
@require_roles("ProgramAdmin", "NegotiationAgent", "Client")
def get_debt(did):
    d = lookup(store.debts, did)
    _scope(d["program_id"])
    return success(debt_out(d))


@bp.get("/debts")
@require_roles("ProgramAdmin", "NegotiationAgent", "Client")
def list_debts():
    items = list(store.debts.values())
    program_id = request.args.get("program_id")
    settled_offer_id = request.args.get("settled_offer_id")
    status = request.args.get("status")
    if program_id is not None:
        items = [d for d in items if d["program_id"] == program_id]
    if settled_offer_id is not None:
        items = [d for d in items if d["settled_offer_id"] == settled_offer_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    if g.role == "Client":
        items = [d for d in items
                 if store.programs.get(d["program_id"], {}).get("client_id") == g.user_id]
    items = sort_by_created(items)
    page, pagination = paginate(items)
    return success([debt_out(d) for d in page], pagination=pagination)


def _scope(program_id):
    if g.role == "Client":
        p = store.programs.get(program_id)
        if p is None or p["client_id"] != g.user_id:
            fail(ERR_NOT_PROGRAM_OWNER, "Client may only read their own resources")
