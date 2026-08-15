"""Close-out endpoints."""
from flask import Blueprint

import store
from auth import authenticate, authorize
from errors import ERR_LOT_NOT_FOUND, ERR_CLOSE_OUT_NOT_FOUND, ERR_INVALID_REQUEST, raise_err
from serializers import close_out_out
from services import closeout_service
from util import body_json, get_or_404, req_str, req_int, opt_int, success_object

bp = Blueprint("close_outs", __name__)


@bp.route("/feedlot/close-outs", methods=["POST"])
def create_close_out():
    _, role = authenticate()
    authorize(role, ["RiskManager"])
    body = body_json()

    lot_id = req_str(body, "lot_id")
    pricing_basis = req_str(body, "pricing_basis")
    grid_base_price_cents_per_cwt = req_int(body, "grid_base_price_cents_per_cwt")
    expected_lot_version = opt_int(body, "expected_lot_version")

    # Validate pricing_basis
    if pricing_basis not in ("PER_CARCASS", "LOT_AVERAGE"):
        raise_err(ERR_INVALID_REQUEST,
                  "pricing_basis must be PER_CARCASS or LOT_AVERAGE")

    # Validate ranges
    if grid_base_price_cents_per_cwt <= 0:
        raise_err(ERR_INVALID_REQUEST, "grid_base_price_cents_per_cwt must be > 0")

    # Validate lot exists
    lot = store.lots.get(lot_id)
    if lot is None:
        raise_err(ERR_LOT_NOT_FOUND, "Lot not found: %s" % lot_id)

    rec = closeout_service.create_close_out(
        lot, pricing_basis, grid_base_price_cents_per_cwt, expected_lot_version
    )
    return success_object(close_out_out(rec), 201)


@bp.route("/feedlot/close-outs/<close_out_id>/confirm", methods=["POST"])
def confirm_close_out(close_out_id):
    _, role = authenticate()
    authorize(role, ["RiskManager"])
    body = body_json()

    carcass_records = body.get("carcass_records")
    if not isinstance(carcass_records, list):
        raise_err(ERR_INVALID_REQUEST, "carcass_records must be an array")

    # Validate each record
    for i, rec in enumerate(carcass_records):
        if not isinstance(rec, dict):
            raise_err(ERR_INVALID_REQUEST, "carcass_records[%d] must be an object" % i)
        hcw = rec.get("hot_carcass_weight_lbs")
        if not isinstance(hcw, int) or hcw <= 0:
            raise_err(ERR_INVALID_REQUEST,
                      "carcass_records[%d].hot_carcass_weight_lbs must be a positive integer" % i)
        qg = rec.get("quality_grade")
        if qg not in ("PRIME", "CHOICE", "SELECT", "STANDARD"):
            raise_err(ERR_INVALID_REQUEST,
                      "carcass_records[%d].quality_grade must be PRIME, CHOICE, SELECT, or STANDARD" % i)
        yg = rec.get("yield_grade")
        if yg not in (1, 2, 3, 4, 5):
            raise_err(ERR_INVALID_REQUEST,
                      "carcass_records[%d].yield_grade must be 1, 2, 3, 4, or 5" % i)

    rec = get_or_404(store.close_outs, close_out_id, ERR_CLOSE_OUT_NOT_FOUND, "CloseOut")

    closeout_service.confirm_close_out(rec, carcass_records)
    return success_object(close_out_out(rec))
