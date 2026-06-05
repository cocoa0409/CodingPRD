"""WalletTransaction flat ledger reads (PRD §3.2).

GET /api/wallet-transactions/{id}  — PlatformAdmin, Rider
GET /api/wallet-transactions        — PlatformAdmin
"""
from flask import Blueprint, request

import errors
from db import db
from middleware import authenticate, require_role, require_rider_owner
from response import success
from util import public, parse_pagination, paginate

bp = Blueprint("wallet_transactions", __name__)


@bp.get("/api/wallet-transactions/<txn_id>")
def get_txn(txn_id):
    role, user_id = authenticate()
    require_role(role, {"PlatformAdmin", "Rider"})
    txn = db.wallet_transactions.get(txn_id)
    if txn is None:
        raise errors.not_found("Wallet transaction not found")
    # A Rider may only read their own ledger entry (PRD §2.1).
    require_rider_owner(role, user_id, txn["rider_id"])
    return success(public(txn))


@bp.get("/api/wallet-transactions")
def list_txns():
    role, user_id = authenticate()
    require_role(role, {"PlatformAdmin"})
    limit, offset = parse_pagination()

    rows = list(db.wallet_transactions.values())
    rider_id = request.args.get("rider_id")
    if rider_id is not None:
        rows = [r for r in rows if r["rider_id"] == rider_id]
    trip_id = request.args.get("trip_id")
    if trip_id is not None:
        rows = [r for r in rows if r["trip_id"] == trip_id]
    fine_id = request.args.get("fine_id")
    if fine_id is not None:
        rows = [r for r in rows if r["fine_id"] == fine_id]
    txn_type = request.args.get("txn_type")
    if txn_type is not None:
        rows = [r for r in rows if r["txn_type"] == txn_type]

    page, pagination = paginate(rows, limit, offset)
    return success(page, is_array=True, pagination=pagination)
