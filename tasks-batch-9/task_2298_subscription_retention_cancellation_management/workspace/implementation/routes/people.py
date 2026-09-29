"""Subscribers and payment methods (PRD §3.2, §3.7)."""
from flask import Blueprint

import constants as K
import serializers as S
import validation as V
from db import base_record, store, touch
from errors import fail
from middleware import auth, own
from response import created, ok
from routes import send_list
from services import calc

bp = Blueprint("people", __name__)


@bp.post("/subscribers")
@auth("PlatformAdmin")
def create_subscriber():
    data = V.body()
    email = V.req_str(data, "email")
    if any(s["email"] == email for s in store.subscribers.values()):
        V.bad("email", "must be unique across subscribers")
    channel = V.req_enum(data, "acquisition_channel", K.ACQUISITION_CHANNELS)
    dnc = V.opt_bool(data, "do_not_contact", False)

    rec = base_record()
    rec.update({
        "email": email,
        "acquisition_channel": channel,
        "do_not_contact": dnc,
        "first_subscribed_at": None,
        "lapsed_at": None,
        "won_back_at": None,
        "churn_type": "NONE",
        "winback_suppressed_until": None,
        "cohort_month": None,
        "_suppression_grant_id": None,
    })
    store.subscribers[rec["id"]] = rec
    return created(S.subscriber(rec))


@bp.patch("/subscribers/<subscriber_id>")
@auth("Subscriber", "PlatformAdmin")
def update_subscriber(subscriber_id):
    subscriber = V.must_exist("subscribers", subscriber_id)
    data = V.body()
    dnc = V.req_bool(data, "do_not_contact")
    own(subscriber["id"])
    subscriber["do_not_contact"] = dnc
    touch(subscriber)
    return ok(S.subscriber(subscriber))


@bp.get("/subscribers/<subscriber_id>")
@auth()
def read_subscriber(subscriber_id):
    return ok(S.subscriber(V.must_exist("subscribers", subscriber_id)))


@bp.post("/payment-methods")
@auth("Subscriber", "PlatformAdmin")
def create_payment_method():
    data = V.body()
    subscriber = V.fk(data, "subscriber_id", "subscribers")
    V.req_str(data, "subscriber_id")
    last4 = V.req_str(data, "card_last4")
    if not V.LAST4_RE.match(last4):
        V.bad("card_last4", "must be exactly four digits")
    exp_month = V.req_int(data, "exp_month", minimum=1, maximum=12)
    exp_year = V.req_int(data, "exp_year", minimum=2020)
    network = V.req_enum(data, "network", K.CARD_NETWORKS)
    own(subscriber["id"])

    rec = base_record()
    rec.update({
        "subscriber_id": subscriber["id"],
        "card_last4": last4,
        "exp_month": exp_month,
        "exp_year": exp_year,
        "network": network,
        "status": "ACTIVE",
        "updater_status": "NONE",
        "updater_requested_at": None,
    })

    for method in store.payment_methods.values():
        if method["subscriber_id"] == subscriber["id"] and method["status"] == "ACTIVE":
            method["status"] = "REPLACED"
            touch(method)
    store.payment_methods[rec["id"]] = rec

    for sub in calc.subscriptions_of(subscriber["id"]):
        if sub["lifecycle_state"] != "CANCELLED":
            sub["payment_method_id"] = rec["id"]
            touch(sub)
    return created(S.payment_method(rec))


@bp.post("/payment-methods/<method_id>/updater-result")
@auth("BillingOperator")
def updater_result(method_id):
    method = V.must_exist("payment_methods", method_id)
    data = V.body()
    outcome = V.req_enum(data, "outcome", K.UPDATER_OUTCOMES)
    new_last4 = V.opt_str(data, "new_card_last4")
    if new_last4 is not None and not V.LAST4_RE.match(new_last4):
        V.bad("new_card_last4", "must be exactly four digits")
    new_month = V.opt_int(data, "new_exp_month", None, minimum=1, maximum=12)
    new_year = V.opt_int(data, "new_exp_year", None, minimum=2020)

    if method["updater_status"] != "PENDING":
        fail("ERR_UPDATER_NOT_PENDING",
             "The payment method has no pending card-updater request.")

    if outcome == "UPDATED":
        method["updater_status"] = "UPDATED"
        if new_last4 is not None:
            method["card_last4"] = new_last4
        if new_month is not None:
            method["exp_month"] = new_month
        if new_year is not None:
            method["exp_year"] = new_year
        method["status"] = "ACTIVE"
    else:
        method["updater_status"] = "UNAVAILABLE"
        method["status"] = "EXPIRED"
    touch(method)
    return ok(S.payment_method(method))


@bp.get("/payment-methods/<method_id>")
@auth()
def read_payment_method(method_id):
    return ok(S.payment_method(V.must_exist("payment_methods", method_id)))


@bp.get("/payment-methods")
@auth()
def list_payment_methods():
    return send_list(store.payment_methods.values(), S.payment_method,
                     {"subscriber_id": "subscriber_id", "status": "status"})
