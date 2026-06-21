"""AuctionSale and Lane endpoints (PRD §3.1)."""
from flask import Blueprint

import db
from errors import ApiError
from middleware import get_auth, require_role
from response import success_object, success_list
from services.common import (
    base_record, touch, get_body, require_str, require_int, public,
    list_collection,
)
from services import lookup, cascade

bp = Blueprint("sales", __name__)

ALL_ROLES = {"AuctionAdmin", "Seller", "Buyer", "Arbitrator"}


# ===== AuctionSale ==========================================================
@bp.route("/auction/sales", methods=["POST"])
def create_sale():
    _, role = get_auth()
    require_role(role, {"AuctionAdmin"})
    body = get_body()
    sale_name = require_str(body, "sale_name")
    sale_date = require_str(body, "sale_date")
    schedule = body.get("buyer_fee_schedule_code", "STANDARD")
    if schedule is None:
        schedule = "STANDARD"
    if schedule not in ("STANDARD", "PREMIUM"):
        raise ApiError("ERR_VALIDATION", "buyer_fee_schedule_code invalid.")

    with db.lock:
        rec = base_record()
        rec.update({
            "sale_name": sale_name,
            "sale_date": sale_date,
            "buyer_fee_schedule_code": schedule,
            "status": "DRAFT",
            "lane_count": 0,
        })
        db.sales[rec["id"]] = rec
        return success_object(public(rec), 201)


@bp.route("/auction/sales", methods=["GET"])
def list_sales():
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    from flask import request
    filters = {"status": request.args.get("status")}
    items, limit, offset, total = list_collection(db.sales, filters)
    return success_list(items, limit, offset, total)


@bp.route("/auction/sales/<sale_id>", methods=["GET"])
def get_sale(sale_id):
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    with db.lock:
        sale = lookup.get_sale(sale_id)
        return success_object(public(sale))


def _transition_sale(sale_id, expected, new_status, err, extra=None):
    with db.lock:
        sale = lookup.get_sale(sale_id)
        if sale["status"] != expected:
            raise ApiError(err, "Sale not in %s." % expected)
        if extra:
            extra(sale)
        sale["status"] = new_status
        touch(sale)
        return success_object(public(sale))


@bp.route("/auction/sales/<sale_id>/open", methods=["POST"])
def open_sale(sale_id):
    _, role = get_auth()
    require_role(role, {"AuctionAdmin"})
    return _transition_sale(sale_id, "DRAFT", "OPEN", "ERR_SALE_NOT_IN_DRAFT")


@bp.route("/auction/sales/<sale_id>/start", methods=["POST"])
def start_sale(sale_id):
    _, role = get_auth()
    require_role(role, {"AuctionAdmin"})

    def precheck(sale):
        lanes = [l for l in db.lanes.values()
                 if l["sale_id"] == sale["id"] and l["status"] in ("PLANNED", "ACTIVE")]
        if not lanes:
            raise ApiError("ERR_NO_LANES", "No lanes for this sale.")
        for l in db.lanes.values():
            if l["sale_id"] == sale["id"] and l["status"] == "PLANNED":
                l["status"] = "ACTIVE"
                touch(l)

    return _transition_sale(sale_id, "OPEN", "RUNNING", "ERR_SALE_NOT_OPEN", precheck)


@bp.route("/auction/sales/<sale_id>/close", methods=["POST"])
def close_sale(sale_id):
    _, role = get_auth()
    require_role(role, {"AuctionAdmin"})

    def precheck(sale):
        for lot in db.lots.values():
            if lot["sale_id"] == sale["id"] and lot["status"] == "BIDDING_OPEN":
                raise ApiError("ERR_LOTS_STILL_LIVE", "A lot is still live.")
        for l in db.lanes.values():
            if l["sale_id"] == sale["id"] and l["status"] == "ACTIVE":
                l["status"] = "CLOSED"
                touch(l)

    return _transition_sale(sale_id, "RUNNING", "CLOSED", "ERR_SALE_NOT_RUNNING", precheck)


@bp.route("/auction/sales/<sale_id>/settle", methods=["POST"])
def settle_sale(sale_id):
    _, role = get_auth()
    require_role(role, {"AuctionAdmin"})

    def precheck(sale):
        for s in db.settlements.values():
            lot = db.lots.get(s["lot_id"])
            if lot is None or lot.get("sale_id") != sale["id"]:
                continue
            if s["status"] not in ("CLEARED", "VOID", "DEFAULTED"):
                raise ApiError("ERR_UNSETTLED_LOTS_EXIST", "Unsettled lots exist.")

    return _transition_sale(sale_id, "CLOSED", "SETTLED", "ERR_SALE_NOT_CLOSED", precheck)


# ===== Lane =================================================================
@bp.route("/auction/lanes", methods=["POST"])
def create_lane():
    _, role = get_auth()
    require_role(role, {"AuctionAdmin"})
    body = get_body()
    sale_id = require_str(body, "sale_id")
    lane_number = require_int(body, "lane_number", positive=True)
    open_minute = require_int(body, "open_minute", minimum=0)
    close_minute = require_int(body, "close_minute")
    if not (open_minute < close_minute):
        raise ApiError("ERR_VALIDATION", "Invalid lane window.")

    with db.lock:
        sale = lookup.get_sale(sale_id)
        # uniqueness of (sale_id, lane_number)
        for l in db.lanes.values():
            if l["sale_id"] == sale_id and l["lane_number"] == lane_number and l["status"] != "ARCHIVED":
                raise ApiError("ERR_DUPLICATE_LANE_NUMBER", "Lane number already used.")
        rec = base_record()
        rec.update({
            "sale_id": sale_id,
            "lane_number": lane_number,
            "open_minute": open_minute,
            "close_minute": close_minute,
            "scheduled_slot_count": 0,
            "status": "PLANNED",
        })
        db.lanes[rec["id"]] = rec
        cascade.recompute_sale_lane_count(sale)
        return success_object(public(rec), 201)


@bp.route("/auction/lanes", methods=["GET"])
def list_lanes():
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    from flask import request
    filters = {"sale_id": request.args.get("sale_id"), "status": request.args.get("status")}
    items, limit, offset, total = list_collection(db.lanes, filters)
    return success_list(items, limit, offset, total)


@bp.route("/auction/lanes/<lane_id>", methods=["GET"])
def get_lane(lane_id):
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    with db.lock:
        lane = lookup.get_lane(lane_id)
        return success_object(public(lane))


@bp.route("/auction/lanes/<lane_id>/archive", methods=["POST"])
def archive_lane(lane_id):
    _, role = get_auth()
    require_role(role, {"AuctionAdmin"})
    with db.lock:
        lane = lookup.get_lane(lane_id)
        if lane["status"] != "PLANNED":
            raise ApiError("ERR_LANE_NOT_PLANNED", "Lane not PLANNED.")
        if lane["scheduled_slot_count"] != 0:
            raise ApiError("ERR_LANE_HAS_LOTS", "Lane has lots.")
        lane["status"] = "ARCHIVED"
        touch(lane)
        sale = db.sales.get(lane["sale_id"])
        if sale is not None:
            cascade.recompute_sale_lane_count(sale)
        return success_object(public(lane))
