"""SaveOffer top-level endpoints (list/get/accept/decline)."""
from flask import Blueprint, request

import domain
from db import bump, by_created, store
from errors import ApiError
from middleware import own_check, require_roles
from response import ok_obj, paginate
from serialize import ser_save_offer
from util import days

bp = Blueprint("offers", __name__)


def _offer_and_owner_check(oid, uid, role):
    offer = domain.fetch(store.save_offers, oid)
    sub = store.subscriptions.get(offer["subscription_id"])
    own_check(uid, role, sub["subscriber_id"] if sub else None)
    return offer


@bp.get("/api/save-offers")
def list_offers():
    require_roles("ServiceRep", "CirculationDirector")
    recs = by_created(store.save_offers.values())
    subscription_id = request.args.get("subscription_id")
    if subscription_id is not None:
        recs = [o for o in recs if o["subscription_id"] == subscription_id]
    status = request.args.get("status")
    if status is not None:
        recs = [o for o in recs if o["status"] == status]
    return paginate(recs, ser_save_offer)


@bp.get("/api/save-offers/<oid>")
def get_offer(oid):
    uid, role = require_roles("Subscriber", "ServiceRep", "CirculationDirector")
    offer = _offer_and_owner_check(oid, uid, role)
    return ok_obj(ser_save_offer(offer))


@bp.post("/api/save-offers/<oid>/accept")
def accept_offer(oid):
    uid, role = require_roles("Subscriber", "ServiceRep", "CirculationDirector")
    offer = _offer_and_owner_check(oid, uid, role)
    t = domain.today()
    if offer["status"] != "OFFERED" or not (t < offer["expires_at"]):
        raise ApiError("ERR_OFFER_NOT_OPEN", 409,
                       "Save offer is not OFFERED or has expired")
    sub = store.subscriptions[offer["subscription_id"]]
    if sub["billing_status"] not in ("CANCEL_PENDING", "ACTIVE", "GRACE"):
        raise ApiError("ERR_SUBSCRIPTION_NOT_ACTIVE", 409,
                       "Accept requires billing_status CANCEL_PENDING, ACTIVE or GRACE")
    offer["status"] = "ACCEPTED"
    bump(offer)
    sub["save_discount_pct"] = offer["discount_pct"]
    sub["save_discount_until"] = t + days(offer["duration_weeks"] * 7)
    sub["cancel_reason"] = None
    if sub["billing_status"] == "CANCEL_PENDING":
        sub["billing_status"] = "ACTIVE"  # save-offer rescue
    bump(sub)
    return ok_obj(ser_save_offer(offer))


@bp.post("/api/save-offers/<oid>/decline")
def decline_offer(oid):
    uid, role = require_roles("Subscriber", "ServiceRep", "CirculationDirector")
    offer = _offer_and_owner_check(oid, uid, role)
    if offer["status"] != "OFFERED":
        raise ApiError("ERR_OFFER_NOT_OPEN", 409, "Save offer is not OFFERED")
    offer["status"] = "DECLINED"
    bump(offer)
    sub = store.subscriptions[offer["subscription_id"]]
    if sub["billing_status"] == "CANCEL_PENDING":
        domain.cancel_terminal(sub)  # churn confirmed
    return ok_obj(ser_save_offer(offer))
