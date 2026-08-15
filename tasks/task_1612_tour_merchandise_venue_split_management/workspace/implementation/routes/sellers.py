"""Seller endpoints (PRD §3.4)."""

from flask import Blueprint, request

from db import DB
from errors import (
    ERR_TOUR_NOT_FOUND,
    ERR_SELLER_NOT_FOUND,
    ERR_VALIDATION,
    err,
)
from middleware import (
    require_role,
    require_auth,
    get_json_body,
    require_string,
    base_fields,
    paginate,
)
from response import success_object, success_list
from services.serializers import seller_view

bp = Blueprint("sellers", __name__)


def get_seller_or_404(seller_id):
    s = DB.sellers.get(seller_id)
    if s is None:
        raise err(ERR_SELLER_NOT_FOUND, 404, "No Seller with the given id")
    return s


@bp.post("/merch/sellers")
def create_seller():
    require_role("TourManager")
    body = get_json_body()
    tour_id = body.get("tour_id")
    if tour_id is None:
        raise err(ERR_VALIDATION, 400, "Missing required field: tour_id")
    if tour_id not in DB.tours:
        raise err(ERR_TOUR_NOT_FOUND, 404, "No Tour with the given id")

    display_name = require_string(body, "display_name", required=True)
    seller_code = require_string(body, "seller_code", required=True)

    seller = {
        **base_fields(),
        "tour_id": tour_id,
        "display_name": display_name,
        "seller_code": seller_code,
    }
    DB.sellers[seller["id"]] = seller
    return success_object(seller_view(seller), status=201)


@bp.get("/merch/sellers")
def list_sellers():
    require_auth()
    tour_id = request.args.get("tour_id")
    items = list(DB.sellers.values())
    if tour_id is not None:
        items = [s for s in items if s["tour_id"] == tour_id]
    items.sort(key=lambda s: s["created_at"])
    page, limit, offset, total = paginate(items)
    return success_list([seller_view(s) for s in page], limit, offset, total)


@bp.get("/merch/sellers/<seller_id>")
def get_seller(seller_id):
    require_auth()
    return success_object(seller_view(get_seller_or_404(seller_id)))
