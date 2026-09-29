"""The hedge book: opening and unwinding positions (PRD 3.9)."""
from decimal import Decimal

from flask import Blueprint

import calc
import response
import store
import validate
from constants import INSTRUMENTS, VOL_TIERS
from errors import ERR_INVALID_HEDGE_STATE, ERR_MATURITY_IN_PAST, fail
from routes.helpers import find, listing
from store import bump, q

bp = Blueprint("hedges", __name__)
ZERO = Decimal("0")


@bp.post("/hedge-positions")
def open_position():
    validate.auth("FeedstockTrader")
    data = validate.body()
    instrument = validate.get_enum(data, "instrument", INSTRUMENTS)
    notional = validate.get_num(data, "notional_units", 0, 1000000, 3, exclusive_min=True)
    strike = validate.get_num(data, "strike_price_usd", 0, 10000, 2, exclusive_min=True)
    maturity_at = validate.get_dt(data, "maturity_at")
    tier = validate.get_enum(data, "volatility_tier", VOL_TIERS, required=False, default=None)

    if maturity_at <= store.now():
        fail(ERR_MATURITY_IN_PAST,
             "Field 'maturity_at' must be strictly after the current logical clock.")

    notional = q(notional, 3)
    strike = q(strike, 2)
    margin = calc.hedge_margin(instrument, notional, strike, tier)

    row = store.new_row()
    row.update({
        "instrument": instrument,
        "notional_units": notional,
        "strike_price_usd": strike,
        "maturity_at": maturity_at,
        "gross_notional_usd": margin["gross_notional_usd"],
        "base_margin_usd": margin["base_margin_usd"],
        "volatility_tier": margin["volatility_tier"],
        "volatility_adder_usd": margin["volatility_adder_usd"],
        "total_margin_usd": margin["total_margin_usd"],
        "settlement_price_usd": None,
        "realized_pnl_usd": q(ZERO, 2),
        "status": "OPEN",
    })
    store.hedges[row["id"]] = row
    return response.ok(row, 201)


@bp.get("/hedge-positions/<hedge_id>")
def read_position(hedge_id):
    validate.auth("FeedstockTrader", "ComplianceOfficer")
    return response.ok(find("hedge", hedge_id))


@bp.get("/hedge-positions")
def list_positions():
    validate.auth("FeedstockTrader", "ComplianceOfficer")
    rows, limit, offset = listing(store.table_rows(store.hedges), {
        "instrument": "instrument",
        "volatility_tier": "volatility_tier",
        "status": "status",
    })
    return response.page(rows, limit, offset)


@bp.post("/hedge-positions/<hedge_id>/unwinds")
def unwind_position(hedge_id):
    validate.auth("FeedstockTrader")
    hedge = find("hedge", hedge_id)
    data = validate.body()
    settlement = validate.get_num(data, "settlement_price_usd", 0, 10000, 2)

    if hedge["status"] != "OPEN":
        fail(ERR_INVALID_HEDGE_STATE,
             "Only an OPEN position may be unwound; this one is %s." % hedge["status"])

    settlement = q(settlement, 2)
    hedge["settlement_price_usd"] = settlement
    hedge["realized_pnl_usd"] = q(
        (settlement - hedge["strike_price_usd"]) * hedge["notional_units"], 2)
    hedge["base_margin_usd"] = q(ZERO, 2)
    hedge["volatility_adder_usd"] = q(ZERO, 2)
    hedge["total_margin_usd"] = q(ZERO, 2)
    hedge["volatility_tier"] = "T1"
    hedge["status"] = "UNWOUND"
    bump(hedge)
    return response.ok(hedge)
