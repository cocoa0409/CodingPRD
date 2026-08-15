from flask import Blueprint, request

import db
from errors import (ApiError, ERR_NOT_FOUND, ERR_INVALID_STATE,
                    ERR_PROGRAM_SUSPENDED, ERR_CLOSE_NEGATIVE, ERR_OPEN_ITEMS)
from helpers import (auth, require_role, require_body, ok, ok_list, v_str,
                     ALL_ROLES, sort_created)
from serializers import account_to_dict, offer_effective_status

bp = Blueprint("accounts", __name__)


def get_account_or_404(aid):
    a = db.store["accounts"].get(aid)
    if a is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Account %s not found" % aid)
    return a


@bp.post("/v1/accounts")
def create_account():
    _, role = auth()
    require_role(role, ["Teller", "ProgramAdmin"])
    body = require_body()
    program_id = v_str(body, "program_id")
    holder_name = v_str(body, "holder_name")
    program = db.store["programs"].get(program_id)
    if program is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Program %s not found" % program_id)
    if program["status"] != "ACTIVE":
        raise ApiError(ERR_PROGRAM_SUSPENDED, 409,
                       "Program is SUSPENDED; account opening is gated")
    a = db.new_entity({
        "program_id": program_id,
        "holder_name": holder_name,
        "status": "ACTIVE",
        "ledger_balance_cents": 0,
        "consecutive_negative_business_days": 0,
        "restricted_business_days": 0,
        "lifetime_fees_assessed_cents": 0,
        "lifetime_fees_waived_cents": 0,
        "charged_off_cents": 0,
        "recovered_cents": 0,
        "charge_off_original_cents": 0,
    })
    db.store["accounts"][a["id"]] = a
    return ok(account_to_dict(a), status=201)


@bp.get("/v1/accounts")
def list_accounts():
    _, role = auth()
    require_role(role, ALL_ROLES)
    items = list(db.store["accounts"].values())
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    if program_id is not None:
        items = [a for a in items if a["program_id"] == program_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return ok_list([account_to_dict(a) for a in sort_created(items)])


@bp.get("/v1/accounts/<aid>")
def get_account(aid):
    _, role = auth()
    require_role(role, ALL_ROLES)
    return ok(account_to_dict(get_account_or_404(aid)))


@bp.post("/v1/accounts/<aid>/close")
def close_account(aid):
    _, role = auth()
    require_role(role, ["Teller", "ProgramAdmin"])
    a = get_account_or_404(aid)
    # Tier 7: voluntary close is only valid from ACTIVE.
    if a["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an ACTIVE account can be voluntarily closed")
    # Tier 11: close economics — non-negative balance first, then open items.
    if a["ledger_balance_cents"] < 0:
        raise ApiError(ERR_CLOSE_NEGATIVE, 409,
                       "Cannot close an account with a negative ledger balance")
    for f in db.store["fees"].values():
        if f["account_id"] == aid and f["status"] == "ASSESSED":
            raise ApiError(ERR_OPEN_ITEMS, 409, "Account has ASSESSED fees")
    for w in db.store["waiver_requests"].values():
        if w["account_id"] == aid and w["status"] in (
                "PENDING_SUPERVISOR", "PENDING_MANAGER", "PENDING_COMPLIANCE"):
            raise ApiError(ERR_OPEN_ITEMS, 409, "Account has pending waiver requests")
    for o in db.store["offers"].values():
        if o["account_id"] == aid and offer_effective_status(o) == "OFFERED":
            raise ApiError(ERR_OPEN_ITEMS, 409, "Account has an OFFERED education offer")
    a["status"] = "CLOSED_VOLUNTARY"
    db.touch(a)
    return ok(account_to_dict(a))
