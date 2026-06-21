"""Settlement endpoints (PRD §3.9). Settlements are never created directly."""
from flask import Blueprint, request

import db
from errors import ApiError
from middleware import get_auth, require_role
from response import success_object, success_list
from services.common import touch, public, list_collection
from services import lookup, cascade

bp = Blueprint("settlements", __name__)

ALL_ROLES = {"AuctionAdmin", "Seller", "Buyer", "Arbitrator"}


@bp.route("/auction/settlements", methods=["GET"])
def list_settlements():
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    filters = {
        "lot_id": request.args.get("lot_id"),
        "buyer_id": request.args.get("buyer_id"),
        "seller_id": request.args.get("seller_id"),
        "status": request.args.get("status"),
    }
    items, limit, offset, total = list_collection(db.settlements, filters)
    return success_list(items, limit, offset, total)


@bp.route("/auction/settlements/<settlement_id>", methods=["GET"])
def get_settlement(settlement_id):
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    with db.lock:
        s = lookup.get_settlement(settlement_id)
        return success_object(public(s))


@bp.route("/auction/settlements/<settlement_id>/record-payment", methods=["POST"])
def record_payment(settlement_id):
    _, role = get_auth()
    require_role(role, {"AuctionAdmin"})
    with db.lock:
        s = lookup.get_settlement(settlement_id)
        if s["payment_status"] != "UNPAID":
            raise ApiError("ERR_SETTLEMENT_NOT_UNPAID", "Settlement not UNPAID.")
        lot = db.lots.get(s["lot_id"])
        if lot is None or lot["status"] != "HAMMERED":
            raise ApiError("ERR_LOT_NOT_HAMMERED", "Lot not HAMMERED.")
        s["payment_status"] = "PAID"
        touch(s)
        cascade.maybe_clear_settlement(s)
        return success_object(public(s))


@bp.route("/auction/settlements/<settlement_id>/record-title", methods=["POST"])
def record_title(settlement_id):
    _, role = get_auth()
    require_role(role, {"AuctionAdmin"})
    with db.lock:
        s = lookup.get_settlement(settlement_id)
        if s["title_status"] != "PENDING_TITLE":
            raise ApiError("ERR_TITLE_ALREADY_RECEIVED", "Title already received.")
        s["title_status"] = "TITLE_RECEIVED"
        touch(s)
        cascade.maybe_clear_settlement(s)
        return success_object(public(s))


@bp.route("/auction/settlements/<settlement_id>/write-off", methods=["POST"])
def write_off(settlement_id):
    _, role = get_auth()
    require_role(role, {"AuctionAdmin"})
    with db.lock:
        s = lookup.get_settlement(settlement_id)
        if s["payment_status"] != "UNPAID":
            raise ApiError("ERR_SETTLEMENT_NOT_UNPAID", "Settlement not UNPAID.")
        lot = db.lots.get(s["lot_id"])
        sale = db.sales.get(lot["sale_id"]) if lot else None
        if sale is None or sale["status"] != "CLOSED":
            raise ApiError("ERR_SALE_NOT_CLOSED", "Sale not CLOSED.")
        s["payment_status"] = "WRITTEN_OFF"
        s["status"] = "DEFAULTED"
        touch(s)
        # re-credit buyer + suspend
        buyer = db.buyers.get(s["buyer_id"])
        if buyer is not None:
            cascade.recompute_buyer_credit(buyer)
            buyer["status"] = "SUSPENDED"
            touch(buyer)
        return success_object(public(s))
