"""PosTransaction endpoints."""
from flask import Blueprint

import calc
import serial
import services
from core import (bad_request, db, ensure_object, fail, filter_bool,
                  filter_str, get_body, mark, ok, ok_list, ordered, paginate,
                  req_enum, req_int, req_str, require_auth, resolve_body_ref,
                  resolve_path, stamp_new)
from guards import CLERK_ADMIN, check_store_scope, validate_line_items

bp = Blueprint("pos", __name__)

POS_READ_ROLES = ("FnsAdmin", "FnsAnalyst", "AdminReviewOfficer",
                  "RetailerOwner", "StoreClerk")
VOID_REASON_CODES = ("CLERK_ERROR", "CUSTOMER_ABANDONED", "PROCESSOR_REVERSAL")


@bp.post("/pos-transactions")
def create_transaction():
    require_auth(CLERK_ADMIN)
    body = get_body()
    ensure_object(body)
    store = resolve_body_ref(body, "store_id", db.stores, "ERR_STORE_NOT_FOUND")
    deployment = resolve_body_ref(body, "terminal_deployment_id",
                                 db.terminal_deployments,
                                 "ERR_DEPLOYMENT_NOT_FOUND")
    if store is not None:
        check_store_scope(store)
    card = req_str(body, "household_ebt_card_last4")
    line_items = validate_line_items(body, "line_items")
    snap_available = req_int(body, "snap_benefit_available_cents", minimum=0)
    other_offered = req_int(body, "other_tender_offered_cents", minimum=0)
    if store is None:
        req_str(body, "store_id")
    if deployment is None:
        req_str(body, "terminal_deployment_id")
    if len(card) != 4:
        bad_request("Field 'household_ebt_card_last4' must be 4 characters.")
    if deployment["status"] != "ACTIVE":
        fail("ERR_TERMINAL_DEPLOYMENT_NOT_ACTIVE")
    if store["authorization_status"] != "AUTHORIZED":
        fail("ERR_STORE_NOT_AUTHORIZED")
    result = calc.pos_split_tender(line_items, snap_available, other_offered,
                                   store["tax_rate_bps"])
    error_id = result.pop("error_id", None)
    row = stamp_new({
        "store_id": store["id"],
        "terminal_deployment_id": deployment["id"],
        "household_ebt_card_last4": card,
        "line_items": line_items,
        "snap_benefit_available_cents": snap_available,
        "other_tender_offered_cents": other_offered,
        "void_reason_code": None,
    })
    row.update(result)
    row.setdefault("decline_reason_code", None)
    db.pos_transactions[row["id"]] = row
    if error_id is not None:
        # The declined sale is still recorded, but the call reports the refusal.
        fail(error_id)
    services.refresh_open_periods(store["id"])
    services.commit()
    return ok(serial.pos_transaction(row), 201)


@bp.get("/pos-transactions/<transaction_id>")
def get_transaction(transaction_id):
    require_auth(POS_READ_ROLES)
    row = resolve_path(db.pos_transactions, transaction_id,
                       "ERR_POS_TRANSACTION_NOT_FOUND")
    return ok(serial.pos_transaction(row))


@bp.get("/pos-transactions")
def list_transactions():
    require_auth(POS_READ_ROLES)
    rows = ordered(list(db.pos_transactions.values()))
    for name in ("store_id", "terminal_deployment_id", "status"):
        value = filter_str(name)
        if value is not None:
            rows = [r for r in rows if r.get(name) == value]
    split = filter_bool("split_tender_applied")
    if split is not None:
        rows = [r for r in rows if bool(r.get("split_tender_applied")) == split]
    data, pagination = paginate(rows, serial.pos_transaction)
    return ok_list(data, pagination)


def _covering_periods(txn):
    return ordered([p for p in db.redemption_periods.values()
                    if p["store_id"] == txn["store_id"]
                    and p["period_start"] <= txn["created_at"] < p["period_end"]])


@bp.post("/pos-transactions/<transaction_id>/void")
def void_transaction(transaction_id):
    require_auth(CLERK_ADMIN)
    txn = resolve_path(db.pos_transactions, transaction_id,
                       "ERR_POS_TRANSACTION_NOT_FOUND")
    body = get_body()
    ensure_object(body)
    reason = req_enum(body, "void_reason_code", VOID_REASON_CODES)
    if txn["status"] != "AUTHORIZED":
        fail("ERR_INVALID_STATE")
    periods = _covering_periods(txn)
    for period in periods:
        if period["status"] != "OPEN":
            fail("ERR_REDEMPTION_PERIOD_CLOSED")
    txn["status"] = "VOIDED"
    txn["void_reason_code"] = reason
    mark(txn)
    for period in periods:
        services.refresh_period(period)
    services.commit()
    return ok(serial.pos_transaction(txn))
