"""Purchases, the earning legs, the clawback cascade, and the ledger (PRD 3.3, 3.4, 2.7)."""

from flask import Blueprint, request

from auth import endpoint
from core import DB, clock_iso, fmt_dt, must_find, new_row, ok, ordered, store, touch
from errors import invalid
from rhelp import require_account_open, require_state
from shapes import body, req_dt, req_int, req_string
from svc_earn import award
from svc_ledger import append_entry, ledger_order, refresh_account
from svc_posture import hold_transfer
from views import ADMIN, OPS_CARD, listing, plain

bp = Blueprint("transactions", __name__)


@bp.post("/transactions")
@endpoint(ADMIN)
def create_transaction():
    data = body()
    account_id = data.get("account_id")
    if not isinstance(account_id, str) or account_id.strip() == "":
        raise invalid("'account_id' is required")
    account = must_find("accounts", account_id)

    mcc_code = req_string(data, "mcc_code")
    amount_cents = req_int(data, "amount_cents", minimum=1)
    posted_at = req_dt(data, "posted_at")
    require_account_open(account)

    row = new_row(
        "transactions",
        {
            "account_id": account_id,
            "mcc_code": mcc_code,
            "amount_cents": amount_cents,
            "posted_at": fmt_dt(posted_at),
            "merchant_category_id": None,
            "classification_source": "FALLBACK",
            "rotation_id": None,
            "rotation_eligible_cents": 0,
            "base_points": 0,
            "bonus_points": 0,
            "total_points_earned": 0,
            "status": "POSTED",
            "reversed_at": None,
            "reversal_reason": None,
        },
    )
    store("transactions", row)
    award(row, account)

    append_entry(
        account,
        "EARN_BASE",
        row["base_points"],
        "TRANSACTION",
        row["id"],
        "Base points earned on purchase",
    )
    if row["bonus_points"] > 0:
        append_entry(
            account,
            "EARN_BONUS",
            row["bonus_points"],
            "TRANSACTION",
            row["id"],
            "Rotation bonus points earned on purchase",
        )
    touch(account)
    refresh_account(account)
    return ok(plain(row), 201)


@bp.get("/transactions/<transaction_id>")
@endpoint(OPS_CARD)
def read_transaction(transaction_id):
    return ok(plain(must_find("transactions", transaction_id)))


@bp.get("/transactions")
@endpoint(OPS_CARD)
def list_transactions():
    args = request.args
    filters = {
        "account_id": args.get("account_id"),
        "merchant_category_id": args.get("merchant_category_id"),
        "rotation_id": args.get("rotation_id"),
        "classification_source": args.get("classification_source"),
        "status": args.get("status"),
    }
    return listing("transactions", args, filters)


@bp.post("/transactions/<transaction_id>/reverse")
@endpoint(ADMIN)
def reverse_transaction(transaction_id):
    transaction = must_find("transactions", transaction_id)
    account = must_find("accounts", transaction["account_id"])
    reversal_reason = req_string(body(), "reversal_reason")
    require_state(transaction, ("POSTED",))
    require_account_open(account)

    # hop one: the reversal itself
    transaction["status"] = "REVERSED"
    transaction["reversed_at"] = clock_iso()
    transaction["reversal_reason"] = reversal_reason
    touch(transaction)
    append_entry(
        account,
        "CLAWBACK",
        -transaction["total_points_earned"],
        "TRANSACTION",
        transaction["id"],
        "Points clawed back on purchase reversal",
    )

    # hop two: the balance is recomputed from the ledger
    refresh_account(account)
    touch(account)

    # hop three: underfunded in-flight transfers are held by the system
    if account["points_balance"] < 0:
        candidates = ordered(
            "transfer_requests",
            [
                t
                for t in DB["transfer_requests"].values()
                if t["account_id"] == account["id"] and t["status"] in ("SUBMITTED", "QUEUED")
            ],
        )
        for transfer in candidates:
            # hop four runs inside: the posture recomputes against the new hold count
            hold_transfer(account, transfer, "INSUFFICIENT_BALANCE_AFTER_CLAWBACK", "SYSTEM")

    refresh_account(account)
    return ok(plain(transaction))


# --------------------------------------------------------------------------
# points ledger
# --------------------------------------------------------------------------
@bp.get("/points-ledger-entries/<entry_id>")
@endpoint(OPS_CARD)
def read_entry(entry_id):
    return ok(plain(must_find("ledger", entry_id)))


@bp.get("/points-ledger-entries")
@endpoint(OPS_CARD)
def list_entries():
    args = request.args
    filters = {
        "account_id": args.get("account_id"),
        "entry_type": args.get("entry_type"),
        "source_entity_type": args.get("source_entity_type"),
        "source_entity_id": args.get("source_entity_id"),
    }
    return listing("ledger", args, filters, sort=ledger_order)
