"""ShowProduct endpoints (PRD §3.2)."""

from flask import Blueprint, request

from db import DB
from errors import (
    ERR_SHOW_NOT_FOUND,
    ERR_PRODUCT_NOT_FOUND,
    ERR_SHOW_PRODUCT_NOT_FOUND,
    ERR_CROSS_TOUR_REFERENCE,
    ERR_PRODUCT_NOT_SELLABLE_AT_SHOW,
    ERR_SHOW_PRODUCT_EXISTS,
    ERR_INVALID_SHOW_STATE,
    ERR_STALE_VERSION,
    ERR_VALIDATION,
    err,
)
from middleware import (
    require_role,
    require_auth,
    get_json_body,
    require_int,
    base_fields,
    touch,
    paginate,
)
from response import success_object, success_list
from services.serializers import show_product_view

bp = Blueprint("show_products", __name__)


def get_show_product_or_404(sp_id):
    sp = DB.show_products.get(sp_id)
    if sp is None:
        raise err(ERR_SHOW_PRODUCT_NOT_FOUND, 404, "No ShowProduct with the given id")
    return sp


@bp.post("/merch/show-products")
def create_show_product():
    require_role("TourManager")
    body = get_json_body()
    show_id = body.get("show_id")
    product_id = body.get("product_id")

    if show_id is None:
        raise err(ERR_VALIDATION, 400, "Missing required field: show_id")
    if product_id is None:
        raise err(ERR_VALIDATION, 400, "Missing required field: product_id")

    show = DB.shows.get(show_id)
    if show is None:
        raise err(ERR_SHOW_NOT_FOUND, 404, "No Show with the given id")
    product = DB.products.get(product_id)
    if product is None:
        raise err(ERR_PRODUCT_NOT_FOUND, 404, "No Product with the given id")

    if show["status"] != "SCHEDULED":
        raise err(ERR_INVALID_SHOW_STATE, 409,
                  "Price rows can be created only while the show is SCHEDULED")

    if product["tour_id"] != show["tour_id"]:
        raise err(ERR_CROSS_TOUR_REFERENCE, 422,
                  "Product must belong to the show's tour")

    for sp in DB.show_products.values():
        if sp["show_id"] == show_id and sp["product_id"] == product_id:
            raise err(ERR_SHOW_PRODUCT_EXISTS, 409,
                      "A ShowProduct already exists for this (show, product)")

    if product["product_type"] == "BUNDLE":
        raise err(ERR_PRODUCT_NOT_SELLABLE_AT_SHOW, 422,
                  "BUNDLE products are online-only")

    price_cents = require_int(body, "price_cents", gt=0, required=True)

    sp = {
        **base_fields(),
        "show_id": show_id,
        "product_id": product_id,
        "price_cents": price_cents,
    }
    DB.show_products[sp["id"]] = sp
    return success_object(show_product_view(sp), status=201)


@bp.get("/merch/show-products")
def list_show_products():
    require_auth()
    show_id = request.args.get("show_id")
    product_id = request.args.get("product_id")
    items = list(DB.show_products.values())
    if show_id is not None:
        items = [s for s in items if s["show_id"] == show_id]
    if product_id is not None:
        items = [s for s in items if s["product_id"] == product_id]
    items.sort(key=lambda s: s["created_at"])
    page, limit, offset, total = paginate(items)
    return success_list([show_product_view(s) for s in page], limit, offset, total)


@bp.get("/merch/show-products/<sp_id>")
def get_show_product(sp_id):
    require_auth()
    return success_object(show_product_view(get_show_product_or_404(sp_id)))


@bp.patch("/merch/show-products/<sp_id>")
def reprice_show_product(sp_id):
    require_role("TourManager")
    sp = get_show_product_or_404(sp_id)
    body = get_json_body()

    show = DB.shows[sp["show_id"]]
    if show["status"] not in ("SCHEDULED", "OPEN"):
        raise err(ERR_INVALID_SHOW_STATE, 409,
                  "Repricing requires the show to be SCHEDULED or OPEN")

    # OCC staleness (priority 5 in PRD §2.7) precedes body shape checks (12).
    expected = body.get("expected_show_product_version")
    if expected is not None and isinstance(expected, int) and not isinstance(expected, bool):
        if expected != sp["version"]:
            raise err(ERR_STALE_VERSION, 412,
                      "expected_show_product_version does not match the current version")

    price_cents = require_int(body, "price_cents", gt=0, required=True)
    if expected is None or not isinstance(expected, int) or isinstance(expected, bool):
        raise err(ERR_VALIDATION, 400,
                  "expected_show_product_version is required and must be an integer")

    sp["price_cents"] = price_cents
    touch(sp)
    return success_object(show_product_view(sp))
