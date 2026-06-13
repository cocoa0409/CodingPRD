"""ProductSku routes: create, fetch, list, restock (PRD §3.1)."""
from flask import Blueprint, request

import db
from errors import err
from lookups import get_or_404, get_salon
from response import success
from util import stamp_create, touch, public
import validate as v
from routes.common import auth, json_body, list_response

bp = Blueprint("product_skus", __name__)


def _sku_taken(salon_id, sku):
    for s in db.product_skus.values():
        if s["salon_id"] == salon_id and s["sku"] == sku:
            return True
    return False


@bp.post("/product-skus")
def create_sku():
    auth(("SalonOwner",))
    body = json_body()
    v.require_object(body)

    salon_id = v.req_str(body, "salon_id")
    salon = get_salon(salon_id)

    sku = v.req_str(body, "sku")
    name = v.req_str(body, "name")
    unit_price_cents = v.req_int(body, "unit_price_cents", minimum=0)
    qty_on_hand = v.req_int(body, "qty_on_hand", minimum=0)

    if _sku_taken(salon["id"], sku):
        raise err("ERR_INVALID_REQUEST", "sku already in use within this salon")

    product = {
        "salon_id": salon["id"],
        "sku": sku,
        "name": name,
        "unit_price_cents": unit_price_cents,
        "qty_on_hand": qty_on_hand,
    }
    stamp_create(product)
    db.product_skus[product["id"]] = product
    return success(public(product), status=201)


@bp.get("/product-skus/<sku_id>")
def get_sku(sku_id):
    auth(("SalonOwner", "FrontDesk"))
    product = get_or_404(db.product_skus, sku_id)
    return success(public(product), status=200)


@bp.get("/product-skus")
def list_skus():
    auth(("SalonOwner", "FrontDesk"))
    salon_id = request.args.get("salon_id")

    def pred(s):
        if salon_id is not None and s["salon_id"] != salon_id:
            return False
        return True

    page, meta = list_response(db.product_skus, pred)
    return success(page, status=200, response_type="array", pagination=meta)


@bp.post("/product-skus/<sku_id>/restock")
def restock(sku_id):
    auth(("SalonOwner",))
    product = get_or_404(db.product_skus, sku_id)
    body = json_body()
    v.require_object(body)
    quantity = v.req_int(body, "quantity", minimum=1)
    product["qty_on_hand"] += quantity
    touch(product)
    return success(public(product), status=200)
