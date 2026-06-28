"""Cross-cutting business validation helpers (PRD §2.6, §2.9, §1.4).

These encode the fixed precedence ladder used by route handlers:
  auth (1) -> rbac (2) -> path existence (3) -> reference existence (4) ->
  body shape (5) -> OCC (6) -> state legality (7) -> posture gate (8) ->
  seller-block (9) -> domain guards (10+).
"""

from flask import g

import errors
from db import db


# --- priority 2: Seller ownership on order/pledge create -------------------

def enforce_seller_ownership(body_seller_id):
    """When the acting role is Seller, X-User-ID must equal the body seller_id
    (PRD §2.1). Other roles bypass this check."""
    if g.user_role == "Seller":
        if g.user_id != body_seller_id:
            raise errors.forbidden("Seller may only act crediting themselves")


def enforce_seller_reads_own(resource_seller_id):
    """When the acting role is Seller, a read of an order/pledge is allowed only
    when its seller_id equals X-User-ID (PRD §2.1)."""
    if g.user_role == "Seller":
        if g.user_id != resource_seller_id:
            raise errors.forbidden("Seller may only read their own resource")


# --- priority 4: body FK reference existence within campaign ---------------

def resolve_campaign_ref(campaign_id):
    c = db.campaigns.get(campaign_id)
    if c is None:
        raise errors.reference_not_found("campaign_id not found")
    return c


def resolve_seller_ref(seller_id, campaign_id):
    s = db.sellers.get(seller_id)
    if s is None or s["campaign_id"] != campaign_id:
        raise errors.reference_not_found("seller_id not found in the named campaign")
    return s


def resolve_product_ref(product_id, campaign_id):
    p = db.products.get(product_id)
    if p is None or p["campaign_id"] != campaign_id:
        raise errors.reference_not_found("product_id not found in the named campaign")
    return p


def resolve_volunteer_ref(volunteer_id, campaign_id):
    v = db.volunteers.get(volunteer_id)
    if v is None or v["campaign_id"] != campaign_id:
        raise errors.reference_not_found("volunteer_id not found in the named campaign")
    return v


# --- priority 8: campaign-posture gate -------------------------------------

def require_campaign_active_for_create(campaign):
    """A child create requires the campaign posture to be ACTIVE. DRAFT blocks
    all child create; FROZEN/CLOSED/etc. also block create. (PRD §2.9, §3.1)."""
    if campaign["posture"] != "ACTIVE":
        raise errors.campaign_not_active(
            "Campaign must be ACTIVE to create children")


def require_campaign_active(campaign):
    """A forward-progress child transition requires posture ACTIVE. DRAFT and
    FROZEN both block; this is ERR_CAMPAIGN_NOT_ACTIVE (PRD §2.9)."""
    if campaign["posture"] != "ACTIVE":
        raise errors.campaign_not_active(
            "Campaign must be ACTIVE for this operation")
