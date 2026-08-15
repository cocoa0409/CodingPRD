"""Product endpoints (PRD §3.1)."""

from flask import Blueprint, request

from db import DB
from errors import (
    ERR_TOUR_NOT_FOUND,
    ERR_PRODUCT_NOT_FOUND,
    ERR_BUNDLE_COMPONENT_INVALID,
    ERR_VALIDATION,
    err,
)
from middleware import (
    require_role,
    require_auth,
    get_json_body,
    require_string,
    require_int,
    require_enum,
    require_bool,
    base_fields,
    paginate,
)
from response import success_object, success_list
from services.core import validate_bundle_components, validate_stock_map
from services.serializers import product_view

bp = Blueprint("products", __name__)


def get_product_or_404(product_id):
    p = DB.products.get(product_id)
    if p is None:
        raise err(ERR_PRODUCT_NOT_FOUND, 404, "No Product with the given id")
    return p


@bp.post("/merch/products")
def create_product():
    require_role("TourManager")
    body = get_json_body()
    tour_id = body.get("tour_id")
    if tour_id is None:
        raise err(ERR_VALIDATION, 400, "Missing required field: tour_id")
    if tour_id not in DB.tours:
        raise err(ERR_TOUR_NOT_FOUND, 404, "No Tour with the given id")

    sku = require_string(body, "sku", required=True)
    name = require_string(body, "name", required=True)
    product_type = require_enum(body, "product_type", ("REGULAR", "BUNDLE"), required=True)
    royalty_treatment = require_enum(body, "royalty_treatment", ("STANDARD", "LICENSED"), required=True)
    base_price_cents = require_int(body, "base_price_cents", gt=0, required=True)
    sized = require_bool(body, "sized")
    if sized is None:
        sized = True

    components = body.get("bundle_components")
    if product_type == "BUNDLE":
        components = validate_bundle_components(tour_id, components)
    else:
        if components is not None:
            raise err(ERR_BUNDLE_COMPONENT_INVALID, 400,
                      "REGULAR products must leave bundle_components null")

    stock = validate_stock_map(body.get("initial_stock_by_size"), sized)

    product = {
        **base_fields(),
        "tour_id": tour_id,
        "sku": sku,
        "name": name,
        "product_type": product_type,
        "royalty_treatment": royalty_treatment,
        "sized": sized,
        "base_price_cents": base_price_cents,
        "bundle_components": components if product_type == "BUNDLE" else None,
        "initial_stock_by_size": stock,
    }
    DB.products[product["id"]] = product
    return success_object(product_view(product), status=201)


@bp.get("/merch/products")
def list_products():
    require_auth()
    tour_id = request.args.get("tour_id")
    items = list(DB.products.values())
    if tour_id is not None:
        items = [p for p in items if p["tour_id"] == tour_id]
    items.sort(key=lambda p: p["created_at"])
    page, limit, offset, total = paginate(items)
    return success_list([product_view(p) for p in page], limit, offset, total)


@bp.get("/merch/products/<product_id>")
def get_product(product_id):
    require_auth()
    return success_object(product_view(get_product_or_404(product_id)))
