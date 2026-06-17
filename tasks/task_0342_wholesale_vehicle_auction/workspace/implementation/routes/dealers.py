"""Seller and Buyer endpoints (PRD §3.2)."""
from flask import Blueprint, request

import db
from errors import ApiError
from middleware import get_auth, require_role
from response import success_object, success_list
from services.common import (
    base_record, touch, get_body, require_str, require_int, optional_number,
    public, list_collection,
)
from services import lookup

bp = Blueprint("dealers", __name__)


# ===== Seller ===============================================================
@bp.route("/auction/sellers", methods=["POST"])
def create_seller():
    _, role = get_auth()
    require_role(role, {"AuctionAdmin"})
    body = get_body()
    dealer_name = require_str(body, "dealer_name")
    seller_fee_pct = optional_number(body, "seller_fee_pct", default=0.02, minimum=0, maximum=0.10)
    with db.lock:
        rec = base_record()
        rec.update({
            "dealer_name": dealer_name,
            "seller_fee_pct": seller_fee_pct,
            "status": "ACTIVE",
        })
        db.sellers[rec["id"]] = rec
        return success_object(public(rec), 201)


@bp.route("/auction/sellers", methods=["GET"])
def list_sellers():
    _, role = get_auth()
    require_role(role, {"AuctionAdmin", "Seller"})
    filters = {"status": request.args.get("status")}
    items, limit, offset, total = list_collection(db.sellers, filters)
    return success_list(items, limit, offset, total)


@bp.route("/auction/sellers/<seller_id>", methods=["GET"])
def get_seller(seller_id):
    _, role = get_auth()
    require_role(role, {"AuctionAdmin", "Seller"})
    with db.lock:
        seller = lookup.get_seller(seller_id)
        return success_object(public(seller))


@bp.route("/auction/sellers/<seller_id>/suspend", methods=["POST"])
def suspend_seller(seller_id):
    _, role = get_auth()
    require_role(role, {"AuctionAdmin"})
    with db.lock:
        seller = lookup.get_seller(seller_id)
        seller["status"] = "SUSPENDED"
        touch(seller)
        return success_object(public(seller))


@bp.route("/auction/sellers/<seller_id>/reinstate", methods=["POST"])
def reinstate_seller(seller_id):
    _, role = get_auth()
    require_role(role, {"AuctionAdmin"})
    with db.lock:
        seller = lookup.get_seller(seller_id)
        seller["status"] = "ACTIVE"
        touch(seller)
        return success_object(public(seller))


# ===== Buyer ================================================================
@bp.route("/auction/buyers", methods=["POST"])
def create_buyer():
    _, role = get_auth()
    require_role(role, {"AuctionAdmin"})
    body = get_body()
    dealer_name = require_str(body, "dealer_name")
    credit_limit = require_int(body, "credit_limit_cents", minimum=0)
    with db.lock:
        rec = base_record()
        rec.update({
            "dealer_name": dealer_name,
            "credit_limit_cents": credit_limit,
            "committed_cents": 0,
            "available_credit_cents": credit_limit,
            "status": "ACTIVE",
        })
        db.buyers[rec["id"]] = rec
        return success_object(public(rec), 201)


@bp.route("/auction/buyers", methods=["GET"])
def list_buyers():
    _, role = get_auth()
    require_role(role, {"AuctionAdmin", "Buyer"})
    filters = {"status": request.args.get("status")}
    items, limit, offset, total = list_collection(db.buyers, filters)
    return success_list(items, limit, offset, total)


@bp.route("/auction/buyers/<buyer_id>", methods=["GET"])
def get_buyer(buyer_id):
    _, role = get_auth()
    require_role(role, {"AuctionAdmin", "Buyer"})
    with db.lock:
        buyer = lookup.get_buyer(buyer_id)
        return success_object(public(buyer))


@bp.route("/auction/buyers/<buyer_id>/suspend", methods=["POST"])
def suspend_buyer(buyer_id):
    _, role = get_auth()
    require_role(role, {"AuctionAdmin"})
    with db.lock:
        buyer = lookup.get_buyer(buyer_id)
        buyer["status"] = "SUSPENDED"
        touch(buyer)
        return success_object(public(buyer))


@bp.route("/auction/buyers/<buyer_id>/reinstate", methods=["POST"])
def reinstate_buyer(buyer_id):
    _, role = get_auth()
    require_role(role, {"AuctionAdmin"})
    with db.lock:
        buyer = lookup.get_buyer(buyer_id)
        buyer["status"] = "ACTIVE"
        touch(buyer)
        return success_object(public(buyer))
