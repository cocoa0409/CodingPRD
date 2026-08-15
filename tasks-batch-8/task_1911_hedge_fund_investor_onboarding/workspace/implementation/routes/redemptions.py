"""RedemptionRequest endpoints (PRD 3.7): notice, lockup, suspension, cancel."""
from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE, ERR_NOT_FOUND, ERR_INVALID_REQUEST,
    ERR_INVALID_AMOUNT, ERR_INSUFFICIENT_BALANCE, ERR_LOCKUP_NOT_EXPIRED,
    ERR_INSUFFICIENT_NOTICE, ERR_REDEMPTIONS_SUSPENDED,
)
from middleware import require_roles, check_investor_owns
from response import success_object, success_list
from services.core import (
    stamp_new, touch, serialize, paginate, filter_by,
    get_fund, get_share_class, get_nav_period, get_capital_account,
    get_redemption, child_of, class_nav_per_share, applicable_liquidity_reduction,
)
from util import CLOCK, parse_datetime, quantize_half_up, dec
from validate import get_body, req_str, opt_int, opt_number

bp = Blueprint("redemptions", __name__)

RED_LISTERS = ("FundAdmin", "ComplianceOfficer", "TransferAgent", "PortfolioManager")
RED_READERS = ("FundAdmin", "ComplianceOfficer", "TransferAgent", "PortfolioManager", "Investor")


def _load_redemption_under_fund(fund_id, red_id):
    fund = get_fund(fund_id)
    red = get_redemption(red_id)
    child_of(red, "_fund_id", fund["id"])
    return fund, red


@bp.post("/funds/<fund_id>/redemptions")
def create_redemption(fund_id):
    caller = require_roles("Investor", "TransferAgent")
    fund = get_fund(fund_id)
    body = get_body()
    account_id = req_str(body, "capital_account_id")
    period_id = req_str(body, "requested_effective_period_id")
    amount = opt_int(body, "requested_amount_cents")
    shares = opt_number(body, "requested_shares")

    account = db["capital_accounts"].get(account_id)
    if account is None or account["_fund_id"] != fund["id"]:
        raise_error(ERR_NOT_FOUND, "capital_account_id does not belong to this fund")
    check_investor_owns(caller, account["investor_id"])
    period = db["nav_periods"].get(period_id)
    if period is None or period["fund_id"] != fund["id"]:
        raise_error(ERR_NOT_FOUND, "requested_effective_period_id does not belong to this fund")

    if (amount is None) == (shares is None):
        raise_error(ERR_INVALID_REQUEST,
                    "exactly one of requested_amount_cents and requested_shares is required")
    share_class = get_share_class(account["share_class_id"])
    if amount is None:
        if shares <= 0:
            raise_error(ERR_INVALID_AMOUNT, "requested_shares must be positive")
        amount = int(quantize_half_up(dec(shares) * class_nav_per_share(share_class)))
    if amount <= 0:
        raise_error(ERR_INVALID_AMOUNT, "requested_amount_cents must be positive")
    if amount > account["current_balance_cents"]:
        raise_error(ERR_INSUFFICIENT_BALANCE,
                    "requested amount exceeds capital account balance")

    red = stamp_new({
        "capital_account_id": account["id"],
        "investor_id": account["investor_id"],
        "requested_amount_cents": amount,
        "requested_shares": shares,
        "notice_given_at_utc": CLOCK.now_iso(),
        "requested_effective_period_id": period["id"],
        "effective_period_id": period["id"],
        "gate_applied_pct": 0,
        "settled_amount_cents": 0,
        "status": "PENDING",
        "_fund_id": fund["id"],
        "_rejection_reason": None,
    })
    db["redemptions"][red["id"]] = red
    return success_object(serialize(red), 201)


@bp.get("/funds/<fund_id>/redemptions")
def list_redemptions(fund_id):
    require_roles(*RED_LISTERS)
    fund = get_fund(fund_id)
    items = filter_by(db["redemptions"].values(),
                      _fund_id=fund["id"],
                      capital_account_id=request.args.get("capital_account_id"),
                      status=request.args.get("status"))
    items, total, limit, offset = paginate(items)
    return success_list(items, total, limit, offset)


@bp.get("/funds/<fund_id>/redemptions/<red_id>")
def get_redemption_route(fund_id, red_id):
    caller = require_roles(*RED_READERS)
    fund, red = _load_redemption_under_fund(fund_id, red_id)
    check_investor_owns(caller, red["investor_id"])
    return success_object(serialize(red))


@bp.post("/funds/<fund_id>/redemptions/<red_id>/approve")
def approve_redemption(fund_id, red_id):
    require_roles("FundAdmin")
    fund, red = _load_redemption_under_fund(fund_id, red_id)
    get_body()
    if red["status"] != "PENDING":
        raise_error(ERR_INVALID_STATE, "redemption request is not PENDING")
    account = get_capital_account(red["capital_account_id"])
    share_class = get_share_class(account["share_class_id"])

    # PRD 3.7 explicit order: lockup -> notice -> suspension -> class openness.
    if parse_datetime(account["locked_until_utc"]) > CLOCK.now():
        raise_error(ERR_LOCKUP_NOT_EXPIRED, "capital account lockup has not expired")

    period = get_nav_period(red["effective_period_id"])
    required_notice = max(0, share_class["notice_days"]
                          - applicable_liquidity_reduction(account))
    actual_notice = (parse_datetime(period["period_end_utc"])
                     - parse_datetime(red["notice_given_at_utc"])).days
    if actual_notice < required_notice:
        raise_error(ERR_INSUFFICIENT_NOTICE, "notice period requirement not met")

    if fund["suspension_status"] != "NOT_SUSPENDED":
        raise_error(ERR_REDEMPTIONS_SUSPENDED, "fund redemptions are suspended")
    if not share_class["is_open_for_redemption"]:
        raise_error(ERR_INVALID_STATE, "share class is closed to redemptions")

    red["status"] = "APPROVED"
    touch(red)
    account["status"] = "REDEMPTION_PENDING"
    touch(account)
    return success_object(serialize(red))


@bp.post("/funds/<fund_id>/redemptions/<red_id>/reject")
def reject_redemption(fund_id, red_id):
    require_roles("FundAdmin")
    fund, red = _load_redemption_under_fund(fund_id, red_id)
    body = get_body()
    if red["status"] != "PENDING":
        raise_error(ERR_INVALID_STATE, "redemption request is not PENDING")
    red["status"] = "REJECTED"
    from validate import opt_str
    red["_rejection_reason"] = opt_str(body, "rejection_reason")
    touch(red)
    return success_object(serialize(red))


@bp.post("/funds/<fund_id>/redemptions/<red_id>/cancel")
def cancel_redemption(fund_id, red_id):
    caller = require_roles("Investor")
    fund, red = _load_redemption_under_fund(fund_id, red_id)
    check_investor_owns(caller, red["investor_id"])
    get_body()
    if red["status"] != "PENDING":
        raise_error(ERR_INVALID_STATE, "redemption request is not PENDING")
    account = get_capital_account(red["capital_account_id"])
    share_class = get_share_class(account["share_class_id"])
    period = get_nav_period(red["requested_effective_period_id"])
    cutoff = parse_datetime(period["period_end_utc"]) - timedelta(
        days=share_class["notice_days"])
    if CLOCK.now() >= cutoff:
        raise_error(ERR_INVALID_STATE, "notice deadline has passed; request is locked in")
    red["status"] = "CANCELLED"
    touch(red)
    return success_object(serialize(red))
