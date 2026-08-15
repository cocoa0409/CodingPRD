"""Allocation endpoints (PRD §3.3)."""

from flask import Blueprint, request

from db import DB
from errors import (
    ERR_SHOW_NOT_FOUND,
    ERR_PRODUCT_NOT_FOUND,
    ERR_ALLOCATION_NOT_FOUND,
    ERR_INVALID_SHOW_STATE,
    ERR_ALLOCATIONS_EXIST,
    ERR_VALIDATION,
    err,
)
from middleware import (
    require_role,
    require_auth,
    get_json_body,
    require_int,
    base_fields,
    paginate,
)
from response import success_object, success_list, success_array
from services.core import size_curve_split
from services.serializers import allocation_view

bp = Blueprint("allocations", __name__)


def get_allocation_or_404(alloc_id):
    a = DB.allocations.get(alloc_id)
    if a is None:
        raise err(ERR_ALLOCATION_NOT_FOUND, 404, "No Allocation with the given id")
    return a


@bp.post("/merch/shows/<show_id>/allocations/generate")
def generate_allocations(show_id):
    require_role("TourManager")
    show = DB.shows.get(show_id)
    if show is None:
        raise err(ERR_SHOW_NOT_FOUND, 404, "No Show with the given id")
    body = get_json_body()
    product_id = body.get("product_id")
    if product_id is None:
        raise err(ERR_VALIDATION, 400, "Missing required field: product_id")
    product = DB.products.get(product_id)
    if product is None:
        raise err(ERR_PRODUCT_NOT_FOUND, 404, "No Product with the given id")

    if show["status"] != "SCHEDULED":
        raise err(ERR_INVALID_SHOW_STATE, 409,
                  "Allocation generation requires a SCHEDULED show")

    # Cross-tour coherence: product must belong to the show's tour.
    if product["tour_id"] != show["tour_id"]:
        from errors import ERR_CROSS_TOUR_REFERENCE
        raise err(ERR_CROSS_TOUR_REFERENCE, 422,
                  "Product must belong to the show's tour")

    for a in DB.allocations.values():
        if a["show_id"] == show_id and a["product_id"] == product_id:
            raise err(ERR_ALLOCATIONS_EXIST, 409,
                      "Allocations already generated for this (show, product)")

    if product["product_type"] == "BUNDLE":
        raise err(ERR_VALIDATION, 400, "BUNDLE products are not allocated at shows")

    total_units = require_int(body, "total_units", ge=0, required=True)

    rows = size_curve_split(show, product, total_units)
    created = []
    for size, qty in rows:
        alloc = {
            **base_fields(),
            "show_id": show_id,
            "product_id": product_id,
            "size": size,
            "quantity_allocated": qty,
            "quantity_returned": 0,
            "quantity_liquidated": 0,
            "quantity_shrunk": 0,
        }
        DB.allocations[alloc["id"]] = alloc
        created.append(alloc)

    return success_array([allocation_view(a) for a in created], status=201)


@bp.get("/merch/allocations")
def list_allocations():
    require_auth()
    show_id = request.args.get("show_id")
    product_id = request.args.get("product_id")
    items = list(DB.allocations.values())
    if show_id is not None:
        items = [a for a in items if a["show_id"] == show_id]
    if product_id is not None:
        items = [a for a in items if a["product_id"] == product_id]
    items.sort(key=lambda a: a["created_at"])
    page, limit, offset, total = paginate(items)
    return success_list([allocation_view(a) for a in page], limit, offset, total)


@bp.get("/merch/allocations/<alloc_id>")
def get_allocation(alloc_id):
    require_auth()
    return success_object(allocation_view(get_allocation_or_404(alloc_id)))
