"""TillSession + SalesTransaction endpoints (PRD §3.6)."""
from flask import Blueprint

from db import db, new_record, touch, iso_now, parse_ts
from errors import (
    ApiError, not_found, invalid_request,
    ERR_TILL_SESSION_OPEN_EXISTS, ERR_TILL_INVALID_STATE, ERR_SALE_INVALID_STATE,
    ERR_SALE_VOID_WINDOW_CLOSED, ERR_FORBIDDEN_OWNERSHIP, ERR_ITEM_INVALID_STATE,
    ERR_SOD_APPROVER_IS_COUNTER, ERR_NOT_FOUND,
)
from middleware import require_roles, get_body, ALL_ROLES, paginate, query_filters, apply_filters
from response import success_object, success_list
from services import calc
from services.helpers import recompute_session_totals, recompute_batch_rollups

bp = Blueprint("till", __name__)


def session_view(s):
    return dict(s)


def sale_view(s):
    return dict(s)


def _get_session(session_id):
    s = db.till_sessions.get(session_id)
    if s is None:
        raise not_found("till session")
    return s


@bp.route("/api/till-sessions", methods=["POST"])
def open_session():
    user_id, role = require_roles(["Cashier"])
    payload = get_body(required=[("opening_float_cents", "integer")])
    if payload["opening_float_cents"] < 0:
        raise invalid_request("opening_float_cents must be >= 0")
    # uniqueness: at most one OPEN session per cashier
    for s in db.till_sessions.values():
        if s["cashier_worker_id"] == user_id and s["status"] == "OPEN":
            raise ApiError(ERR_TILL_SESSION_OPEN_EXISTS, 409,
                           "Cashier already has an OPEN till session")
    rec = new_record()
    rec.update({
        "cashier_worker_id": user_id,
        "opening_float_cents": payload["opening_float_cents"],
        "opened_at": iso_now(),
        "cash_sales_cents": 0,
        "card_sales_cents": 0,
        "expected_cash_cents": payload["opening_float_cents"],
        "counted_cash_cents": None,
        "over_short_cents": None,
        "status": "OPEN",
        "counted_by_user_id": None,
        "variance_approved_by_user_id": None,
        "closed_at": None,
    })
    db.till_sessions[rec["id"]] = rec
    return success_object(session_view(rec), status=201)


@bp.route("/api/till-sessions/<session_id>", methods=["GET"])
def get_session(session_id):
    require_roles(ALL_ROLES)
    return success_object(session_view(_get_session(session_id)))


@bp.route("/api/till-sessions", methods=["GET"])
def list_sessions():
    require_roles(ALL_ROLES)
    filters = query_filters(["cashier_worker_id", "status"])
    records = apply_filters(list(db.till_sessions.values()), filters)
    page, limit, offset, total = paginate(records)
    return success_list([session_view(s) for s in page], limit, offset, total)


@bp.route("/api/till-sessions/<session_id>/count", methods=["POST"])
def count_session(session_id):
    user_id, role = require_roles(["StoreManager"])
    payload = get_body(required=[("counted_cash_cents", "integer")])
    if payload["counted_cash_cents"] < 0:
        raise invalid_request("counted_cash_cents must be >= 0")
    session = _get_session(session_id)
    if session["status"] != "OPEN":
        raise ApiError(ERR_TILL_INVALID_STATE, 409,
                       "count requires an OPEN till session")
    recompute_session_totals(session)
    counted = payload["counted_cash_cents"]
    session["counted_cash_cents"] = counted
    session["counted_by_user_id"] = user_id
    session["over_short_cents"] = counted - session["expected_cash_cents"]
    # branch: |over_short| <= 500 auto-reconciles; >= 501 needs FinanceClerk approval
    if abs(session["over_short_cents"]) <= calc.AUTO_RECONCILE_MAX_CENTS:
        session["status"] = "RECONCILED"
    else:
        session["status"] = "PENDING_APPROVAL"
    touch(session)
    return success_object(session_view(session))


@bp.route("/api/till-sessions/<session_id>/approve-variance", methods=["POST"])
def approve_variance(session_id):
    user_id, role = require_roles(["FinanceClerk"])
    get_body()
    session = _get_session(session_id)
    if session["status"] != "PENDING_APPROVAL":
        raise ApiError(ERR_TILL_INVALID_STATE, 409,
                       "approve-variance requires a PENDING_APPROVAL session")
    if user_id == session["counted_by_user_id"]:
        raise ApiError(ERR_SOD_APPROVER_IS_COUNTER, 422,
                       "Variance approver must differ from the counter")
    session["variance_approved_by_user_id"] = user_id
    session["status"] = "RECONCILED"
    touch(session)
    return success_object(session_view(session))


@bp.route("/api/till-sessions/<session_id>/close", methods=["POST"])
def close_session(session_id):
    require_roles(["StoreManager"])
    get_body()
    session = _get_session(session_id)
    if session["status"] != "RECONCILED":
        raise ApiError(ERR_TILL_INVALID_STATE, 409,
                       "close requires a RECONCILED session")
    session["status"] = "CLOSED"
    session["closed_at"] = iso_now()
    touch(session)
    return success_object(session_view(session))


@bp.route("/api/sales", methods=["POST"])
def create_sale():
    user_id, role = require_roles(["Cashier"])
    payload = get_body(
        required=[("till_session_id", "string"), ("item_ids", "array"),
                  ("payment_method", "string")],
        enums={"payment_method": ["CASH", "CARD"]},
    )
    item_ids = payload["item_ids"]
    if len(item_ids) == 0:
        raise invalid_request("item_ids must be a non-empty array")
    for iid in item_ids:
        if not isinstance(iid, str):
            raise invalid_request("item_ids entries must be strings")
    # existence: session, then every item
    session = db.till_sessions.get(payload["till_session_id"])
    if session is None:
        raise not_found("till session")
    items = []
    for iid in item_ids:
        item = db.items.get(iid)
        if item is None:
            raise ApiError(ERR_NOT_FOUND, 404, "item not found: %s" % iid)
        items.append(item)
    # ownership: cashier must own the session
    if session["cashier_worker_id"] != user_id:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403,
                       "Cashier does not own this till session")
    # state: session OPEN; every item ON_FLOOR
    if session["status"] != "OPEN":
        raise ApiError(ERR_TILL_INVALID_STATE, 409,
                       "sale requires an OPEN till session")
    for item in items:
        if item["status"] != "ON_FLOOR":
            raise ApiError(ERR_ITEM_INVALID_STATE, 409,
                           "Every sale line must be ON_FLOOR")
    total = sum(i["current_price_cents"] for i in items)
    rec = new_record()
    rec.update({
        "till_session_id": session["id"],
        "payment_method": payload["payment_method"],
        "item_ids": list(item_ids),
        "line_count": len(item_ids),
        "total_cents": total,
        "status": "COMPLETED",
        "voided_by_user_id": None,
        "voided_at": None,
        "void_reason": None,
    })
    db.sales[rec["id"]] = rec
    sold_at = iso_now()
    for item in items:
        item["status"] = "SOLD"
        item["sale_id"] = rec["id"]
        item["sold_at"] = sold_at
        touch(item)
    # batch sold_item_count += 1 per line, batch version bump (once per batch)
    touched_batches = set()
    for item in items:
        batch = db.batches.get(item["batch_id"])
        if batch is not None:
            batch["sold_item_count"] += 1
            if batch["id"] not in touched_batches:
                touched_batches.add(batch["id"])
    for bid in touched_batches:
        touch(db.batches[bid])
    recompute_session_totals(session)
    touch(session)
    return success_object(sale_view(rec), status=201)


@bp.route("/api/sales/<sale_id>", methods=["GET"])
def get_sale(sale_id):
    require_roles(ALL_ROLES)
    s = db.sales.get(sale_id)
    if s is None:
        raise not_found("sale")
    return success_object(sale_view(s))


@bp.route("/api/sales", methods=["GET"])
def list_sales():
    require_roles(ALL_ROLES)
    filters = query_filters(["till_session_id", "status"])
    records = apply_filters(list(db.sales.values()), filters)
    page, limit, offset, total = paginate(records)
    return success_list([sale_view(s) for s in page], limit, offset, total)


@bp.route("/api/sales/<sale_id>/void", methods=["POST"])
def void_sale(sale_id):
    user_id, role = require_roles(["Cashier", "StoreManager"])
    payload = get_body(optional=[("reason", "string")])
    sale = db.sales.get(sale_id)
    if sale is None:
        raise not_found("sale")
    session = db.till_sessions.get(sale["till_session_id"])
    # priority 6: sale must be COMPLETED (outranks window checks)
    if sale["status"] != "COMPLETED":
        raise ApiError(ERR_SALE_INVALID_STATE, 409,
                       "Only a COMPLETED sale can be voided")
    # ownership/state per actor
    if role == "Cashier":
        if session is None or session["cashier_worker_id"] != user_id:
            raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403,
                           "Cashier may void only on their own session")
        if session["status"] != "OPEN":
            raise ApiError(ERR_TILL_INVALID_STATE, 409,
                           "Cashier may void only while the session is OPEN")
    else:  # StoreManager
        if session is not None and session["status"] == "CLOSED":
            raise ApiError(ERR_SALE_VOID_WINDOW_CLOSED, 422,
                           "The void window has closed (session CLOSED)")
    # temporal: void window — same UTC date as sale creation, session not CLOSED
    sale_date = parse_ts(sale["created_at"]).date()
    now_date = db.clock.now().date()
    if now_date != sale_date or (session is not None and session["status"] == "CLOSED"):
        raise ApiError(ERR_SALE_VOID_WINDOW_CLOSED, 422,
                       "Void attempted on a later UTC date than the sale or after session close")
    # compensation cascade
    sale["status"] = "VOIDED"
    sale["voided_by_user_id"] = user_id
    sale["voided_at"] = iso_now()
    sale["void_reason"] = payload.get("reason")
    touch(sale)
    touched_batches = set()
    for iid in sale["item_ids"]:
        item = db.items.get(iid)
        if item is not None and item["status"] == "SOLD":
            item["status"] = "ON_FLOOR"
            item["sale_id"] = None
            item["sold_at"] = None
            # current_price_cents / markdown_round immutable while SOLD — already exact
            touch(item)
            batch = db.batches.get(item["batch_id"])
            if batch is not None:
                batch["sold_item_count"] -= 1
                touched_batches.add(batch["id"])
    for bid in touched_batches:
        touch(db.batches[bid])
    if session is not None:
        recompute_session_totals(session)
        touch(session)
    return success_object(sale_view(sale))
