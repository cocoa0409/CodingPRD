from flask import Blueprint

from db import STORE, make_rec, mark
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND,
                    ERR_INVALID_STATE_TRANSITION, ERR_SSP_WINDOW_OVERLAP,
                    ERR_INVALID_AMOUNT)
from response import ok_object
import serializers as ser
from validate import require_roles, body, req_str, req_int, req_date

bp = Blueprint("ssp", __name__)


@bp.post("/revrec/ssp-prices")
def create_ssp():
    require_roles("RevenueManager")
    data = body()
    product_code = req_str(data, "product_code")
    region = req_str(data, "region")
    ssp_cents = req_int(data, "ssp_cents")
    eff_from = req_date(data, "effective_from")
    eff_to = req_date(data, "effective_to")
    if eff_to < eff_from:
        raise ApiError(ERR_INVALID_REQUEST, 400, "effective_to must not precede effective_from")
    # CLOSED intervals: overlap OR a shared boundary date is a conflict.
    for s in STORE.ssp_prices.values():
        if s["status"] != "ACTIVE":
            continue
        if s["product_code"] != product_code or s["region"] != region:
            continue
        if eff_from.isoformat() <= s["effective_to"] and s["effective_from"] <= eff_to.isoformat():
            raise ApiError(ERR_SSP_WINDOW_OVERLAP, 409,
                           "SSP windows for the same (product_code, region) must not overlap or touch")
    if ssp_cents <= 0:
        raise ApiError(ERR_INVALID_AMOUNT, 422, "ssp_cents must be > 0")
    rec = make_rec(STORE.ssp_prices, {
        "product_code": product_code,
        "region": region,
        "ssp_cents": ssp_cents,
        "effective_from": eff_from.isoformat(),
        "effective_to": eff_to.isoformat(),
        "status": "ACTIVE",
    })
    return ok_object(ser.ssp_price(rec), 201)


@bp.post("/revrec/ssp-prices/<ssp_id>/retire")
def retire_ssp(ssp_id):
    require_roles("RevenueManager")
    s = STORE.ssp_prices.get(ssp_id)
    if s is None:
        raise ApiError(ERR_NOT_FOUND, 404, "ssp_id does not identify an existing SSP record")
    if s["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "retire requires the SSP record to be ACTIVE")
    s["status"] = "RETIRED"
    mark(s)
    return ok_object(ser.ssp_price(s))
