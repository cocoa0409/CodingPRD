"""Subscriptions."""
from flask import Blueprint, request

import errors as E
import middleware as mw
from db import store, mint, touch, pub, pub_list
from response import ok_object, ok_list

bp = Blueprint("subscriptions", __name__)


@bp.post("/tc/subscriptions")
def create_subscription():
    uid, role = mw.auth()
    mw.require_roles(role, {"Coordinator"})
    data = mw.body()
    # priority 9 (business constraint) precedes priority 12 (shape):
    # at most one ACTIVE subscription per coordinator.
    for s in store.subscriptions.values():
        if s["coordinator_id"] == uid and s["status"] == "ACTIVE":
            E.raise_err(E.ERR_SUBSCRIPTION_ALREADY_ACTIVE,
                        "Coordinator already has an ACTIVE subscription")
    mw.validate_shape(data, [
        ("monthly_fee_cents", "int", True),
        ("included_files_quota", "int", True, mw.non_negative_int),
        ("overage_fee_cents", "int", True),
    ])
    rec = mint({
        "coordinator_id": uid,
        "monthly_fee_cents": data["monthly_fee_cents"],
        "included_files_quota": data["included_files_quota"],
        "overage_fee_cents": data["overage_fee_cents"],
        "included_files_used": 0,
        "status": "ACTIVE",
    })
    store.subscriptions[rec["id"]] = rec
    return ok_object(pub("subscription", rec), 201)


@bp.get("/tc/subscriptions/<subscriptionId>")
def get_subscription(subscriptionId):
    mw.auth()
    rec = mw.get_or_404("subscription", subscriptionId)
    return ok_object(pub("subscription", rec))


@bp.get("/tc/subscriptions")
def list_subscriptions():
    mw.auth()
    limit, offset = mw.page_params()
    recs = list(store.subscriptions.values())
    recs = mw.filter_eq(recs, "coordinator_id", request.args.get("coordinator_id"))
    recs = mw.filter_eq(recs, "status", request.args.get("status"))
    page, total = mw.apply_page(recs, limit, offset)
    return ok_list(pub_list("subscription", page), limit, offset, total)


@bp.post("/tc/subscriptions/<subscriptionId>/cancel")
def cancel_subscription(subscriptionId):
    uid, role = mw.auth()
    mw.require_roles(role, {"Coordinator"})
    rec = mw.get_or_404("subscription", subscriptionId)
    if rec["coordinator_id"] != uid:
        E.raise_err(E.ERR_RESOURCE_NOT_OWNED, "Subscription belongs to another coordinator")
    if rec["status"] != "ACTIVE":
        E.raise_err(E.ERR_SUBSCRIPTION_INVALID_STATE, "Subscription is not ACTIVE")
    for f in store.files.values():
        if f.get("subscription_id") == rec["id"] and f["status"] in ("ACTIVE", "PENDING_CLOSE"):
            E.raise_err(E.ERR_SUBSCRIPTION_HAS_ACTIVE_FILES,
                        "Subscription has files in ACTIVE or PENDING_CLOSE")
    rec["status"] = "CANCELLED"
    touch(rec)
    return ok_object(pub("subscription", rec))
