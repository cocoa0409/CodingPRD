"""Order capture: forward pricing, as-of controls and the blue-sky reservation."""
from datetime import time as time_cls

import clock
import dates
import db
from constants import AS_OF_MAX_BUSINESS_DAYS
from errors import ApiError
from money import ZERO
from services import bluesky, positions as positions_service

PURCHASE_SIDE = ("PURCHASE", "EXCHANGE")


def _parse_cutoff(text):
    return time_cls(int(text[0:2]), int(text[3:5]), int(text[6:8]))


def compute_trade_date(fund, as_of_date):
    """calculation forward_pricing_trade_date."""
    if as_of_date is not None:
        return as_of_date
    today = clock.today()
    now_time = clock.time_of_day()
    cutoff = _parse_cutoff(fund["cutoff_time_utc"])
    if dates.is_business_day(today) and now_time < cutoff:
        return today
    return dates.next_business_day_after(today)


def check_as_of_controls(fund, as_of_date):
    """Order-of-rejection steps 13, 14 and 15."""
    if as_of_date is None:
        return
    today = clock.today()
    cutoff = _parse_cutoff(fund["cutoff_time_utc"])
    if as_of_date == today and clock.time_of_day() >= cutoff:
        raise ApiError("ERR_LATE_TRADE_PROHIBITED",
                       "An as-of order for today may not be captured after the fund cutoff.")
    if as_of_date > today or not dates.is_business_day(as_of_date):
        raise ApiError("ERR_AS_OF_FUTURE_DATE",
                       "as_of_date must be a past-or-present business date.")
    if dates.business_days_between(as_of_date, today) > AS_OF_MAX_BUSINESS_DAYS:
        raise ApiError("ERR_AS_OF_WINDOW_EXCEEDED",
                       "as_of_date is more than three business days before the current business date.")


def resolve_registration(trade_type, account, share_class_id, exchange_target_share_class_id,
                         trade_date_text, gross_amount):
    """Order-of-rejection steps 25 and 28 for purchase-side capture."""
    if trade_type not in PURCHASE_SIDE:
        return None
    target_class_id = (exchange_target_share_class_id
                       if trade_type == "EXCHANGE" else share_class_id)
    bluesky.expire_stale(target_class_id, account["state_code"], trade_date_text)
    registration = bluesky.select(target_class_id, account["state_code"], trade_date_text)
    if registration is None:
        raise ApiError("ERR_BLUE_SKY_NOT_REGISTERED",
                       "No blue-sky registration covers this class, state and trade date.")
    if trade_type == "PURCHASE":
        if gross_amount > bluesky.remaining(registration):
            raise ApiError("ERR_BLUE_SKY_CAPACITY_EXCEEDED",
                           "The purchase exceeds the registration's remaining capacity.")
    return registration


def check_share_sufficiency(trade_type, account_id, share_class_id, shares_requested):
    """Order-of-rejection step 29 at capture."""
    if trade_type not in ("REDEMPTION", "EXCHANGE"):
        return
    position = positions_service.find(account_id, share_class_id)
    held = position["shares"] if position is not None else ZERO
    if shares_requested > held:
        raise ApiError("ERR_INSUFFICIENT_SHARES",
                       "The position does not hold enough shares for this order.")


def capture(caller_id, account, share_class, fund, trade_type, gross_amount=None,
            shares_requested=None, as_of_date=None, dealer_reference=None,
            exchange_target_share_class_id=None, originating_plan_id=None,
            check_as_of=True):
    """Runs the remaining capture guards and books the order."""
    if check_as_of:
        check_as_of_controls(fund, as_of_date)

    if trade_type in PURCHASE_SIDE and fund["status"] == "CLOSED_TO_NEW":
        raise ApiError("ERR_FUND_CLOSED_TO_NEW",
                       "The fund is closed to new purchase-side activity.")

    trade_date = compute_trade_date(fund, as_of_date)
    trade_date_text = dates.fmt_date(trade_date)

    registration = resolve_registration(
        trade_type, account, share_class["id"], exchange_target_share_class_id,
        trade_date_text, gross_amount)

    check_share_sufficiency(trade_type, account["id"], share_class["id"], shares_requested)

    trade = db.create(db.store.trades, {
        "account_id": account["id"],
        "share_class_id": share_class["id"],
        "exchange_target_share_class_id": exchange_target_share_class_id,
        "parent_distribution_id": None,
        "originating_plan_id": originating_plan_id,
        "blue_sky_registration_id": registration["id"] if registration is not None else None,
        "trade_type": trade_type,
        "gross_amount": gross_amount,
        "shares_requested": shares_requested,
        "as_of_date": dates.fmt_date(as_of_date),
        "dealer_reference": dealer_reference,
        "received_at": clock.now_iso(),
        "trade_date": trade_date_text,
        "execution_status": "PENDING_AS_OF_APPROVAL" if as_of_date is not None else "RECEIVED",
        "settlement_status": "UNSETTLED",
        "pricing_variant": None,
        "nav_per_share_applied": None,
        "roa_qualifying_amount": None,
        "roa_basis_variant": None,
        "sales_load_pct": None,
        "sales_load_amount": None,
        "net_invested_amount": None,
        "shares_transacted": None,
        "gross_proceeds_amount": None,
        "cdsc_amount": None,
        "net_proceeds_amount": None,
        "exchange_target_shares": None,
        "restated_share_delta": None,
        "captured_by_user_id": caller_id,
        "approved_by_user_id": None,
        "cancel_reason": None,
        "reversal_reason": None,
    })

    if registration is not None and trade_type == "PURCHASE":
        bluesky.reserve(registration, gross_amount)

    return trade
