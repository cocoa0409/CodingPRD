from flask import Blueprint, request

from db import store
from errors import err
from middleware import require
from response import success, paginated
from services.common import (
    base_record, ledger_record, touch, require_str, require_int,
    require_enum, valid_email, require_body, parse_pagination, page,
)
from services import serialize

bp = Blueprint("consignors", __name__)

CONSIGNOR_STATUSES = {"ACTIVE", "SUSPENDED", "CLOSED"}


@bp.post("/consignors")
@require("StoreAdmin")
def create_consignor():
    body = require_body()
    full_name = require_str(body, "full_name")
    if "email" not in body:
        raise err("ERR_INVALID_REQUEST", "Missing field: email")
    email = body["email"]
    if not valid_email(email):
        raise err("ERR_INVALID_REQUEST", "email is not a valid address")

    for c in store.consignors.values():
        if c["email"] == email:
            raise err("ERR_DUPLICATE_EMAIL", "email already in use")

    rec = base_record()
    rec.update({
        "full_name": full_name,
        "email": email,
        "status": "ACTIVE",
        "store_credit_cents": 0,
        "unsettled_payable_cents": 0,
        "lifetime_payout_cents": 0,
    })
    store.consignors[rec["id"]] = rec
    return success(serialize.consignor_out(rec), 201)


@bp.get("/consignors/<cid>")
@require("StoreAdmin", "SettlementManager", "CashierClerk", "IntakeGrader", "Authenticator")
def get_consignor(cid):
    c = store.consignors.get(cid)
    if c is None:
        raise err("ERR_NOT_FOUND", "Consignor not found")
    return success(serialize.consignor_out(c), 200)


@bp.get("/consignors")
@require("StoreAdmin", "SettlementManager")
def list_consignors():
    limit, offset = parse_pagination()
    status = request.args.get("status")
    recs = list(store.consignors.values())
    if status is not None:
        recs = [c for c in recs if c["status"] == status]
    window, total = page(recs, limit, offset)
    return paginated([serialize.consignor_out(c) for c in window], limit, offset, total)


@bp.patch("/consignors/<cid>")
@require("StoreAdmin")
def patch_consignor(cid):
    c = store.consignors.get(cid)
    if c is None:
        raise err("ERR_NOT_FOUND", "Consignor not found")
    body = require_body()
    status = require_enum(body, "status", CONSIGNOR_STATUSES)
    c["status"] = status
    touch(c)
    return success(serialize.consignor_out(c), 200)


@bp.get("/consignors/<cid>/agreements")
@require("StoreAdmin", "SettlementManager")
def consignor_agreements(cid):
    if cid not in store.consignors:
        raise err("ERR_NOT_FOUND", "Consignor not found")
    limit, offset = parse_pagination()
    recs = [a for a in store.agreements.values() if a["consignor_id"] == cid]
    window, total = page(recs, limit, offset)
    return paginated([serialize.agreement_out(a) for a in window], limit, offset, total)


@bp.get("/consignors/<cid>/ledger-entries")
@require("StoreAdmin", "SettlementManager")
def consignor_ledger(cid):
    if cid not in store.consignors:
        raise err("ERR_NOT_FOUND", "Consignor not found")
    limit, offset = parse_pagination()
    recs = [e for e in store.payout_ledger_entries.values() if e["consignor_id"] == cid]
    settled = request.args.get("settled")
    if settled is not None:
        want = settled.lower() in ("true", "1", "yes")
        recs = [e for e in recs if (e["settlement_id"] is not None) == want]
    window, total = page(recs, limit, offset)
    return paginated([serialize.ledger_out(e) for e in window], limit, offset, total)


@bp.get("/consignors/<cid>/store-credit/transactions")
@require("StoreAdmin", "SettlementManager")
def consignor_credit_txns(cid):
    if cid not in store.consignors:
        raise err("ERR_NOT_FOUND", "Consignor not found")
    limit, offset = parse_pagination()
    recs = [t for t in store.store_credit_transactions.values() if t["consignor_id"] == cid]
    window, total = page(recs, limit, offset)
    return paginated([serialize.credit_txn_out(t) for t in window], limit, offset, total)


@bp.get("/consignors/<cid>/sale-lines")
@require("StoreAdmin", "SettlementManager")
def consignor_sale_lines(cid):
    if cid not in store.consignors:
        raise err("ERR_NOT_FOUND", "Consignor not found")
    limit, offset = parse_pagination()
    recs = [l for l in store.sale_lines.values() if l["consignor_id"] == cid]
    window, total = page(recs, limit, offset)
    return paginated([serialize.sale_line_out(l) for l in window], limit, offset, total)


@bp.post("/consignors/<cid>/store-credit/redeem")
@require("CashierClerk", "StoreAdmin")
def redeem_store_credit(cid):
    c = store.consignors.get(cid)
    if c is None:
        raise err("ERR_NOT_FOUND", "Consignor not found")
    body = require_body()
    amount = require_int(body, "amount_cents", minimum=1)

    current = serialize.recompute_store_credit(cid)
    if current - amount < 0:
        raise err("ERR_INSUFFICIENT_STORE_CREDIT", "Redemption exceeds store-credit balance")

    txn = ledger_record()
    txn.update({
        "consignor_id": cid,
        "txn_type": "REDEEM",
        "amount_cents": -amount,
        "status": "POSTED",
    })
    store.store_credit_transactions[txn["id"]] = txn
    serialize.reconcile_consignor(c)
    return success(serialize.credit_txn_out(txn), 201)
