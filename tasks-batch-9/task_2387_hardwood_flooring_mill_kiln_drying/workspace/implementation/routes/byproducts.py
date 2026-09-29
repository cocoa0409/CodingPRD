"""The byproduct ledger: read-only batches and broker sales (PRD 3.6)."""

from flask import Blueprint

from db import db, insert, touch
from errors import ApiError
from middleware import ALL_ROLES, BYPRODUCT_BROKER, MILL_ADMIN, authorize
from response import array_response, object_response, paginate
from serializers import serialize, serialize_many
from services import calc, lookup, mill
from services.calc import D, rhu
from validation import (body_json, pagination, query_enum, query_str, req_decimal,
                        req_int, req_ref, req_str)

bp = Blueprint("byproducts", __name__)

BYPRODUCT_TYPES = ("SAWDUST", "SHAVINGS", "SHORTS")


@bp.get("/mill/byproduct-batches/<byproduct_batch_id>")
@authorize(*ALL_ROLES)
def get_byproduct_batch(byproduct_batch_id):
    return object_response(
        serialize("byproduct_batch", lookup.byproduct_batch(byproduct_batch_id)))


@bp.get("/mill/byproduct-batches")
@authorize(*ALL_ROLES)
def list_byproduct_batches():
    limit, offset = pagination()
    rows = lookup.filtered(db.byproduct_batches, [
        ("flooring_lot_id", query_str("flooring_lot_id")),
        ("byproduct_type", query_enum("byproduct_type", BYPRODUCT_TYPES)),
    ])
    page, total = paginate(rows, limit, offset)
    return array_response(serialize_many("byproduct_batch", page), limit, offset, total)


@bp.post("/mill/byproduct-sales")
@authorize(BYPRODUCT_BROKER, MILL_ADMIN)
def create_byproduct_sale():
    body = body_json()
    byproduct_batch_id = req_ref(body, "byproduct_batch_id")
    buyer_name = req_str(body, "buyer_name")
    quantity_tons = req_decimal(body, "quantity_tons")
    unit_price_cents_per_ton = req_int(body, "unit_price_cents_per_ton")
    haul_distance_miles = req_int(body, "haul_distance_miles")

    batch = lookup.byproduct_batch(byproduct_batch_id)

    projected = rhu(D(batch["sold_tons"]) + quantity_tons, 2)
    if projected > D(batch["available_tons"]):
        raise ApiError("ERR_BYPRODUCT_QUANTITY_EXCEEDS_BATCH")

    gross_cents, discount_cents, haul_cents, net_cents = calc.byproduct_settlement(
        quantity_tons, unit_price_cents_per_ton, haul_distance_miles)

    record = insert(db.byproduct_sales, {
        "byproduct_batch_id": byproduct_batch_id,
        "buyer_name": buyer_name,
        "quantity_tons": quantity_tons,
        "unit_price_cents_per_ton": unit_price_cents_per_ton,
        "haul_distance_miles": haul_distance_miles,
        "gross_cents": gross_cents,
        "discount_cents": discount_cents,
        "haul_cents": haul_cents,
        "net_cents": net_cents,
    })

    mill.recompute_sold_tons(batch)
    touch(batch)
    return object_response(serialize("byproduct_sale", record), 201)


@bp.get("/mill/byproduct-sales/<byproduct_sale_id>")
@authorize(*ALL_ROLES)
def get_byproduct_sale(byproduct_sale_id):
    return object_response(serialize("byproduct_sale", lookup.byproduct_sale(byproduct_sale_id)))


@bp.get("/mill/byproduct-sales")
@authorize(*ALL_ROLES)
def list_byproduct_sales():
    limit, offset = pagination()
    rows = lookup.filtered(db.byproduct_sales, [
        ("byproduct_batch_id", query_str("byproduct_batch_id")),
    ])
    page, total = paginate(rows, limit, offset)
    return array_response(serialize_many("byproduct_sale", page), limit, offset, total)
