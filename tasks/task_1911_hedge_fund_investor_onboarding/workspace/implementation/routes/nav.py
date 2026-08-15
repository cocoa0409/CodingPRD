"""NavPeriod and Series endpoints (PRD 3.6)."""
from flask import Blueprint

from db import db
from errors import raise_error, ERR_INVALID_STATE, ERR_INVALID_REQUEST, ERR_STALE_VERSION
from middleware import require_roles
from response import success_object, success_list
from services.core import (
    serialize, paginate, filter_by, get_fund, get_share_class, get_nav_period,
    get_series, child_of,
)
from services.periods import open_period, finalize_period, close_period
from util import parse_datetime
from validate import get_body, req_datetime, req_int, opt_int

bp = Blueprint("nav", __name__)

NAV_READERS = ("FundAdmin", "ComplianceOfficer", "TransferAgent", "PortfolioManager")


@bp.post("/funds/<fund_id>/nav-periods")
def create_nav_period(fund_id):
    require_roles("FundAdmin")
    fund = get_fund(fund_id)
    body = get_body()
    period_end = req_datetime(body, "period_end_utc")
    # Only one OPEN period per fund (singleton open slot).
    for p in db["nav_periods"].values():
        if p["fund_id"] == fund["id"] and p["status"] == "OPEN":
            raise_error(ERR_INVALID_STATE, "fund already has an OPEN nav period")
    if parse_datetime(period_end) <= parse_datetime(__import__("util").CLOCK.now_iso()):
        raise_error(ERR_INVALID_REQUEST, "period_end_utc must be after period start")
    period = open_period(fund, period_end)
    return success_object(serialize(period), 201)


@bp.get("/funds/<fund_id>/nav-periods")
def list_nav_periods(fund_id):
    require_roles(*NAV_READERS)
    fund = get_fund(fund_id)
    items, total, limit, offset = paginate(filter_by(
        db["nav_periods"].values(), fund_id=fund["id"]))
    return success_list(items, total, limit, offset)


@bp.get("/funds/<fund_id>/nav-periods/<period_id>")
def get_nav_period_route(fund_id, period_id):
    require_roles(*NAV_READERS)
    fund = get_fund(fund_id)
    period = get_nav_period(period_id)
    child_of(period, "fund_id", fund["id"])
    return success_object(serialize(period))


@bp.post("/funds/<fund_id>/nav-periods/<period_id>/finalize")
def finalize_nav_period(fund_id, period_id):
    require_roles("FundAdmin")
    fund = get_fund(fund_id)
    period = get_nav_period(period_id)
    child_of(period, "fund_id", fund["id"])
    body = get_body()
    if period["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE, "nav period is not OPEN")
    gross_return_bps = req_int(body, "gross_return_bps")
    expected = opt_int(body, "expected_fund_version")
    if expected is not None and expected != fund["version"]:
        raise_error(ERR_STALE_VERSION, "expected_fund_version does not match fund version")
    finalize_period(fund, period, gross_return_bps)
    return success_object(serialize(period))


@bp.post("/funds/<fund_id>/nav-periods/<period_id>/close")
def close_nav_period(fund_id, period_id):
    require_roles("FundAdmin")
    fund = get_fund(fund_id)
    period = get_nav_period(period_id)
    child_of(period, "fund_id", fund["id"])
    get_body()
    if period["status"] != "NAV_FINALIZED":
        raise_error(ERR_INVALID_STATE, "nav period is not NAV_FINALIZED")
    close_period(fund, period)
    return success_object(serialize(period))


# ---------------------------------------------------------------------------
# Series (nested reads)
# ---------------------------------------------------------------------------


@bp.get("/funds/<fund_id>/share-classes/<class_id>/series")
def list_series(fund_id, class_id):
    require_roles(*NAV_READERS)
    fund = get_fund(fund_id)
    share_class = get_share_class(class_id)
    child_of(share_class, "fund_id", fund["id"])
    items, total, limit, offset = paginate(filter_by(
        db["series"].values(), share_class_id=share_class["id"]))
    return success_list(items, total, limit, offset)


@bp.get("/funds/<fund_id>/share-classes/<class_id>/series/<series_id>")
def get_series_route(fund_id, class_id, series_id):
    require_roles(*NAV_READERS)
    fund = get_fund(fund_id)
    share_class = get_share_class(class_id)
    child_of(share_class, "fund_id", fund["id"])
    series = get_series(series_id)
    child_of(series, "share_class_id", share_class["id"])
    return success_object(serialize(series))
