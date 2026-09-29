"""Delivered order lines ingested from the commerce platform (PRD 3.7)."""

from flask import Blueprint

import constants as C
import validate as V
from db import db, new_row
from lookup import ensure_not_delisted, filtered, get_customer, get_item, get_order_line
from middleware import authenticate
from response import array_response, object_response
from services.derive import recompute_customer, recompute_item

bp = Blueprint("order_lines", __name__)


@bp.post("/fit-program/order-lines")
def ingest_order_line():
    authenticate(C.ROLE_MERCH_OPS_ADMIN)
    body = V.get_body()

    customer_profile_id = V.req_str(body, "customer_profile_id", min_len=1)
    item_id = V.req_str(body, "item_id", min_len=1)
    size_label = V.req_str(body, "size_label", min_len=1)
    quantity = V.req_int(body, "quantity", minimum=1)
    unit_price_cents = V.req_int(body, "unit_price_cents", minimum=1)
    shipping_allocated_cents = V.req_int(body, "shipping_allocated_cents", minimum=0)
    delivered_at = V.req_instant(body, "delivered_at")

    customer = get_customer(customer_profile_id)
    item = get_item(item_id)
    ensure_not_delisted(item)

    line = new_row({
        "customer_profile_id": customer["id"],
        "item_id": item["id"],
        "size_label": size_label,
        "quantity": quantity,
        "unit_price_cents": unit_price_cents,
        "shipping_allocated_cents": shipping_allocated_cents,
        "delivered_at": delivered_at,
        "gross_line_cents": unit_price_cents * quantity,
        "status": "DELIVERED",
    })
    db.order_lines[line["id"]] = line

    # ingest is itself a small cascade
    recompute_item(item)
    recompute_customer(customer)

    return object_response(line, 201)


@bp.get("/fit-program/order-lines/<line_id>")
def read_order_line(line_id):
    authenticate(C.ROLE_MERCH_OPS_ADMIN, C.ROLE_RETURNS_AUDITOR, C.ROLE_CUSTOMER)
    return object_response(get_order_line(line_id))


@bp.get("/fit-program/order-lines")
def list_order_lines():
    authenticate(C.ROLE_MERCH_OPS_ADMIN, C.ROLE_RETURNS_AUDITOR, C.ROLE_CUSTOMER)
    limit, offset = V.pagination_params()
    rows = filtered(db.order_lines.values(), {
        "customer_profile_id": "customer_profile_id",
        "item_id": "item_id",
        "status": "status",
    })
    page, meta = V.paginate(rows, limit, offset)
    return array_response(page, meta)
