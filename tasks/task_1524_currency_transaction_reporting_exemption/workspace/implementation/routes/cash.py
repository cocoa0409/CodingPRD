"""CashTransaction endpoints."""
from flask import Blueprint, request

from db import now, now_iso, stamp_new, store, today, touch
from errors import (
    ERR_AMOUNT_NOT_POSITIVE,
    ERR_BRANCH_INACTIVE,
    ERR_BRANCH_NOT_FOUND,
    ERR_CUSTOMER_NOT_ACTIVE,
    ERR_CUSTOMER_NOT_FOUND,
    ERR_OCCURRED_AT_IN_FUTURE,
    ERR_TRANSACTION_ALREADY_VOIDED,
    ERR_TRANSACTION_NOT_FOUND,
    ERR_VOID_WINDOW_EXPIRED,
    ApiError,
)
from middleware import authenticate, body, f_datetime, f_enum, f_int, f_str, f_str_opt, sorted_page
from response import ok, ok_list
from serializers import serialize_cash_transaction
from services.audit import add_fx, main_event
from services.domain import evaluate_structuring, recompute_aggregation

bp = Blueprint("cash_transactions", __name__)

ALL_ROLES = ["SystemAdmin", "BranchManager", "Teller", "ComplianceAnalyst", "BSAOfficer", "Examiner"]


def get_transaction_or_404(txn_id):
    t = store.cash_transactions.get(txn_id)
    if t is None:
        raise ApiError(ERR_TRANSACTION_NOT_FOUND, "Cash transaction not found", 404)
    return t


@bp.post("/cash-transactions")
def create_cash_transaction():
    authenticate(["Teller"])
    b = body()
    customer_id = f_str(b, "customer_id")
    branch_id = f_str(b, "branch_id")
    direction = f_enum(b, "direction", ("CASH_IN", "CASH_OUT"))
    amount_cents = f_int(b, "amount_cents")
    occurred_raw, occurred_dt = f_datetime(b, "occurred_at")
    conductor_name = f_str_opt(b, "conductor_name")
    # Body FK references resolve customer first, then branch.
    customer = store.customers.get(customer_id)
    if customer is None:
        raise ApiError(ERR_CUSTOMER_NOT_FOUND, "Customer not found", 404)
    branch = store.branches.get(branch_id)
    if branch is None:
        raise ApiError(ERR_BRANCH_NOT_FOUND, "Branch not found", 404)
    # Customer status is checked before the branch's.
    if customer["status"] != "ACTIVE":
        raise ApiError(ERR_CUSTOMER_NOT_ACTIVE, "Customer is not ACTIVE", 409)
    if branch["status"] != "ACTIVE":
        raise ApiError(ERR_BRANCH_INACTIVE, "Branch is not ACTIVE", 409)
    if amount_cents <= 0:
        raise ApiError(ERR_AMOUNT_NOT_POSITIVE, "amount_cents must be > 0", 422)
    if occurred_dt > now():
        raise ApiError(
            ERR_OCCURRED_AT_IN_FUTURE,
            "occurred_at is later than the current logical clock",
            422,
        )
    txn = {
        "customer_id": customer_id,
        "branch_id": branch_id,
        "direction": direction,
        "amount_cents": amount_cents,
        "occurred_at": occurred_raw,
        "business_date": occurred_dt.date().isoformat(),
        "conductor_name": conductor_name,
        "status": "POSTED",
        "voided_at": None,
    }
    stamp_new(txn)
    store.cash_transactions[txn["id"]] = txn
    # Atomic cascade: aggregation recompute, CTR reportability, structuring.
    recompute_aggregation(customer_id, txn["business_date"])
    if direction == "CASH_IN":
        evaluate_structuring(customer_id, txn["business_date"])
    main_event(
        "POST /cash-transactions", "CashTransaction", txn["id"], None,
        serialize_cash_transaction(txn),
    )
    return ok(serialize_cash_transaction(txn), status=201)


@bp.get("/cash-transactions")
def list_cash_transactions():
    authenticate(ALL_ROLES)
    items = list(store.cash_transactions.values())
    for param in ("customer_id", "branch_id", "business_date", "direction", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [t for t in items if t[param] == value]
    page, limit, offset, total = sorted_page(items)
    return ok_list([serialize_cash_transaction(t) for t in page], limit, offset, total)


@bp.get("/cash-transactions/<txn_id>")
def get_cash_transaction(txn_id):
    authenticate(ALL_ROLES)
    return ok(serialize_cash_transaction(get_transaction_or_404(txn_id)))


@bp.post("/cash-transactions/<txn_id>/void")
def void_cash_transaction(txn_id):
    authenticate(["Teller", "BranchManager"])
    b = body()
    void_reason = f_str_opt(b, "void_reason")
    txn = get_transaction_or_404(txn_id)
    if txn["status"] != "POSTED":
        raise ApiError(
            ERR_TRANSACTION_ALREADY_VOIDED, "Transaction is already VOIDED", 409
        )
    if txn["business_date"] != today().isoformat():
        raise ApiError(
            ERR_VOID_WINDOW_EXPIRED,
            "Void is permitted only on the transaction's business date",
            409,
        )
    before = serialize_cash_transaction(txn)
    txn["status"] = "VOIDED"
    txn["voided_at"] = now_iso()
    touch(txn)
    if void_reason is not None:
        add_fx({"type": "void_reason", "value": void_reason})
    recompute_aggregation(txn["customer_id"], txn["business_date"])
    main_event(
        "POST /cash-transactions/{id}/void", "CashTransaction", txn["id"], before,
        serialize_cash_transaction(txn),
    )
    return ok(serialize_cash_transaction(txn))
