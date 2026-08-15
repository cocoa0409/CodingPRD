"""Inventory lot endpoints (PRD 3.3)."""
from flask import Blueprint

from middleware import authorized
from response import success_object
from routes.helpers import arg, get_one, list_response
from services.calc import lot_expiry_date
from services.core import new_record, serialize
from util import fmt_date, parse_date
from validate import get_body, req_date, req_int, req_str, require_fk

bp = Blueprint("lots", __name__)


@bp.post("/api/lots")
def create_lot():
    authorized(["AccountManager"])
    body = get_body()
    product_id = req_str(body, "product_id")
    lot_code = req_str(body, "lot_code")
    manufacture_date = req_date(body, "manufacture_date")
    qty_received = req_int(body, "qty_received", min_value=1)
    # Priority 4: body FK existence.
    product = require_fk("products", product_id, "product")
    expiry = lot_expiry_date(product, parse_date(manufacture_date))
    rec = new_record("lots", {
        "product_id": product_id,
        "lot_code": lot_code,
        "manufacture_date": manufacture_date,
        "qty_received": qty_received,
        "qty_on_hand": qty_received,
        "expiry_date": fmt_date(expiry) if expiry is not None else None,
        "status": "AVAILABLE",
    })
    return success_object(serialize(rec), status=201)


@bp.get("/api/lots/<lid>")
def get_lot(lid):
    return get_one("lots", lid, "lot")


@bp.get("/api/lots")
def list_lots():
    return list_response("lots", {
        "product_id": arg("product_id"),
        "status": arg("status"),
    })
