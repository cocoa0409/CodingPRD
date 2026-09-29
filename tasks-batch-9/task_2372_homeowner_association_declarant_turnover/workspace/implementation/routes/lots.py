"""Platted lots and the sale closing transition."""
from flask import Blueprint

import auth
import calc
import cascades
import constants
import response
import validation as v
from db import db, new_record, serialize, touch
from errors import ApiError
from routes import common

bp = Blueprint("lots", __name__)


@bp.post("/hoa/lots")
def create_lot():
    auth.require_roles(constants.ROLE_DECLARANT)
    body = v.body()

    association = common.body_association_or_404(v.get_fk(body, "association_id"))
    if association is None:
        raise ApiError("ERR_INVALID_REQUEST", "association_id is required.")

    lot_number = v.get_str(body, "lot_number", min_len=1, max_len=16)
    sale_status = v.get_enum(
        body,
        "sale_status",
        constants.LOT_CREATE_SALE_STATUSES,
        required=False,
        default="UNSOLD",
    )

    for existing in calc.lots_of(association["id"]):
        if existing["lot_number"] == lot_number:
            raise ApiError("ERR_DUPLICATE_LOT_NUMBER")

    lot = new_record({
        "association_id": association["id"],
        "lot_number": lot_number,
        "sale_status": sale_status,
        "closing_date": None,
    })
    db.lots[lot["id"]] = lot
    return response.object_response(serialize(lot), 201)


@bp.post("/hoa/lots/<lot_id>/close-sale")
def close_sale(lot_id):
    auth.require_roles(constants.ROLE_DECLARANT)
    lot = common.lot_or_404(lot_id, scoped=True)
    body = v.body()
    closing_date, _ = v.get_datetime(body, "closing_date")

    cascades.require_not_settled_locked(lot["association_id"])

    if lot["sale_status"] not in ("UNSOLD", "UNDER_CONTRACT"):
        raise ApiError("ERR_LOT_STATE_INVALID")

    lot["sale_status"] = "CLOSED"
    lot["closing_date"] = closing_date
    touch(lot)

    association = db.associations.get(lot["association_id"])
    if association is not None:
        calc.apply_sold_lot_percentage(association)
        touch(association)

    return response.object_response(serialize(lot))
