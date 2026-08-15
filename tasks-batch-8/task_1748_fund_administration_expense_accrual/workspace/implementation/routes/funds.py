"""Fund endpoints: create, trial balance, fiscal-year close."""
from datetime import date, timedelta
from decimal import Decimal

from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import ALL_ROLES, get_context, require_roles
from response import created, ok
from services import navmath
from services.navmath import D
from validation import parse_body, query_param_date, require_path_entity

bp = Blueprint("funds", __name__)

FUND_SCHEMA = {
    "fund_name": ("string", True, None),
    "ticker": ("string", True, None),
    "base_currency": ("enum", True, ["USD", "EUR", "GBP"]),
    "fiscal_year_end": ("fiscal_md", True, None),
    "adviser_name": ("string", True, None),
    "admin_fee_bps": ("posnumber", True, None),
    "adviser_fee_tiers": ("tiers", True, None),
    "day_count_convention": ("enum", True, ["ACT_365", "ACT_360"]),
}


@bp.post("/funds")
def create_fund():
    get_context()
    require_roles(["FundController"])
    body = parse_body(FUND_SCHEMA)
    for existing in store.funds.values():
        if existing["ticker"] == body["ticker"]:
            raise ApiError("ERR_TICKER_ALREADY_EXISTS", 409, "Fund ticker already exists")
    fund = {
        "id": db.new_id(),
        "fund_name": body["fund_name"],
        "ticker": body["ticker"],
        "base_currency": body["base_currency"],
        "fiscal_year_end": body["fiscal_year_end"],
        "adviser_name": body["adviser_name"],
        "admin_fee_bps": D(body["admin_fee_bps"]),
        "adviser_fee_tiers": [
            {"up_to_net_assets": t["up_to_net_assets"], "rate_bps": t["rate_bps"]}
            for t in body["adviser_fee_tiers"]
        ],
        "day_count_convention": body["day_count_convention"],
        "last_closed_fiscal_year_end": None,
    }
    db.new_common(fund)
    store.funds[fund["id"]] = fund
    return created(fund)


@bp.get("/funds/<fund_id>/trial-balance")
def trial_balance(fund_id):
    get_context()
    fund = require_path_entity(store.funds, fund_id)
    require_roles(ALL_ROLES)
    as_of = query_param_date("as_of_date")
    total_mv = Decimal("0")
    total_accr = Decimal("0")
    total_tna = Decimal("0")
    found = False
    for cls in store.share_classes.values():
        if cls["fund_id"] != fund["id"]:
            continue
        finals = [n for n in store.nav_records.values()
                  if n["share_class_id"] == cls["id"] and n["status"] == "FINAL"
                  and n["accounting_date"] <= as_of]
        if not finals:
            continue  # classes without a FINAL record contribute zero
        rec = max(finals, key=lambda n: n["accounting_date"])
        found = True
        total_mv += D(rec["gross_asset_value"])
        total_accr += D(rec["expense_accrual_total"])
        total_tna += D(rec["total_net_assets"])
    if not found:
        raise ApiError("ERR_NO_FINAL_NAV_IN_PERIOD", 422,
                       "No FINAL NavRecord of the fund on or before as_of_date")
    return ok({
        "as_of_date": as_of,
        "total_market_value": total_mv,
        "total_accrued_expenses": total_accr,
        "total_net_assets": total_tna,
    })


def _fiscal_year_start(fye):
    """First day of the fiscal year ending on fye: same MM-DD one year earlier,
    plus one day."""
    try:
        prev = date(fye.year - 1, fye.month, fye.day)
    except ValueError:  # Feb 29 in a non-leap prior year
        prev = date(fye.year - 1, fye.month, fye.day - 1)
    return prev + timedelta(days=1)


@bp.post("/funds/<fund_id>/fiscal-year-close")
def fiscal_year_close(fund_id):
    get_context()
    fund = require_path_entity(store.funds, fund_id)
    require_roles(["FundController"])
    body = parse_body({"fiscal_year_end_date": ("date", True, None)})
    fye_str = body["fiscal_year_end_date"]
    if fye_str[5:] != fund["fiscal_year_end"]:
        raise ApiError("ERR_VALIDATION", 400,
                       "fiscal_year_end_date does not match the fund's fiscal_year_end")
    fye = navmath.date_of(fye_str)
    start = _fiscal_year_start(fye).isoformat()

    # Compliance gates (priority 7): all in-year records FINAL, no OPEN or
    # ESCALATED break of the fund, all in-year filings FILED.
    class_ids = {c["id"] for c in store.share_classes.values()
                 if c["fund_id"] == fund["id"]}
    for nav in store.nav_records.values():
        if nav["share_class_id"] in class_ids \
                and start <= nav["accounting_date"] <= fye_str \
                and nav["status"] != "FINAL":
            raise ApiError("ERR_FISCAL_CLOSE_BLOCKED", 409,
                           "A NavRecord inside the fiscal year is not FINAL")
    for brk in store.reconciliation_breaks.values():
        if brk["fund_id"] == fund["id"] and brk["status"] in ("OPEN", "ESCALATED"):
            raise ApiError("ERR_FISCAL_CLOSE_BLOCKED", 409,
                           "A reconciliation break of the fund is not resolved")
    for filing in store.regulatory_filings.values():
        if filing["fund_id"] == fund["id"] \
                and start <= filing["period_end"] <= fye_str \
                and filing["status"] != "FILED":
            raise ApiError("ERR_FISCAL_CLOSE_BLOCKED", 409,
                           "A regulatory filing inside the fiscal year is not FILED")

    # Temporal (priority 8): the close date must not lie after the clock.
    if fye > db.clock_today():
        raise ApiError("ERR_PERIOD_NOT_ENDED", 422,
                       "fiscal_year_end_date is after the logical clock date")

    fund["last_closed_fiscal_year_end"] = fye_str
    db.touch(fund)
    return ok(fund)
