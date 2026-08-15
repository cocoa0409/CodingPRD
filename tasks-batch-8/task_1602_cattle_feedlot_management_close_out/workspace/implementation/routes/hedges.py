"""Hedge position endpoints."""
from flask import Blueprint

import store
from auth import authenticate, authorize
from errors import ERR_LOT_NOT_FOUND, ERR_HEDGE_NOT_FOUND, ERR_INVALID_REQUEST, raise_err
from serializers import hedge_position_out
from services import hedge_service
from util import body_json, get_or_404, req_str, req_int, opt_int, opt_enum, \
    req_date, success_object, valid_year_month

bp = Blueprint("hedges", __name__)


@bp.route("/feedlot/hedges", methods=["POST"])
def create_hedge():
    _, role = authenticate()
    authorize(role, ["RiskManager"])
    body = body_json()

    lot_id = req_str(body, "lot_id")
    contract_month = req_str(body, "contract_month")
    side = opt_enum(body, "side", ("SHORT", "LONG"), "SHORT")
    quantity_contracts = req_int(body, "quantity_contracts")
    entry_price_cents_per_cwt = req_int(body, "entry_price_cents_per_cwt")
    expected_lot_version = opt_int(body, "expected_lot_version")

    # Validate contract_month format
    if not valid_year_month(contract_month):
        raise_err(ERR_INVALID_REQUEST, "contract_month must be in YYYY-MM format")

    # Validate ranges
    if quantity_contracts < 1:
        raise_err(ERR_INVALID_REQUEST, "quantity_contracts must be >= 1")
    if entry_price_cents_per_cwt <= 0:
        raise_err(ERR_INVALID_REQUEST, "entry_price_cents_per_cwt must be > 0")

    # Validate lot exists
    lot = store.lots.get(lot_id)
    if lot is None:
        raise_err(ERR_LOT_NOT_FOUND, "Lot not found: %s" % lot_id)

    rec = hedge_service.create_hedge(
        lot, contract_month, side, quantity_contracts,
        entry_price_cents_per_cwt, expected_lot_version
    )
    return success_object(hedge_position_out(rec), 201)


@bp.route("/feedlot/hedges/<hedge_id>/offset", methods=["POST"])
def offset_hedge(hedge_id):
    _, role = authenticate()
    authorize(role, ["RiskManager"])
    body = body_json()

    exit_price_cents_per_cwt = req_int(body, "exit_price_cents_per_cwt")
    offset_date = req_date(body, "offset_date")

    if exit_price_cents_per_cwt <= 0:
        raise_err(ERR_INVALID_REQUEST, "exit_price_cents_per_cwt must be > 0")

    rec = get_or_404(store.hedge_positions, hedge_id, ERR_HEDGE_NOT_FOUND, "HedgePosition")

    hedge_service.offset_hedge(rec, exit_price_cents_per_cwt, offset_date)
    return success_object(hedge_position_out(rec))
