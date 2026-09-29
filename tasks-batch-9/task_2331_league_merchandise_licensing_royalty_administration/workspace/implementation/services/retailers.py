"""Retailer-authorization aggregate predicates (PRD 3.6, global rules 36 and 38)."""

from datetime import timedelta

import constants as K
import db
from db import S
from errors import ApiError
from services import domain

BUFFER = K.RETAILER_WINDOW_BUFFER_DAYS


def _window(auth):
    return (db.parse_date(auth["authorized_from"]), db.parse_date(auth["authorized_to"]))


def check_window_rule(licensee_id, retailer_name, channel_class, start, end, exclude_id=None):
    """Rule 38: closed window well formed and no crowding within thirty days."""
    if start > end:
        raise ApiError("ERR_RETAILER_WINDOW_CONFLICT",
                       "authorized_from must be at or before authorized_to.")
    for other in domain.authorizations_of(licensee_id):
        if exclude_id is not None and other["id"] == exclude_id:
            continue
        if other["status"] not in ("PENDING", "AUTHORIZED"):
            continue
        if other["retailer_name"] != retailer_name:
            continue
        if other["channel_class"] != channel_class:
            continue
        other_start, other_end = _window(other)
        if start <= other_end + timedelta(days=BUFFER) and \
                other_start <= end + timedelta(days=BUFFER):
            raise ApiError("ERR_RETAILER_WINDOW_CONFLICT",
                           "Another authorization for this retailer and channel lies "
                           "within thirty days of the requested window.")


def check_off_price_capacity(licensee_id, channel_class, start, end, exclude_id=None):
    """Rule 36: at most two concurrent off-price accounts per licensee."""
    if channel_class != "OFF_PRICE":
        return
    count = 1
    for other in domain.authorizations_of(licensee_id):
        if exclude_id is not None and other["id"] == exclude_id:
            continue
        if other["status"] not in ("PENDING", "AUTHORIZED"):
            continue
        if other["channel_class"] != "OFF_PRICE":
            continue
        other_start, other_end = _window(other)
        if other_start <= end and start <= other_end:
            count += 1
    if count > K.MAX_CONCURRENT_OFF_PRICE:
        raise ApiError("ERR_OFF_PRICE_CAPACITY_EXCEEDED",
                       "At most two concurrent off-price accounts are permitted.")


def portfolio_frozen(licensee_id):
    for agreement in domain.agreements_of(licensee_id):
        if agreement["contract_status"] in ("ACTIVE", "SUSPENDED") and \
                agreement["compliance_posture"] == "FROZEN":
            return True
    return False


def usable_for_period(auth, period_quarter):
    """Rule 24: the authorization is usable for the reported period."""
    quarter_end = db.quarter_end_date(period_quarter)
    if auth["status"] == "AUTHORIZED":
        status_ok = True
    elif auth["status"] == "SUSPENDED" and auth["suspension_reason"] == "NO_APPROVED_SKUS":
        suspended_at = auth.get("suspended_at")
        status_ok = bool(suspended_at) and db.parse_date(suspended_at[0:10]) > quarter_end
    else:
        status_ok = False
    if not status_ok:
        return False
    start = db.parse_date(auth["authorized_from"])
    end = db.parse_date(auth["authorized_to"])
    return start <= quarter_end <= end


def find_auth(auth_id):
    auth = S.authorizations.get(auth_id)
    if auth is None:
        raise ApiError("ERR_AUTHORIZATION_NOT_FOUND")
    return auth
