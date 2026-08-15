import re
from flask import Blueprint, request

import store as db
from auth import authorize
from envelope import obj, page
from errors import ApiError
from logic import (new_common, touch, get_or_404, refresh_portfolio)
from serialize import security_out
from validate import body, no_unknown, req_str, req_int, req_enum, pagination

bp = Blueprint("securities", __name__)

ASSET_CLASSES = {"US_EQUITY", "INTL_EQUITY", "FIXED_INCOME", "CASH_EQUIVALENT",
                 "ALTERNATIVES"}
TICKER_RE = __import__("re").compile(r"^[A-Z0-9.]+$")


@bp.post("/advisory/securities")
def create_security():
    authorize("ComplianceOfficer")
    b = body()
    no_unknown(b, {"ticker", "asset_class", "initial_price_cents"})
    ticker = req_str(b, "ticker")
    if not ticker or not TICKER_RE.match(ticker):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "ticker must be uppercase A-Z, 0-9, dots")
    asset_class = req_enum(b, "asset_class", ASSET_CLASSES)
    price = req_int(b, "initial_price_cents", lo=1)
    for s in db.securities.values():
        if s["ticker"] == ticker:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "ticker must be unique")
    s = new_common()
    s.update({"ticker": ticker, "asset_class": asset_class,
              "price_cents": price, "trading_status": "LISTED"})
    db.securities[s["id"]] = s
    return obj(security_out(s), 201)


@bp.get("/advisory/securities")
def list_securities():
    authorize("Advisor", "ComplianceOfficer")
    limit, offset = pagination()
    rows = sorted(db.securities.values(), key=lambda e: (e["created_dt"], e["_seq"]))
    ticker = request.args.get("ticker")
    if ticker is not None:
        rows = [s for s in rows if s["ticker"] == ticker]
    ac = request.args.get("asset_class")
    if ac is not None:
        rows = [s for s in rows if s["asset_class"] == ac]
    ts = request.args.get("trading_status")
    if ts is not None:
        rows = [s for s in rows if s["trading_status"] == ts]
    total = len(rows)
    return page([security_out(s) for s in rows[offset:offset + limit]],
                limit, offset, total)


@bp.get("/advisory/securities/<sid>")
def get_security(sid):
    authorize("Advisor", "ComplianceOfficer")
    s = get_or_404(db.securities, sid)
    return obj(security_out(s))


@bp.post("/advisory/securities/<sid>/reprice")
def reprice_security(sid):
    authorize("ComplianceOfficer")
    b = body()
    no_unknown(b, {"new_price_cents"})
    new_price = req_int(b, "new_price_cents", lo=1)
    s = get_or_404(db.securities, sid)
    s["price_cents"] = new_price
    touch(s)
    # Cascade: held positions (quantity > 0) recompute; affected portfolios
    # recompute totals + drift; their MODELED withdrawals revert.
    affected_pf_ids = []
    for p in db.positions.values():
        if p["security_id"] == sid and p["quantity"] > 0:
            touch(p)
            if p["portfolio_id"] not in affected_pf_ids:
                affected_pf_ids.append(p["portfolio_id"])
    for pf_id in affected_pf_ids:
        refresh_portfolio(db.portfolios[pf_id], revert=True)
    return obj(security_out(s))


@bp.post("/advisory/securities/<sid>/set-trading-status")
def set_trading_status(sid):
    authorize("ComplianceOfficer")
    b = body()
    no_unknown(b, {"trading_status"})
    new_status = req_enum(b, "trading_status", {"LISTED", "HALTED", "DELISTED"})
    s = get_or_404(db.securities, sid)
    current = s["trading_status"]
    allowed = {("LISTED", "HALTED"), ("HALTED", "LISTED"),
               ("LISTED", "DELISTED"), ("HALTED", "DELISTED")}
    if (current, new_status) not in allowed:
        raise ApiError("ERR_SECURITY_INVALID_STATE", 409,
                       f"Cannot transition {current} -> {new_status}")
    if new_status == "DELISTED":
        for p in db.positions.values():
            if p["security_id"] == sid and p["quantity"] > 0:
                raise ApiError("ERR_SECURITY_IN_USE", 422,
                               "Cannot delist while positions hold the security")
    s["trading_status"] = new_status
    touch(s)
    return obj(security_out(s))
