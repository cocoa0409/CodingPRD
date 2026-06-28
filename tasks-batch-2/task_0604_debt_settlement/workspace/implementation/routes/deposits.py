from datetime import timezone

from flask import Blueprint, g, request

from db import store, stamp_new, touch
from errors import (
    fail,
    ERR_INVALID_REQUEST,
    ERR_NOT_PROGRAM_OWNER,
    ERR_DEPOSIT_MONTH_OCCUPIED,
    ERR_INVALID_STATE,
)
from middleware import require_roles
from response import success
from clock import parse_iso8601
from routes.helpers import (
    get_body,
    require_fields,
    positive_decimal,
    lookup,
    paginate,
    sort_by_created,
)
from services import core
from services.serialize import deposit_out

bp = Blueprint("deposits", __name__)

DEPOSIT_STATUSES = {"CLEARED", "MISSED", "RETURNED"}


def _month_bucket(dt):
    """Return (year, month) UTC bucket key for a datetime."""
    dt = dt.astimezone(timezone.utc)
    return (dt.year, dt.month)


@bp.post("/deposits")
@require_roles("Client", "ProgramAdmin")
def create_deposit():
    body = get_body()
    require_fields(body, ["program_id", "scheduled_for", "amount"])
    program_id = body["program_id"]
    program = lookup(store.programs, program_id)

    # Ownership for Client
    if g.role == "Client" and program["client_id"] != g.user_id:
        fail(ERR_NOT_PROGRAM_OWNER, "Client does not own this program")

    scheduled_for_raw = body["scheduled_for"]
    scheduled_dt = parse_iso8601(scheduled_for_raw)
    if scheduled_dt is None:
        fail(ERR_INVALID_REQUEST, "scheduled_for must be a valid ISO8601 instant")
    amount = positive_decimal(body["amount"], "amount")

    status = "CLEARED"
    if body.get("status") is not None:
        status = body["status"]
        if status not in DEPOSIT_STATUSES:
            fail(ERR_INVALID_REQUEST, "invalid deposit status")

    # Month-bucket occupancy check (only for CLEARED deposits)
    if status == "CLEARED":
        bucket = _month_bucket(scheduled_dt)
        for d in core.program_deposits(program_id):
            if d["status"] == "CLEARED":
                if _month_bucket(parse_iso8601(d["scheduled_for"])) == bucket:
                    fail(ERR_DEPOSIT_MONTH_OCCUPIED, "A CLEARED deposit already occupies this month bucket")

    d = stamp_new({
        "program_id": program_id,
        "scheduled_for": scheduled_for_raw,
        "amount": amount,
        "status": status,
    })
    store.deposits[d["id"]] = d

    if status == "MISSED":
        core.recompute_account_standing(program)
        touch(program)

    return success(deposit_out(d), status=201)


@bp.get("/deposits/<did>")
@require_roles("ProgramAdmin", "NegotiationAgent", "Client")
def get_deposit(did):
    d = lookup(store.deposits, did)
    _scope(d["program_id"])
    return success(deposit_out(d))


@bp.get("/deposits")
@require_roles("ProgramAdmin", "NegotiationAgent", "Client")
def list_deposits():
    items = list(store.deposits.values())
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    if program_id is not None:
        items = [d for d in items if d["program_id"] == program_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    if g.role == "Client":
        items = [d for d in items
                 if store.programs.get(d["program_id"], {}).get("client_id") == g.user_id]
    items = sort_by_created(items)
    page, pagination = paginate(items)
    return success([deposit_out(d) for d in page], pagination=pagination)


@bp.post("/deposits/<did>/cure")
@require_roles("Client", "ProgramAdmin")
def cure_deposit(did):
    d = lookup(store.deposits, did)
    program = store.programs[d["program_id"]]
    if g.role == "Client" and program["client_id"] != g.user_id:
        fail(ERR_NOT_PROGRAM_OWNER, "Client does not own this program")
    if d["status"] != "MISSED":
        fail(ERR_INVALID_STATE, "Deposit is not MISSED")
    d["status"] = "CLEARED"
    touch(d)
    core.recompute_account_standing(program)
    touch(program)
    return success(deposit_out(d))


def _scope(program_id):
    if g.role == "Client":
        p = store.programs.get(program_id)
        if p is None or p["client_id"] != g.user_id:
            fail(ERR_NOT_PROGRAM_OWNER, "Client may only read their own resources")
