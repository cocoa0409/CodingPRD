"""Lot routes: read/list and sale-status transitions (PRD §3.3, §3.5, §3.9).

sale_status: CATALOGED -> OPEN -> SOLD|BOUGHT_IN; CATALOGED -> WITHDRAWN.
Knock-down and reverse-sale carry the settlement compensation logic.
"""
from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import require_role, get_json_body
from response import object_response, array_response
from services.common import (
    serialize, parse_pagination, paginate, validate_occ_field, match_occ,
)
from services.domain import (
    recompute_sale_lot_count, recompute_consignment_lot_count,
    recompute_bidder_outstanding, standing_high_bid,
)

bp = Blueprint("lots", __name__)

LOT_READ_ROLES = {
    "SaleAdministrator", "FinanceOfficer", "Auctioneer", "Seller", "Bidder", "Viewer",
}


def _seller_owns_lot(role, user_id, lot):
    if role != "Seller":
        return
    cons = db.consignments.get(lot["consignment_id"])
    if cons is None or cons["seller_id"] != user_id:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Not the owning seller for this lot")


@bp.route("/lots/<id>", methods=["GET"])
def get_lot(id):
    user_id, role = require_role(LOT_READ_ROLES)
    with db.LOCK:
        lot = db.lots.get(id)
        if lot is None:
            raise err(errors.ERR_NOT_FOUND, "Lot not found")
        _seller_owns_lot(role, user_id, lot)
        return object_response(serialize(lot), 200)


@bp.route("/lots", methods=["GET"])
def list_lots():
    user_id, role = require_role(
        {"SaleAdministrator", "FinanceOfficer", "Seller", "Viewer"})
    with db.LOCK:
        limit, offset = parse_pagination(request.args)
        consignment_filter = request.args.get("consignment_id")
        rows = list(db.lots.values())
        if consignment_filter is not None:
            rows = [l for l in rows if l["consignment_id"] == consignment_filter]
        if role == "Seller":
            owned = {c["id"] for c in db.consignments.values()
                     if c["seller_id"] == user_id}
            rows = [l for l in rows if l["consignment_id"] in owned]
        items, total = paginate(rows, limit, offset)
        return array_response(items, limit, offset, total, 200)


@bp.route("/lots/<id>/withdraw", methods=["POST"])
def withdraw_lot(id):
    require_role({"SaleAdministrator"})
    body = get_json_body()
    with db.LOCK:
        lot = db.lots.get(id)
        if lot is None:
            raise err(errors.ERR_NOT_FOUND, "Lot not found")
        validate_occ_field(body, "expected_lot_version", required=True)
        if lot["sale_status"] != "CATALOGED":
            raise err(errors.ERR_INVALID_STATE, "Lot is not CATALOGED")
        match_occ(lot, body, "expected_lot_version")
        lot["sale_status"] = "WITHDRAWN"
        db.touch(lot)
        recompute_sale_lot_count(lot["auction_sale_id"])
        recompute_consignment_lot_count(lot["consignment_id"])
        return object_response(serialize(lot), 200)


@bp.route("/lots/<id>/open", methods=["POST"])
def open_lot(id):
    require_role({"Auctioneer"})
    body = get_json_body()
    with db.LOCK:
        lot = db.lots.get(id)
        if lot is None:
            raise err(errors.ERR_NOT_FOUND, "Lot not found")
        validate_occ_field(body, "expected_lot_version", required=True)
        # single-entity precondition first (ERR_INVALID_STATE)
        if lot["sale_status"] != "CATALOGED":
            raise err(errors.ERR_INVALID_STATE, "Lot is not CATALOGED")
        # cross-entity dependency: sale must be LIVE (ERR_DEPENDENCY_NOT_READY)
        sale = db.auction_sales.get(lot["auction_sale_id"])
        if sale is None or sale["status"] != "LIVE":
            raise err(errors.ERR_DEPENDENCY_NOT_READY, "Sale is not LIVE")
        match_occ(lot, body, "expected_lot_version")
        lot["sale_status"] = "OPEN"
        db.touch(lot)
        return object_response(serialize(lot), 200)


@bp.route("/lots/<id>/knock-down", methods=["POST"])
def knock_down_lot(id):
    require_role({"Auctioneer"})
    body = get_json_body()
    with db.LOCK:
        lot = db.lots.get(id)
        if lot is None:
            raise err(errors.ERR_NOT_FOUND, "Lot not found")
        validate_occ_field(body, "expected_lot_version", required=True)
        if lot["sale_status"] != "OPEN":
            raise err(errors.ERR_INVALID_STATE, "Lot is not OPEN")
        sale = db.auction_sales.get(lot["auction_sale_id"])
        if sale is None or sale["status"] != "LIVE":
            raise err(errors.ERR_DEPENDENCY_NOT_READY, "Sale is not LIVE")
        # OCC guard (priority 9, required for this write)
        match_occ(lot, body, "expected_lot_version")

        high = standing_high_bid(id, statuses=("ACCEPTED",))
        if high is not None and high["amount_cents"] >= lot["reserve_cents"]:
            # SOLD
            lot["sale_status"] = "SOLD"
            lot["hammer_price_cents"] = high["amount_cents"]
            lot["winning_paddle_registration_id"] = high["paddle_registration_id"]
            high["status"] = "WINNING"
            db.touch(high)
            db.touch(lot)
        else:
            # BOUGHT_IN
            lot["sale_status"] = "BOUGHT_IN"
            db.touch(lot)
        return object_response(serialize(lot), 200)


@bp.route("/lots/<id>/buy-in", methods=["POST"])
def buy_in_lot(id):
    require_role({"Auctioneer"})
    body = get_json_body()
    with db.LOCK:
        lot = db.lots.get(id)
        if lot is None:
            raise err(errors.ERR_NOT_FOUND, "Lot not found")
        validate_occ_field(body, "expected_lot_version", required=True)
        if lot["sale_status"] != "OPEN":
            raise err(errors.ERR_INVALID_STATE, "Lot is not OPEN")
        sale = db.auction_sales.get(lot["auction_sale_id"])
        if sale is None or sale["status"] != "LIVE":
            raise err(errors.ERR_DEPENDENCY_NOT_READY, "Sale is not LIVE")
        match_occ(lot, body, "expected_lot_version")
        lot["sale_status"] = "BOUGHT_IN"
        db.touch(lot)
        return object_response(serialize(lot), 200)


@bp.route("/lots/<id>/reverse-sale", methods=["POST"])
def reverse_sale(id):
    require_role({"FinanceOfficer"})
    body = get_json_body()
    with db.LOCK:
        lot = db.lots.get(id)
        if lot is None:
            raise err(errors.ERR_NOT_FOUND, "Lot not found")
        validate_occ_field(body, "expected_lot_version", required=True)
        match_occ(lot, body, "expected_lot_version")

        # Guard: if the lot's seller statement is already PAID/disbursed,
        # reject the whole reverse-sale; no side effects fire.
        for s in db.seller_statements.values():
            if s["lot_id"] == id and s["status"] == "PAID":
                raise err(errors.ERR_STATEMENT_ALREADY_PAID,
                          "Statement already disbursed; cannot reverse")

        # Compensate the financial trail.
        # ISSUED Invoice -> VOID; decrease bidder outstanding by total_due.
        for inv in db.invoices.values():
            if inv["lot_id"] == id and inv["status"] == "ISSUED":
                inv["status"] = "VOID"
                db.touch(inv)
                recompute_bidder_outstanding(inv["bidder_id"])

        # ACCRUED ResaleRoyalty -> REVERSED.
        for roy in db.resale_royalties.values():
            if roy["lot_id"] == id and roy["status"] == "ACCRUED":
                roy["status"] = "REVERSED"
                db.touch(roy)

        # PENDING SellerStatement -> REVERSED.
        for s in db.seller_statements.values():
            if s["lot_id"] == id and s["status"] == "PENDING":
                s["status"] = "REVERSED"
                db.touch(s)

        lot["settlement_status"] = "NONE"
        db.touch(lot)
        return object_response(serialize(lot), 200)
