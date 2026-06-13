"""ProductSale read routes: fetch one, list (PRD §3.7)."""
from flask import Blueprint, request

import db
from lookups import get_or_404
from response import success
from util import public
from routes.common import auth, list_response

bp = Blueprint("product_sales", __name__)


@bp.get("/product-sales/<sale_id>")
def get_sale(sale_id):
    auth(("SalonOwner", "FrontDesk"))
    sale = get_or_404(db.product_sales, sale_id)
    return success(public(sale), status=200)


@bp.get("/product-sales")
def list_sales():
    auth(("SalonOwner", "FrontDesk"))
    checkout_id = request.args.get("checkout_id")
    product_sku_id = request.args.get("product_sku_id")

    def pred(s):
        if checkout_id is not None and s["checkout_id"] != checkout_id:
            return False
        if product_sku_id is not None and s["product_sku_id"] != product_sku_id:
            return False
        return True

    page, meta = list_response(db.product_sales, pred)
    return success(page, status=200, response_type="array", pagination=meta)
