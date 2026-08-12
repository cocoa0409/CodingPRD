"""Rebate statements and the loyalty ledger (earn / redeem / clawback)."""
from flask import Blueprint, request

import db
import services as svc
from authz import require_roles, owner_or_forbid, scoped_account_filter
from envelope import ok_object, ok_list
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_REFERENCE_NOT_FOUND, ERR_VALIDATION,
    ERR_INVALID_STATE, ERR_ACCOUNT_SUSPENDED, ERR_REBATE_PERIOD_INVALID,
    ERR_REBATE_PERIOD_OVERLAP, ERR_INSUFFICIENT_POINTS,
)
from serializers import ser_statement, ser_loyalty_txn, sorted_rows
from validate import body_json, req_str, req_int, req_dt, pagination_params, query_enum_filter

bp = Blueprint("rebates", __name__)

ADMIN = ["CorporateAdmin"]
STATEMENT_READERS = ["CorporateAdmin", "Contractor"]
LEDGER_READERS = ["CorporateAdmin", "StoreManager", "StoreAssociate", "Contractor"]
STATEMENT_STATUS = {"ACCRUED", "FINALIZED", "DISPUTED", "PAID"}


def _get_statement(statement_id):
    s = db.rebate_statements.get(statement_id)
    if s is None:
        raise_err(ERR_NOT_FOUND, "rebate statement %s not found" % statement_id)
    return s


@bp.post("/rebate-statements")
def create_statement():
    require_roles(ADMIN)
    data = body_json()
    contractor_account_id = data.get("contractor_account_id")
    if isinstance(contractor_account_id, str) and contractor_account_id not in db.contractor_accounts:
        raise_err(ERR_REFERENCE_NOT_FOUND,
                  "contractor_account_id %s not found" % contractor_account_id)
    if not isinstance(contractor_account_id, str):
        raise_err(ERR_VALIDATION,
                  "field 'contractor_account_id' is required and must be a string")
    period_start = req_dt(data, "period_start")
    period_end = req_dt(data, "period_end")
    if not period_end > period_start:
        raise_err(ERR_VALIDATION, "field 'period_end' must be after 'period_start'")
    now = db.now()
    if now < period_start:
        raise_err(ERR_REBATE_PERIOD_INVALID,
                  "cannot open a statement for a future period")
    for s in db.rebate_statements.values():
        if s["contractor_account_id"] != contractor_account_id:
            continue
        # Half-open overlap; adjacency allowed.
        if period_start < s["period_end"] and s["period_start"] < period_end:
            raise_err(ERR_REBATE_PERIOD_OVERLAP,
                      "statement period overlaps an existing statement for this account")
    provisional = svc.compute_provisional(contractor_account_id, period_start, period_end, now)
    stmt = svc.stamp_new({
        "contractor_account_id": contractor_account_id,
        "period_start": period_start,
        "period_end": period_end,
        "status": "ACCRUED",
        "provisional_amount_cents": provisional,
        "final_amount_cents": None,
        "adjustment_cents": 0,
        "payable_cents": None,
        "period_net_cents": None,
        "paid_at": None,
    })
    db.rebate_statements[stmt["id"]] = stmt
    return ok_object(ser_statement(stmt), 201)


@bp.get("/rebate-statements")
def list_statements():
    uid, role = require_roles(STATEMENT_READERS)
    limit, offset = pagination_params()
    contractor_filter = scoped_account_filter(uid, role, request.args.get("contractor_account_id"))
    status_filter = query_enum_filter("status", STATEMENT_STATUS)
    rows = list(db.rebate_statements.values())
    if contractor_filter is not None:
        rows = [s for s in rows if s["contractor_account_id"] == contractor_filter]
    if status_filter is not None:
        rows = [s for s in rows if s["status"] == status_filter]
    rows = sorted_rows(rows)
    total = len(rows)
    return ok_list([ser_statement(s) for s in rows[offset:offset + limit]], total, limit, offset)


@bp.get("/rebate-statements/<statement_id>")
def get_statement(statement_id):
    uid, role = require_roles(STATEMENT_READERS)
    stmt = _get_statement(statement_id)
    owner_or_forbid(uid, role, stmt["contractor_account_id"])
    return ok_object(ser_statement(stmt))


@bp.post("/rebate-statements/<statement_id>/finalize")
def finalize_statement(statement_id):
    require_roles(ADMIN)
    stmt = _get_statement(statement_id)
    if stmt["status"] != "ACCRUED" or db.now() < stmt["period_end"]:
        raise_err(ERR_INVALID_STATE,
                  "statement is not ACCRUED or the period has not closed")
    stmt["final_amount_cents"] = svc.compute_final(
        stmt["contractor_account_id"], stmt["period_start"], stmt["period_end"])
    stmt["period_net_cents"] = svc.period_net(
        stmt["contractor_account_id"], stmt["period_start"], stmt["period_end"])
    stmt["payable_cents"] = svc.compute_payable(stmt)
    stmt["status"] = "FINALIZED"
    svc.bump(stmt)
    return ok_object(ser_statement(stmt))


@bp.post("/rebate-statements/<statement_id>/dispute")
def dispute_statement(statement_id):
    uid, role = require_roles(["Contractor"])
    stmt = _get_statement(statement_id)
    owner_or_forbid(uid, role, stmt["contractor_account_id"])
    if stmt["status"] != "FINALIZED":
        raise_err(ERR_INVALID_STATE, "statement is not FINALIZED")
    stmt["status"] = "DISPUTED"
    svc.bump(stmt)
    return ok_object(ser_statement(stmt))


@bp.post("/rebate-statements/<statement_id>/resolve-dispute")
def resolve_dispute(statement_id):
    require_roles(ADMIN)
    stmt = _get_statement(statement_id)
    data = body_json()
    adjustment = req_int(data, "adjustment_cents")
    if stmt["status"] != "DISPUTED":
        raise_err(ERR_INVALID_STATE, "statement is not DISPUTED")
    stmt["adjustment_cents"] = adjustment
    stmt["payable_cents"] = svc.compute_payable(stmt)
    stmt["status"] = "FINALIZED"
    svc.bump(stmt)
    return ok_object(ser_statement(stmt))


@bp.post("/rebate-statements/<statement_id>/pay")
def pay_statement(statement_id):
    require_roles(ADMIN)
    stmt = _get_statement(statement_id)
    if stmt["status"] != "FINALIZED":
        raise_err(ERR_INVALID_STATE, "statement is not FINALIZED")
    stmt["status"] = "PAID"
    stmt["paid_at"] = db.now()
    svc.bump(stmt)
    account = db.contractor_accounts.get(stmt["contractor_account_id"])
    if account is not None:
        svc.bump(account)
    return ok_object(ser_statement(stmt))


# --- loyalty ---------------------------------------------------------------------------
@bp.post("/loyalty-redemptions")
def redeem_points():
    uid, role = require_roles(["Contractor"])
    data = body_json()
    requested = data.get("contractor_account_id")
    if isinstance(requested, str):
        owner_or_forbid(uid, role, requested)
    if isinstance(requested, str) and requested not in db.contractor_accounts:
        raise_err(ERR_REFERENCE_NOT_FOUND, "contractor_account_id %s not found" % requested)
    if not isinstance(requested, str):
        raise_err(ERR_VALIDATION,
                  "field 'contractor_account_id' is required and must be a string")
    points = req_int(data, "points_to_redeem")
    account = db.contractor_accounts[requested]
    if account["status"] != "ACTIVE":
        raise_err(ERR_ACCOUNT_SUSPENDED, "contractor account is SUSPENDED")
    if svc.loyalty_balance(requested) < points:
        raise_err(ERR_INSUFFICIENT_POINTS,
                  "points_to_redeem exceeds loyalty_points_balance")
    txn = svc.post_loyalty(
        requested, None, "REDEEM", -points,
        "Redeemed %d points for credit_cents=%d" % (points, points),
    )
    return ok_object(ser_loyalty_txn(txn), 201)


@bp.get("/loyalty-transactions")
def list_loyalty_transactions():
    uid, role = require_roles(LEDGER_READERS)
    limit, offset = pagination_params()
    contractor_filter = scoped_account_filter(uid, role, request.args.get("contractor_account_id"))
    order_filter = request.args.get("order_id")
    rows = list(db.loyalty_transactions.values())
    if contractor_filter is not None:
        rows = [t for t in rows if t["contractor_account_id"] == contractor_filter]
    if order_filter is not None:
        rows = [t for t in rows if t["order_id"] == order_filter]
        order = db.orders.get(order_filter)
        if role == "Contractor" and order is not None:
            owner_or_forbid(uid, role, order["contractor_account_id"])
    rows = sorted_rows(rows)
    total = len(rows)
    return ok_list([ser_loyalty_txn(t) for t in rows[offset:offset + limit]], total, limit, offset)


@bp.get("/loyalty-transactions/<txn_id>")
def get_loyalty_transaction(txn_id):
    uid, role = require_roles(LEDGER_READERS)
    t = db.loyalty_transactions.get(txn_id)
    if t is None:
        raise_err(ERR_NOT_FOUND, "loyalty transaction %s not found" % txn_id)
    owner_or_forbid(uid, role, t["contractor_account_id"])
    return ok_object(ser_loyalty_txn(t))
