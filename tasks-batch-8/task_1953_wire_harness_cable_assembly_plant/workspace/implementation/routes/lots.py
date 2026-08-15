"""Customer-consigned connector lots (PRD 3.6)."""
from flask import Blueprint

from db import db
from errors import raise_error, ERR_INVALID_REQUEST
from middleware import authenticate, ALL_ROLES
from response import success_object
from services import common_fields, touch, ser_consigned_lot
from validate import get_body, req_str, req_int, require_path

bp = Blueprint("consigned_lots", __name__)

MATERIALS_CLERK = {"MaterialsClerk"}


@bp.route("/plant/consigned-lots", methods=["POST"])
def create_lot():
    body = get_body()
    lot_code = req_str(body, "lot_code")
    owner_customer_code = req_str(body, "owner_customer_code")
    mpn = req_str(body, "mpn")
    unit_liability_cents = req_int(body, "unit_liability_cents", minimum=0)
    replacement_cost_cents = req_int(body, "replacement_cost_cents", minimum=0)
    qty_received = req_int(body, "qty_received", minimum=1)
    authenticate(MATERIALS_CLERK)
    for lot in db["consigned_lots"].values():
        if lot["lot_code"] == lot_code:
            raise_error(ERR_INVALID_REQUEST, f"duplicate lot_code: {lot_code}")

    lot = common_fields()
    lot.update({
        "lot_code": lot_code,
        "owner_customer_code": owner_customer_code,
        "mpn": mpn,
        "unit_liability_cents": unit_liability_cents,
        "replacement_cost_cents": replacement_cost_cents,
        "qty_received": qty_received,
        "qty_on_hand": qty_received,
        "qty_issued_open": 0,
        "qty_consumed": 0,
        "qty_scrapped": 0,
        "qty_returned": 0,
        "book_liability_cents": 0,
        "replacement_liability_cents": 0,
        "status": "ACTIVE",
    })
    db["consigned_lots"][lot["id"]] = lot
    return success_object(ser_consigned_lot(lot), 201)


@bp.route("/plant/consigned-lots/<lid>", methods=["GET"])
def get_lot(lid):
    authenticate(ALL_ROLES)
    lot = require_path("consigned_lots", lid)
    return success_object(ser_consigned_lot(lot), 200)


@bp.route("/plant/consigned-lots/<lid>/return", methods=["POST"])
def return_lot(lid):
    get_body()
    authenticate(MATERIALS_CLERK)
    lot = require_path("consigned_lots", lid)
    if lot["status"] != "ACTIVE":
        raise_error(ERR_INVALID_REQUEST, "only an ACTIVE lot can be returned")
    lot["qty_returned"] += lot["qty_on_hand"]
    lot["qty_on_hand"] = 0
    lot["status"] = "RETURNED"
    touch(lot)
    return success_object(ser_consigned_lot(lot), 200)
