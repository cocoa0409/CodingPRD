"""Reusable ordered-band guards (PRD 2.7 bands 4, 10, 11, 12, 16)."""

from errors import ApiError
from util import clock
from services import aggregates, lookups


# ------------------------------------------------------------------ band 4

def own_or_403(actual_owner_id, user_id):
    if actual_owner_id != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def owns_lot(lot, user_id):
    own_or_403(lot["seller_id"], user_id)


def owns_listing(listing, user_id):
    lot = lookups.lot_of_listing(listing)
    own_or_403(lot["seller_id"], user_id)


def owns_order(order, user_id):
    own_or_403(order["buyer_id"], user_id)


# ----------------------------------------------------------------- band 10

def require_qualified(buyer):
    if buyer["qualification_status"] != "QUALIFIED":
        raise ApiError("ERR_BUYER_NOT_QUALIFIED")


# ----------------------------------------------------------------- band 11

def check_buyer_geography(lot, buyer):
    policy = lookups.policy_of_lot(lot)
    if policy is None:
        return
    prohibited = policy.get("prohibited_buyer_state_codes") or []
    if buyer["state_code"] in prohibited:
        raise ApiError("ERR_BUYER_STATE_PROHIBITED")


def check_anti_shill(lot, buyer):
    seller = lookups.seller_of_lot(lot)
    if seller is not None and seller["tax_id"] == buyer["tax_id"]:
        raise ApiError("ERR_SHILL_BIDDING_PROHIBITED")


# ----------------------------------------------------------------- band 12

def require_window_open(listing):
    now = clock.now()
    if now < listing["window_start_at"]:
        raise ApiError("ERR_LISTING_WINDOW_NOT_OPEN")
    if listing["effective_close_at"] is not None and now >= listing["effective_close_at"]:
        raise ApiError("ERR_LISTING_WINDOW_CLOSED")


# ----------------------------------------------------------------- band 16

def admit_exposure(buyer, prospective_exposure_cents):
    if prospective_exposure_cents > aggregates.credit_ceiling(buyer):
        raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED")
