"""Seller endpoints."""

from flask import Blueprint

import db
import errors
import helpers
import middleware
import services
from helpers import (
    get_campaign, get_group, get_seller, new_id, now_iso,
    req_string, serialize_seller,
)
from middleware import get_body
from response import success_object

bp = Blueprint("sellers", __name__)


@bp.post("/fundraiser/sellers")
def create_seller():
    middleware.require_role("GroupCoordinator")
    body = get_body(required=True)
    group_id = req_string(body, "group_id")
    display_name = req_string(body, "display_name")
    group = get_group(group_id)
    campaign = get_campaign(group["campaign_id"])
    if campaign["status"] not in ("DRAFT", "OPEN"):
        raise errors.err_invalid_state("Sellers may only be enrolled while the campaign is DRAFT or OPEN")
    for s in db.sellers.values():
        if s["group_id"] == group_id and s["display_name"] == display_name:
            raise errors.err_duplicate_seller_name()
    sid = new_id()
    seller = {
        "id": sid,
        "group_id": group_id,
        "campaign_id": group["campaign_id"],
        "display_name": display_name,
        "status": "ENROLLED",
        "units_sold": 0,
        "revenue_cents": 0,
        "orders_count": 0,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }
    db.sellers[sid] = seller
    return success_object(serialize_seller(seller), status=201)


@bp.get("/fundraiser/sellers/<sid>")
def read_seller(sid):
    middleware.any_role()
    seller = get_seller(sid)
    return success_object(serialize_seller(seller))


@bp.post("/fundraiser/sellers/<sid>/suspend")
def suspend_seller(sid):
    middleware.require_role("GroupCoordinator")
    seller = get_seller(sid)
    get_body()
    if seller["status"] != "ACTIVE":
        raise errors.err_invalid_state("Seller is not ACTIVE")
    seller["status"] = "SUSPENDED"
    helpers.touch(seller)
    return success_object(serialize_seller(seller))


@bp.post("/fundraiser/sellers/<sid>/reinstate")
def reinstate_seller(sid):
    middleware.require_role("GroupCoordinator")
    seller = get_seller(sid)
    get_body()
    if seller["status"] != "SUSPENDED":
        raise errors.err_invalid_state("Seller is not SUSPENDED")
    seller["status"] = "ACTIVE"
    helpers.touch(seller)
    return success_object(serialize_seller(seller))


@bp.post("/fundraiser/sellers/<sid>/withdraw")
def withdraw_seller(sid):
    middleware.require_role("GroupCoordinator")
    seller = get_seller(sid)
    get_body()
    if seller["status"] not in ("ENROLLED", "ACTIVE", "SUSPENDED"):
        raise errors.err_invalid_state("Seller is already WITHDRAWN")
    for o in db.orders.values():
        if o["seller_id"] == sid and o["cleared_cents"] > 0:
            raise errors.err_order_has_cleared_payments()
    # Cascade: DRAFT/SUBMITTED orders -> CANCELLED (SUBMITTED post reversal)
    for o in list(db.orders.values()):
        if o["seller_id"] != sid:
            continue
        if o["status"] == "DRAFT":
            o["status"] = "CANCELLED"
            helpers.touch(o)
        elif o["status"] == "SUBMITTED":
            services.cancel_order(o, post_reversal=True)
    # Cascade: QUEUED/AWARDED prize awards -> FORFEITED
    for a in list(db.prize_awards.values()):
        if a["seller_id"] == sid and a["status"] in ("QUEUED", "AWARDED"):
            prize = db.prizes[a["prize_id"]]
            services._forfeit_award(a, prize)
    seller["status"] = "WITHDRAWN"
    helpers.touch(seller)
    campaign = db.campaigns.get(seller["campaign_id"])
    if campaign is not None:
        services.recompute_campaign_totals(campaign)
    return success_object(serialize_seller(seller))
