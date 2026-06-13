"""Auction endpoints: schedule, open, sweep, record/void sale, settle, cancel."""
from flask import Blueprint, request

import db
from clock import iso, now, parse_iso
from errors import ApiError
from middleware import get_json_body, require_role, require_user_context
from response import object_response
from services import auctions as auction_svc
from services import orders as order_svc
from services.serialize import public
from validators import (paginate_and_respond, require_int, require_str,
                        sort_by_created)

bp = Blueprint("auctions", __name__)


def get_auction_or_404(aid):
    a = db.auctions.get(aid)
    if a is None:
        raise ApiError("ERR_NOT_FOUND", "Auction not found")
    return a


def _windows_overlap(s1, e1, s2, e2):
    # Half-open / closed interval overlap: any shared instant counts.
    return s1 < e2 and s2 < e1


@bp.route("/auctions", methods=["POST"])
def create_auction():
    user_id, role = require_user_context()
    require_role(role, {"AuctionOfficial", "LotOperator"})
    body = get_json_body()
    # existence (priority 3) before body well-formedness (priority 4)
    if body.get("lot_id") is None:
        raise ApiError("ERR_INVALID_REQUEST", "Missing required field: lot_id")
    lot = db.impound_lots.get(body.get("lot_id"))
    if lot is None:
        raise ApiError("ERR_NOT_FOUND", "Impound lot not found")
    lot_id = require_str(body, "lot_id")
    window_start_raw = require_str(body, "window_start")
    window_end_raw = require_str(body, "window_end")
    ws = parse_iso(window_start_raw)
    we = parse_iso(window_end_raw)
    if ws is None or we is None:
        raise ApiError("ERR_INVALID_REQUEST", "window_start / window_end must be ISO 8601")
    if not (we > ws):
        raise ApiError("ERR_INVALID_REQUEST", "window_end must be after window_start")
    # no-overlap rule (priority 14) against non-cancelled auctions on the same lot
    for other in db.auctions.values():
        if other["lot_id"] != lot_id or other["status"] == "CANCELLED":
            continue
        o_ws = other["_window_start_dt"]
        o_we = other["_window_end_dt"]
        if _windows_overlap(ws, we, o_ws, o_we):
            raise ApiError("ERR_AUCTION_WINDOW_OVERLAP", "Auction window overlaps an existing window")
    auction = {
        "lot_id": lot_id,
        "window_start": iso(ws),
        "window_end": iso(we),
        "gross_proceeds_cents": 0,
        "distributed_cents": 0,
        "lien_payoff_cents": 0,
        "surplus_to_owner_cents": 0,
        "status": "SCHEDULED",
        "_window_start_dt": ws,
        "_window_end_dt": we,
    }
    db.stamp_create(auction)
    db.auctions[auction["id"]] = auction
    return object_response(public(auction), 201)


@bp.route("/auctions/<aid>", methods=["GET"])
def get_auction(aid):
    user_id, role = require_user_context()
    require_role(role, {"AuctionOfficial", "LotOperator"})
    a = get_auction_or_404(aid)
    return object_response(public(a), 200)


@bp.route("/auctions", methods=["GET"])
def list_auctions():
    user_id, role = require_user_context()
    require_role(role, {"AuctionOfficial", "LotOperator"})
    items = list(db.auctions.values())
    lot_id = request.args.get("lot_id")
    status = request.args.get("status")
    if lot_id is not None:
        items = [a for a in items if a["lot_id"] == lot_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items = sort_by_created(items)
    return paginate_and_respond([public(a) for a in items])


@bp.route("/auctions/<aid>/tow-orders", methods=["GET"])
def list_auction_orders(aid):
    user_id, role = require_user_context()
    require_role(role, {"AuctionOfficial", "LotOperator"})
    get_auction_or_404(aid)
    items = [o for o in db.tow_orders.values() if o.get("auction_id") == aid]
    status = request.args.get("status")
    if status is not None:
        items = [o for o in items if o["status"] == status]
    items = sort_by_created(items)
    from routes.tow_orders import serialize_order
    return paginate_and_respond([serialize_order(o) for o in items])


@bp.route("/auctions/<aid>/open", methods=["POST"])
def open_auction(aid):
    user_id, role = require_user_context()
    require_role(role, {"AuctionOfficial"})
    a = get_auction_or_404(aid)
    if a["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Auction is not SCHEDULED")
    if now() < a["_window_start_dt"]:
        raise ApiError("ERR_AUCTION_WINDOW_NOT_STARTED", "Auction window has not started")
    a["status"] = "OPEN"
    db.touch(a)
    return object_response(public(a), 200)


@bp.route("/auctions/<aid>/sweep", methods=["POST"])
def sweep(aid):
    user_id, role = require_user_context()
    require_role(role, {"AuctionOfficial", "LotOperator"})
    a = get_auction_or_404(aid)
    body = get_json_body()
    tow_order_id = require_str(body, "tow_order_id")
    order = db.tow_orders.get(tow_order_id)
    if order is None:
        raise ApiError("ERR_NOT_FOUND", "Tow order not found")
    if order["status"] != "AUCTION_ELIGIBLE":
        raise ApiError("ERR_INVALID_STATE", "Order is not AUCTION_ELIGIBLE")
    if order["hold_status"] != "NONE":
        raise ApiError("ERR_HOLD_ACTIVE", "An active hold blocks sweep")
    order["auction_id"] = aid
    db.touch(order)
    from routes.tow_orders import serialize_order
    return object_response(serialize_order(order), 200)


@bp.route("/auctions/<aid>/record-sale", methods=["POST"])
def record_sale(aid):
    user_id, role = require_user_context()
    require_role(role, {"AuctionOfficial"})
    a = get_auction_or_404(aid)
    body = get_json_body()
    tow_order_id = require_str(body, "tow_order_id")
    # existence (priority 3) before remaining body well-formedness (priority 4)
    order = db.tow_orders.get(tow_order_id)
    if order is None:
        raise ApiError("ERR_NOT_FOUND", "Tow order not found")
    sale_price = require_int(body, "sale_price_cents", minimum=0)
    if order["status"] != "AUCTION_ELIGIBLE":
        raise ApiError("ERR_INVALID_STATE", "Order is not AUCTION_ELIGIBLE")
    if order.get("auction_id") != aid:
        raise ApiError("ERR_NOT_IN_AUCTION", "Order is not swept into this auction")
    if order["hold_status"] != "NONE":
        raise ApiError("ERR_HOLD_ACTIVE", "An active hold blocks sale")
    # Finalize accrued storage (freeze instant already set on mark-auction-eligible).
    order_svc.recompute(order)
    lot = order_svc.lot_of(order)
    # Write SETTLEMENT ledger entry finalizing accrued_storage_cents.
    settle_dt = now()
    entry = {
        "tow_order_id": order["id"],
        "segment_start": order.get("accrual_frozen_at") or iso(settle_dt),
        "segment_end": iso(settle_dt),
        "days_counted": 0,
        "segment_charge_cents": 0,
        "kind": "SETTLEMENT",
        "_accrual_kind": None,
        "_segment_start_dt": order.get("_accrual_frozen_dt") or settle_dt,
        "_segment_end_dt": settle_dt,
    }
    entry["id"] = db.new_id()
    entry["created_at"] = iso(now())
    entry["_seq"] = db.next_seq()
    db.ledger_entries[entry["id"]] = entry
    order["_settlement_ledger_id"] = entry["id"]
    order["_sale_price_cents"] = sale_price
    order["status"] = "AUCTIONED"
    db.touch(order)
    auction_svc.recompute_distribution(a)
    db.touch(a)
    from routes.tow_orders import serialize_order
    return object_response(serialize_order(order), 200)


@bp.route("/auctions/<aid>/void-sale", methods=["POST"])
def void_sale(aid):
    user_id, role = require_user_context()
    require_role(role, {"AuctionOfficial"})
    a = get_auction_or_404(aid)
    body = get_json_body()
    tow_order_id = require_str(body, "tow_order_id")
    order = db.tow_orders.get(tow_order_id)
    if order is None:
        raise ApiError("ERR_NOT_FOUND", "Tow order not found")
    if order.get("auction_id") != aid:
        raise ApiError("ERR_NOT_IN_AUCTION", "Order is not in this auction")
    if order["status"] != "AUCTIONED":
        raise ApiError("ERR_INVALID_STATE", "Order is not AUCTIONED")
    # Remove the SETTLEMENT ledger entry, revert order to AUCTION_ELIGIBLE.
    sid = order.get("_settlement_ledger_id")
    if sid is not None and sid in db.ledger_entries:
        del db.ledger_entries[sid]
    order["_settlement_ledger_id"] = None
    order["_sale_price_cents"] = 0
    order["status"] = "AUCTION_ELIGIBLE"
    db.touch(order)
    auction_svc.recompute_distribution(a)
    db.touch(a)
    from routes.tow_orders import serialize_order
    return object_response(serialize_order(order), 200)


@bp.route("/auctions/<aid>/settle", methods=["POST"])
def settle(aid):
    user_id, role = require_user_context()
    require_role(role, {"AuctionOfficial"})
    a = get_auction_or_404(aid)
    if a["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Auction is not OPEN")
    auction_svc.recompute_distribution(a)
    a["status"] = "SETTLED"
    db.touch(a)
    return object_response(public(a), 200)


@bp.route("/auctions/<aid>/cancel", methods=["POST"])
def cancel(aid):
    user_id, role = require_user_context()
    require_role(role, {"AuctionOfficial"})
    a = get_auction_or_404(aid)
    if a["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Auction is not SCHEDULED")
    # Unlink any swept orders (auction_id -> null), leave them AUCTION_ELIGIBLE.
    for order in db.tow_orders.values():
        if order.get("auction_id") == aid:
            order["auction_id"] = None
            db.touch(order)
    a["status"] = "CANCELLED"
    db.touch(a)
    return object_response(public(a), 200)
