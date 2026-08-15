"""Spot sale endpoints (PRD §3.7)."""

from flask import Blueprint, request

from db import store
from middleware import require_roles, ALL_ROLES, ROLE_CONTRACT_MANAGER
from response import success_object, success_list, parse_pagination
from util import get_body, check_unknown_fields, req_str, req_int
from errors import (
    invalid_state, ApiError, ERR_SAMPLE_NOT_SELECTED, ERR_CREDIT_LIMIT_EXCEEDED,
)
from services.core import (
    base_record, touch, public, get_spot_sale, get_pellet_lot,
    filtered_sorted, SALE_STATUSES,
)

bp = Blueprint("spot_sales", __name__)

CM = [ROLE_CONTRACT_MANAGER]


@bp.route("/api/spot-sales", methods=["POST"])
def create_spot_sale():
    require_roles(CM)
    body = get_body()
    check_unknown_fields(body, {"pellet_lot_id", "buyer_name",
                                "price_cents_per_lb", "buyer_credit_limit_cents"})
    pellet_lot_id = req_str(body, "pellet_lot_id")
    buyer_name = req_str(body, "buyer_name")
    price = req_int(body, "price_cents_per_lb", min_v=1)
    credit = req_int(body, "buyer_credit_limit_cents", min_v=0)

    pellet = get_pellet_lot(pellet_lot_id)
    # whole-lot commitment: the lot must be AVAILABLE
    if pellet["inventory_status"] != "AVAILABLE":
        raise invalid_state("Pellet lot is not AVAILABLE")

    rec = base_record()
    rec.update({
        "pellet_lot_id": pellet_lot_id,
        "buyer_name": buyer_name,
        "price_cents_per_lb": price,
        "buyer_credit_limit_cents": credit,
        "qty_lbs": pellet["qty_lbs"],
        "sale_total_cents": None,
        "status": "DRAFT",
    })
    store.spot_sales[rec["id"]] = rec
    pellet["inventory_status"] = "RESERVED"
    touch(pellet)
    return success_object(public(rec), status=201)


@bp.route("/api/spot-sales/<sale_id>", methods=["GET"])
def get_spot_sale_endpoint(sale_id):
    require_roles(ALL_ROLES)
    return success_object(public(get_spot_sale(sale_id)))


@bp.route("/api/spot-sales", methods=["GET"])
def list_spot_sales():
    require_roles(ALL_ROLES)
    records = filtered_sorted(list(store.spot_sales.values()), request.args, {
        "pellet_lot_id": ("str", "pellet_lot_id"),
        "status": ("enum", "status", SALE_STATUSES),
    })
    limit, offset = parse_pagination(request.args)
    total = len(records)
    page = records[offset:offset + limit]
    return success_list([public(r) for r in page], limit, offset, total)


@bp.route("/api/spot-sales/<sale_id>/confirm", methods=["POST"])
def confirm_spot_sale(sale_id):
    require_roles(CM)
    check_unknown_fields(get_body(), set())
    sale = get_spot_sale(sale_id)
    if sale["status"] != "DRAFT":
        raise invalid_state("Spot sale is not DRAFT")

    # quality gate first (priority 11), then the fiscal gate (priority 13)
    selected = any(
        s["pellet_lot_id"] == sale["pellet_lot_id"]
        and s["brewery_name"] == sale["buyer_name"]
        and s["status"] == "SELECTED"
        for s in store.samples.values())
    if not selected:
        raise ApiError(ERR_SAMPLE_NOT_SELECTED, 422,
                       "No SELECTED sample exists for this pellet lot and buyer")
    total = sale["qty_lbs"] * sale["price_cents_per_lb"]
    if total > sale["buyer_credit_limit_cents"]:
        raise ApiError(ERR_CREDIT_LIMIT_EXCEEDED, 422,
                       "Sale total exceeds the buyer credit limit")

    sale["sale_total_cents"] = total
    sale["status"] = "CONFIRMED"
    touch(sale)
    pellet = store.pellet_lots.get(sale["pellet_lot_id"])
    if pellet is not None and pellet["inventory_status"] == "RESERVED":
        pellet["inventory_status"] = "SOLD"
        touch(pellet)
    return success_object(public(sale))


@bp.route("/api/spot-sales/<sale_id>/cancel", methods=["POST"])
def cancel_spot_sale(sale_id):
    require_roles(CM)
    check_unknown_fields(get_body(), set())
    sale = get_spot_sale(sale_id)
    if sale["status"] != "DRAFT":
        raise invalid_state("Spot sale is not DRAFT")
    sale["status"] = "CANCELLED"
    touch(sale)
    pellet = store.pellet_lots.get(sale["pellet_lot_id"])
    if pellet is not None and pellet["inventory_status"] == "RESERVED":
        pellet["inventory_status"] = "AVAILABLE"
        touch(pellet)
    return success_object(public(sale))
