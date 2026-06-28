from decimal import Decimal

from flask import Blueprint, g, request

from db import store, stamp_new, touch
from errors import (
    fail,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_NO_ENROLLED_DEBTS,
    ERR_NOT_PROGRAM_OWNER,
    ERR_COMPLETION_NOT_ELIGIBLE,
    ERR_ACCOUNT_DEFAULTED,
    ERR_INVALID_REQUEST,
)
from middleware import require_roles
from response import success
from routes.helpers import (
    get_body,
    require_fields,
    require_string,
    positive_decimal,
    fraction,
    require_int,
    as_decimal,
    lookup,
    paginate,
    sort_by_created,
)
from services import core
from services.cascades import drop_program_cascade
from services.serialize import program_out

bp = Blueprint("programs", __name__)


@bp.post("/programs")
@require_roles("ProgramAdmin")
def create_program():
    body = get_body()
    require_fields(body, ["client_id", "monthly_deposit_amount"])
    client_id = body["client_id"]
    lookup(store.clients, client_id)
    monthly = positive_decimal(body["monthly_deposit_amount"], "monthly_deposit_amount")

    deposit_day = 1
    if body.get("deposit_day_of_month") is not None:
        deposit_day = require_int(body["deposit_day_of_month"], "deposit_day_of_month", 1, 28)

    target = Decimal("0.50")
    if body.get("target_settlement_pct") is not None:
        target = fraction(body["target_settlement_pct"], "target_settlement_pct")

    reserve_floor = Decimal("0")
    if body.get("reserve_floor") is not None:
        reserve_floor = as_decimal(body["reserve_floor"], "reserve_floor")
        if reserve_floor < 0:
            fail(ERR_INVALID_REQUEST, "reserve_floor must be >= 0")

    p = stamp_new({
        "client_id": client_id,
        "program_phase": "ENROLLING",
        "account_standing": "CURRENT",
        "target_settlement_pct": target,
        "monthly_deposit_amount": monthly,
        "deposit_day_of_month": deposit_day,
    })
    store.programs[p["id"]] = p

    a = stamp_new({
        "program_id": p["id"],
        "reserve_floor": reserve_floor,
    })
    store.accounts[a["id"]] = a

    return success(program_out(p), status=201)


@bp.get("/programs/<pid>")
@require_roles("ProgramAdmin", "NegotiationAgent", "Client")
def get_program(pid):
    p = lookup(store.programs, pid)
    if g.role == "Client" and p["client_id"] != g.user_id:
        fail(ERR_NOT_PROGRAM_OWNER, "Client may only read their own programs")
    return success(program_out(p))


@bp.get("/programs")
@require_roles("ProgramAdmin", "NegotiationAgent")
def list_programs():
    items = list(store.programs.values())
    client_id = request.args.get("client_id")
    if client_id is not None:
        items = [p for p in items if p["client_id"] == client_id]
    items = sort_by_created(items)
    page, pagination = paginate(items)
    return success([program_out(p) for p in page], pagination=pagination)


@bp.post("/programs/<pid>/activate")
@require_roles("ProgramAdmin")
def activate_program(pid):
    p = lookup(store.programs, pid)
    if p["program_phase"] != "ENROLLING":
        fail(ERR_INVALID_STATE, "Program is not in ENROLLING phase")
    has_enrolled = any(d["status"] == "ENROLLED" for d in core.program_debts(pid))
    if not has_enrolled:
        fail(ERR_NO_ENROLLED_DEBTS, "Program has no ENROLLED debt")
    p["program_phase"] = "ACTIVE"
    touch(p)
    return success(program_out(p))


@bp.post("/programs/<pid>/complete")
@require_roles("ProgramAdmin")
def complete_program(pid):
    p = lookup(store.programs, pid)
    if p["program_phase"] != "ACTIVE":
        fail(ERR_INVALID_STATE, "Program is not ACTIVE")
    core.recompute_account_standing(p)
    if not core.completion_eligible(p):
        fail(ERR_COMPLETION_NOT_ELIGIBLE, "Program is not completion-eligible")
    if p["account_standing"] == "DEFAULTED":
        fail(ERR_ACCOUNT_DEFAULTED, "Program is DEFAULTED")
    client = store.clients[p["client_id"]]
    from services.cascades import refund_account
    refund_account(p, client)
    p["program_phase"] = "COMPLETED"
    touch(p)
    return success(program_out(p))


@bp.post("/programs/<pid>/drop")
@require_roles("Client")
def drop_program(pid):
    p = lookup(store.programs, pid)
    if p["client_id"] != g.user_id:
        fail(ERR_NOT_PROGRAM_OWNER, "Client does not own this program")
    if p["program_phase"] not in ("ENROLLING", "ACTIVE"):
        fail(ERR_INVALID_STATE, "Program is not in a droppable phase")
    client = store.clients[p["client_id"]]
    drop_program_cascade(p, client)
    p["program_phase"] = "TERMINATED"
    touch(p)
    return success(program_out(p))
