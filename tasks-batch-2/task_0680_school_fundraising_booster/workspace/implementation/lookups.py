"""Path-resource resolution helpers. Raise ERR_NOT_FOUND when a path id is absent.

Path identifiers are validated left-to-right (PRD §2.6).
"""

import errors
from db import db


def get_campaign(campaign_id):
    c = db.campaigns.get(campaign_id)
    if c is None:
        raise errors.not_found("Campaign not found")
    return c


def get_prize_tier(prize_tier_id):
    t = db.prize_tiers.get(prize_tier_id)
    if t is None:
        raise errors.not_found("Prize tier not found")
    return t


def get_seller(seller_id):
    s = db.sellers.get(seller_id)
    if s is None:
        raise errors.not_found("Seller not found")
    return s


def get_product(product_id):
    p = db.products.get(product_id)
    if p is None:
        raise errors.not_found("Product not found")
    return p


def get_order(order_id):
    o = db.orders.get(order_id)
    if o is None:
        raise errors.not_found("Order not found")
    return o


def get_pledge(pledge_id):
    p = db.pledges.get(pledge_id)
    if p is None:
        raise errors.not_found("Pledge not found")
    return p


def get_volunteer(volunteer_id):
    v = db.volunteers.get(volunteer_id)
    if v is None:
        raise errors.not_found("Volunteer not found")
    return v


def get_shift(shift_id):
    s = db.shifts.get(shift_id)
    if s is None:
        raise errors.not_found("Shift not found")
    return s


def get_disbursement(disbursement_id):
    d = db.disbursements.get(disbursement_id)
    if d is None:
        raise errors.not_found("Disbursement not found")
    return d
