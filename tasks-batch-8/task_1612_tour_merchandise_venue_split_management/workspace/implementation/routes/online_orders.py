"""OnlineOrder endpoints (PRD §3.7)."""

from flask import Blueprint, request

from db import DB
from errors import (
    ERR_TOUR_NOT_FOUND,
    ERR_PRODUCT_NOT_FOUND,
    ERR_ONLINE_ORDER_NOT_FOUND,
    ERR_TOUR_NOT_ACTIVE,
    ERR_ORDER_NOT_PLACED,
    ERR_INSUFFICIENT_STOCK,
    ERR_VALIDATION,
    err,
)
from middleware import (
    require_role,
    require_auth,
    get_json_body,
    require_int,
    require_enum,
    base_fields,
    touch,
    paginate,
)
from response import success_object, success_list
from services.core import compute_warehouse_stock, online_royalty_figures
from services.serializers import online_order_view

bp = Blueprint("online_orders", __name__)


def get_order_or_404(order_id):
    o = DB.online_orders.get(order_id)
    if o is None:
        raise err(ERR_ONLINE_ORDER_NOT_FOUND, 404, "No OnlineOrder with the given id")
    return o


@bp.post("/merch/online-orders")
def create_online_order():
    require_role("TourManager")
    body = get_json_body()
    tour_id = body.get("tour_id")
    product_id = body.get("product_id")
    size = body.get("size")

    if tour_id is None:
        raise err(ERR_VALIDATION, 400, "Missing required field: tour_id")
    if product_id is None:
        raise err(ERR_VALIDATION, 400, "Missing required field: product_id")

    tour = DB.tours.get(tour_id)
    if tour is None:
        raise err(ERR_TOUR_NOT_FOUND, 404, "No Tour with the given id")
    product = DB.products.get(product_id)
    if product is None:
        raise err(ERR_PRODUCT_NOT_FOUND, 404, "No Product with the given id")

    if tour["status"] != "ACTIVE":
        raise err(ERR_TOUR_NOT_ACTIVE, 409, "Placing an online order requires an ACTIVE tour")

    if product["tour_id"] != tour_id:
        from errors import ERR_CROSS_TOUR_REFERENCE
        raise err(ERR_CROSS_TOUR_REFERENCE, 422, "Product must belong to the order's tour")

    if product["product_type"] == "BUNDLE":
        if size is not None:
            raise err(ERR_VALIDATION, 400, "size must be null for BUNDLE products")
    elif product["sized"]:
        if size is None:
            raise err(ERR_VALIDATION, 400, "size is required for sized products")
        require_enum(body, "size", ("S", "M", "L", "XL"), required=True)
    else:
        if size is not None:
            raise err(ERR_VALIDATION, 400, "size must be null for non-sized products")

    quantity = require_int(body, "quantity", gt=0, required=True)

    order = {
        **base_fields(),
        "tour_id": tour_id,
        "product_id": product_id,
        "size": size,
        "quantity": quantity,
        "unit_price_cents": product["base_price_cents"],
        "gross_cents": quantity * product["base_price_cents"],
        "status": "PLACED",
        "artist_royalty_final_cents": None,
        "licensing_final_cents": None,
    }
    artist_prov, licensing_prov = online_royalty_figures(order, tour)
    order["artist_royalty_provisional_cents"] = artist_prov
    order["licensing_provisional_cents"] = licensing_prov
    DB.online_orders[order["id"]] = order
    return success_object(online_order_view(order), status=201)


@bp.get("/merch/online-orders")
def list_online_orders():
    require_auth()
    tour_id = request.args.get("tour_id")
    product_id = request.args.get("product_id")
    items = list(DB.online_orders.values())
    if tour_id is not None:
        items = [o for o in items if o["tour_id"] == tour_id]
    if product_id is not None:
        items = [o for o in items if o["product_id"] == product_id]
    items.sort(key=lambda o: o["created_at"])
    page, limit, offset, total = paginate(items)
    return success_list([online_order_view(o) for o in page], limit, offset, total)


@bp.get("/merch/online-orders/<order_id>")
def get_online_order(order_id):
    require_auth()
    return success_object(online_order_view(get_order_or_404(order_id)))


@bp.post("/merch/online-orders/<order_id>/fulfill")
def fulfill_online_order(order_id):
    require_role("TourManager")
    order = get_order_or_404(order_id)
    if order["status"] != "PLACED":
        raise err(ERR_ORDER_NOT_PLACED, 409, "Fulfill requires a PLACED order")

    product = DB.products[order["product_id"]]
    if product["product_type"] == "BUNDLE":
        # Every component's OS stock must cover qty_per_bundle * quantity.
        for comp in product["bundle_components"]:
            need = comp["qty_per_bundle"] * order["quantity"]
            if compute_warehouse_stock(comp["component_product_id"]).get("OS", 0) < need:
                raise err(ERR_INSUFFICIENT_STOCK, 409,
                          "Insufficient warehouse stock for a bundle component")
    else:
        stock = compute_warehouse_stock(product["id"])
        need_size = order["size"] if product["sized"] else "OS"
        if stock.get(need_size, 0) < order["quantity"]:
            raise err(ERR_INSUFFICIENT_STOCK, 409,
                      "Insufficient warehouse stock for the ordered size")

    tour = DB.tours[order["tour_id"]]
    artist_final, licensing_final = online_royalty_figures(order, tour)
    order["artist_royalty_final_cents"] = artist_final
    order["licensing_final_cents"] = licensing_final
    order["status"] = "FULFILLED"
    touch(order)
    return success_object(online_order_view(order))


@bp.post("/merch/online-orders/<order_id>/cancel")
def cancel_online_order(order_id):
    require_role("TourManager")
    order = get_order_or_404(order_id)
    if order["status"] != "PLACED":
        raise err(ERR_ORDER_NOT_PLACED, 409, "Cancel requires a PLACED order")
    order["status"] = "CANCELLED"
    touch(order)
    return success_object(online_order_view(order))
