from flask import Blueprint, request

import db
from errors import (ApiError, ERR_NOT_FOUND, ERR_INVALID_STATE,
                    ERR_ACCOUNT_CLOSED, ERR_ACCOUNT_RESTRICTED, ERR_OWNERSHIP,
                    ERR_RECOVERY_EXCEEDS, ERR_REVERSAL_CLOSED)
from helpers import (auth, require_role, require_body, ok, ok_list, v_str,
                     v_int, v_enum, ALL_ROLES, sort_created)
from serializers import transaction_to_dict
from services import reverse_transaction

bp = Blueprint("transactions", __name__)

TXN_TYPES = ["DEBIT_ONE_TIME", "DEBIT_RECURRING", "DEBIT_ACH", "DEBIT_CHECK", "CREDIT_DEPOSIT"]


def get_transaction_or_404(tid):
    t = db.store["transactions"].get(tid)
    if t is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Transaction %s not found" % tid)
    return t


@bp.post("/v1/transactions")
def create_transaction():
    uid, role = auth()
    require_role(role, ["AccountHolder", "Teller"])
    body = require_body()
    account_id = v_str(body, "account_id")
    ttype = v_enum(body, "type", TXN_TYPES)
    amount_cents = v_int(body, "amount_cents", min_value=1)
    acct = db.store["accounts"].get(account_id)
    if acct is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Account %s not found" % account_id)
    if role == "AccountHolder" and uid != account_id:
        raise ApiError(ERR_OWNERSHIP, 403, "AccountHolder may only act on their own account")
    # Account posture gates (tier 6).
    if acct["status"] == "CLOSED_VOLUNTARY":
        raise ApiError(ERR_ACCOUNT_CLOSED, 409, "Account is closed")
    if acct["status"] == "CLOSED_CHARGEOFF" and ttype != "CREDIT_DEPOSIT":
        raise ApiError(ERR_ACCOUNT_CLOSED, 409,
                       "A charged-off account admits only CREDIT_DEPOSIT recovery")
    if acct["status"] == "RESTRICTED" and ttype != "CREDIT_DEPOSIT":
        raise ApiError(ERR_ACCOUNT_RESTRICTED, 409,
                       "RESTRICTED account blocks new debit authorizations")
    if acct["status"] == "CLOSED_CHARGEOFF":
        # Recovery credit (tier 12): may not exceed remaining charge-off.
        if amount_cents > acct["charged_off_cents"]:
            raise ApiError(ERR_RECOVERY_EXCEEDS, 422,
                           "Recovery credit exceeds remaining charged-off balance")
        t = db.new_entity({
            "account_id": account_id,
            "type": ttype,
            "amount_cents": amount_cents,
            "status": "POSTED",
            "authorized_date": db.clock_date_str(),
            "batch_id": None,
            "posting_sequence": None,
            "posted_date": db.clock_date_str(),
        })
        db.store["transactions"][t["id"]] = t
        acct["recovered_cents"] += amount_cents
        acct["charged_off_cents"] -= amount_cents
        db.touch(acct)
        return ok(transaction_to_dict(t), status=201)
    t = db.new_entity({
        "account_id": account_id,
        "type": ttype,
        "amount_cents": amount_cents,
        "status": "AUTHORIZED",
        "authorized_date": db.clock_date_str(),
        "batch_id": None,
        "posting_sequence": None,
        "posted_date": None,
    })
    db.store["transactions"][t["id"]] = t
    return ok(transaction_to_dict(t), status=201)


@bp.get("/v1/transactions")
def list_transactions():
    _, role = auth()
    require_role(role, ALL_ROLES)
    items = list(db.store["transactions"].values())
    account_id = request.args.get("account_id")
    batch_id = request.args.get("batch_id")
    status = request.args.get("status")
    ttype = request.args.get("type")
    if account_id is not None:
        items = [t for t in items if t["account_id"] == account_id]
    if batch_id is not None:
        items = [t for t in items if t["batch_id"] == batch_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    if ttype is not None:
        items = [t for t in items if t["type"] == ttype]
    return ok_list([transaction_to_dict(t) for t in sort_created(items)])


@bp.get("/v1/transactions/<tid>")
def get_transaction(tid):
    _, role = auth()
    require_role(role, ALL_ROLES)
    return ok(transaction_to_dict(get_transaction_or_404(tid)))


@bp.post("/v1/transactions/<tid>/reverse")
def reverse_txn(tid):
    _, role = auth()
    require_role(role, ["OperationsClerk"])
    t = get_transaction_or_404(tid)
    if t["status"] != "POSTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a POSTED transaction can be reversed")
    batch = db.store["batches"].get(t["batch_id"]) if t["batch_id"] else None
    if batch is None or batch["status"] != "SEALED":
        raise ApiError(ERR_REVERSAL_CLOSED, 409,
                       "Reversal window is closed (batch not SEALED)")
    reverse_transaction(t)
    return ok(transaction_to_dict(t))
