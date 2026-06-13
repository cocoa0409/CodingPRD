"""AuctionSale routes + nested lot cataloging/listing (PRD §3.3).

CATALOGING -> PUBLISHED -> LIVE -> CLOSED.
"""
from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import require_role, get_json_body
from response import object_response, array_response
from services.common import (
    serialize, require_string, require_int, require_bool, parse_pagination,
    paginate, validate_occ_field, match_occ,
)
from services.domain import (
    recompute_sale_lot_count, recompute_consignment_lot_count,
)

bp = Blueprint("auction_sales", __name__)

SALE_READ_ROLES = {
    "SaleAdministrator", "FinanceOfficer", "Auctioneer", "Seller", "Bidder", "Viewer",
}


@bp.route("/auction-sales", methods=["POST"])
def create_auction_sale():
    require_role({"SaleAdministrator"})
    body = get_json_body()
    title = require_string(body, "title")
    sale_date_utc = require_string(body, "sale_date_utc")
    currency = require_string(body, "currency")
    schedule_id = require_string(body, "buyers_premium_schedule_id")

    with db.LOCK:
        if schedule_id not in db.premium_schedules:
            raise err(errors.ERR_FK_NOT_FOUND, "buyers_premium_schedule_id does not resolve")
        common = db.new_common()
        record = {
            "id": common["id"],
            "created_at": common["created_at"],
            "updated_at": common["updated_at"],
            "version": common["version"],
            "_seq": common["_seq"],
            "title": title,
            "sale_date_utc": sale_date_utc,
            "currency": currency,
            "buyers_premium_schedule_id": schedule_id,
            "status": "CATALOGING",
            "lot_count": 0,
        }
        db.auction_sales[record["id"]] = record
        return object_response(serialize(record), 201)


@bp.route("/auction-sales/<id>", methods=["GET"])
def get_auction_sale(id):
    require_role(SALE_READ_ROLES)
    with db.LOCK:
        record = db.auction_sales.get(id)
        if record is None:
            raise err(errors.ERR_NOT_FOUND, "Auction sale not found")
        return object_response(serialize(record), 200)


@bp.route("/auction-sales", methods=["GET"])
def list_auction_sales():
    require_role({"SaleAdministrator", "FinanceOfficer", "Auctioneer", "Viewer"})
    with db.LOCK:
        limit, offset = parse_pagination(request.args)
        schedule_filter = request.args.get("buyers_premium_schedule_id")
        rows = list(db.auction_sales.values())
        if schedule_filter is not None:
            rows = [s for s in rows if s["buyers_premium_schedule_id"] == schedule_filter]
        items, total = paginate(rows, limit, offset)
        return array_response(items, limit, offset, total, 200)


@bp.route("/auction-sales/<id>/publish", methods=["POST"])
def publish_sale(id):
    require_role({"SaleAdministrator"})
    body = get_json_body()
    with db.LOCK:
        sale = db.auction_sales.get(id)
        if sale is None:
            raise err(errors.ERR_NOT_FOUND, "Auction sale not found")
        validate_occ_field(body, "expected_auction_sale_version", required=True)
        if sale["status"] != "CATALOGING":
            raise err(errors.ERR_INVALID_STATE, "Sale is not CATALOGING")
        # at least one non-WITHDRAWN lot
        non_withdrawn = [
            l for l in db.lots.values()
            if l["auction_sale_id"] == id and l["sale_status"] != "WITHDRAWN"
        ]
        if len(non_withdrawn) < 1:
            raise err(errors.ERR_LOTS_REQUIRED, "At least one non-withdrawn lot required")
        match_occ(sale, body, "expected_auction_sale_version")
        sale["status"] = "PUBLISHED"
        db.touch(sale)
        return object_response(serialize(sale), 200)


@bp.route("/auction-sales/<id>/open-bidding", methods=["POST"])
def open_bidding(id):
    require_role({"Auctioneer"})
    body = get_json_body()
    with db.LOCK:
        sale = db.auction_sales.get(id)
        if sale is None:
            raise err(errors.ERR_NOT_FOUND, "Auction sale not found")
        validate_occ_field(body, "expected_auction_sale_version", required=True)
        if sale["status"] != "PUBLISHED":
            raise err(errors.ERR_INVALID_STATE, "Sale is not PUBLISHED")
        match_occ(sale, body, "expected_auction_sale_version")
        # Cascade: every CATALOGED lot in this sale -> OPEN.
        for lot in db.lots.values():
            if lot["auction_sale_id"] == id and lot["sale_status"] == "CATALOGED":
                lot["sale_status"] = "OPEN"
                db.touch(lot)
        sale["status"] = "LIVE"
        db.touch(sale)
        return object_response(serialize(sale), 200)


@bp.route("/auction-sales/<id>/close", methods=["POST"])
def close_sale(id):
    require_role({"Auctioneer"})
    body = get_json_body()
    with db.LOCK:
        sale = db.auction_sales.get(id)
        if sale is None:
            raise err(errors.ERR_NOT_FOUND, "Auction sale not found")
        validate_occ_field(body, "expected_auction_sale_version", required=True)
        if sale["status"] != "LIVE":
            raise err(errors.ERR_INVALID_STATE, "Sale is not LIVE")
        # no OPEN lots remain
        for lot in db.lots.values():
            if lot["auction_sale_id"] == id and lot["sale_status"] == "OPEN":
                raise err(errors.ERR_SALE_NOT_EMPTY_OF_OPEN_LOTS,
                          "An OPEN lot remains in the sale")
        match_occ(sale, body, "expected_auction_sale_version")
        sale["status"] = "CLOSED"
        db.touch(sale)
        return object_response(serialize(sale), 200)


# --- Lot cataloging / listing nested under a sale ---------------------------

@bp.route("/auction-sales/<id>/lots", methods=["POST"])
def catalog_lot(id):
    require_role({"SaleAdministrator"})
    body = get_json_body()
    with db.LOCK:
        sale = db.auction_sales.get(id)
        if sale is None:
            raise err(errors.ERR_NOT_FOUND, "Auction sale not found")

        # body FKs
        consignment_id = require_string(body, "consignment_id")
        lot_number = require_int(body, "lot_number", minimum=0)
        title = require_string(body, "title")
        artist_name = require_string(body, "artist_name")
        artist_alive = require_bool(body, "artist_alive")
        low = require_int(body, "low_estimate_cents", minimum=0)
        high = require_int(body, "high_estimate_cents", minimum=0)
        reserve = require_int(body, "reserve_cents", minimum=0)

        if consignment_id not in db.consignments:
            raise err(errors.ERR_FK_NOT_FOUND, "consignment_id does not resolve")

        # Lot-term validity (priority 11): low > 0, low <= high, reserve <= low.
        if low <= 0 or low > high or reserve > low:
            raise err(errors.ERR_INVALID_LOT_TERMS, "Estimate/reserve ordering invalid")

        # Uniqueness (priority 13): lot_number unique among non-WITHDRAWN lots
        # in this sale.
        for lot in db.lots.values():
            if (lot["auction_sale_id"] == id and lot["sale_status"] != "WITHDRAWN"
                    and lot["lot_number"] == lot_number):
                raise err(errors.ERR_DUPLICATE, "Duplicate lot_number in sale")

        common = db.new_common()
        record = {
            "id": common["id"],
            "created_at": common["created_at"],
            "updated_at": common["updated_at"],
            "version": common["version"],
            "_seq": common["_seq"],
            "auction_sale_id": id,
            "consignment_id": consignment_id,
            "lot_number": lot_number,
            "title": title,
            "artist_name": artist_name,
            "artist_alive": artist_alive,
            "low_estimate_cents": low,
            "high_estimate_cents": high,
            "reserve_cents": reserve,
            "hammer_price_cents": 0,
            "winning_paddle_registration_id": None,
            "sale_status": "CATALOGED",
            "settlement_status": "NONE",
        }
        db.lots[record["id"]] = record
        recompute_sale_lot_count(id)
        recompute_consignment_lot_count(consignment_id)
        return object_response(serialize(record), 201)


@bp.route("/auction-sales/<id>/lots", methods=["GET"])
def list_sale_lots(id):
    user_id, role = require_role(SALE_READ_ROLES)
    with db.LOCK:
        sale = db.auction_sales.get(id)
        if sale is None:
            raise err(errors.ERR_NOT_FOUND, "Auction sale not found")
        limit, offset = parse_pagination(request.args)
        rows = [l for l in db.lots.values() if l["auction_sale_id"] == id]
        if role == "Seller":
            owned = _seller_consignment_ids(user_id)
            rows = [l for l in rows if l["consignment_id"] in owned]
        items, total = paginate(rows, limit, offset)
        return array_response(items, limit, offset, total, 200)


def _seller_consignment_ids(seller_id):
    return {c["id"] for c in db.consignments.values() if c["seller_id"] == seller_id}


@bp.route("/auction-sales/<id>/paddle-registrations", methods=["GET"])
def list_sale_paddles(id):
    require_role({"SaleAdministrator", "FinanceOfficer", "Auctioneer", "Viewer"})
    with db.LOCK:
        sale = db.auction_sales.get(id)
        if sale is None:
            raise err(errors.ERR_NOT_FOUND, "Auction sale not found")
        limit, offset = parse_pagination(request.args)
        rows = [p for p in db.paddle_registrations.values()
                if p["auction_sale_id"] == id]
        items, total = paginate(rows, limit, offset)
        return array_response(items, limit, offset, total, 200)
