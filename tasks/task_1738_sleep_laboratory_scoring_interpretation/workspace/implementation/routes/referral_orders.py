"""Referral orders, insurance authorizations, provider review, cancellation (PRD 3.1-3.2)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_ORDER_NOT_AUTHORIZABLE_STATE,
    ERR_AUTH_NOT_PENDING,
    ERR_AUTH_WINDOW_INVALID,
    ERR_ORDER_HAS_ACTIVE_STUDY,
    ERR_ORDER_NOT_REVIEWABLE,
    ERR_STALE_VERSION,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, public, query_filters
from services.core import new_record, touch
from util import CLOCK, parse_date
from validate import (
    get_body, req_str, req_enum, opt_enum, req_int, req_date,
    require_path_resource, require_body_ref,
)

bp = Blueprint("referral_orders", __name__)

STUDY_TYPES = {"PSG_DIAGNOSTIC", "HST", "SPLIT_NIGHT", "TITRATION_PAP"}
PRIORITIES = {"ROUTINE", "STAT"}
ORDER_TERMINAL = {"FULFILLED", "CANCELLED", "EXPIRED"}


@bp.post("/referral-orders")
def create_order():
    authorized(["Scheduler"])
    body = get_body()
    # Priority 3: body FK existence in declaration order (patient_id first).
    patient = require_body_ref("patients", body.get("patient_id"))
    # Priority 4: request shape.
    patient_id = req_str(body, "patient_id")
    ordering_provider_name = req_str(body, "ordering_provider_name")
    requested_study_type = req_enum(body, "requested_study_type", STUDY_TYPES)
    icd10_primary = req_str(body, "icd10_primary")
    priority = opt_enum(body, "priority", PRIORITIES, "ROUTINE")
    rec = new_record("referral_orders", {
        "patient_id": patient_id,
        "ordering_provider_name": ordering_provider_name,
        "requested_study_type": requested_study_type,
        "icd10_primary": icd10_primary,
        "priority": priority,
        "no_show_count": 0,
        "status": "RECEIVED",
    })
    return success_object(public(rec), status=201)


@bp.get("/referral-orders")
def list_orders():
    return list_response("referral_orders", query_filters("patient_id", "status"))


@bp.get("/referral-orders/<orderId>")
def get_order(orderId):
    return get_one("referral_orders", orderId)


@bp.post("/referral-orders/<orderId>/authorizations")
def submit_authorization(orderId):
    authorized(["Scheduler"])
    order = require_path_resource("referral_orders", orderId)
    body = get_body()
    # Priority 4: request shape (runs before OCC and state preconditions per PRD 2.9).
    payer_name = req_str(body, "payer_name")
    authorization_number = req_str(body, "authorization_number")
    approved_nights = req_int(body, "approved_nights", minimum=1, maximum=2)
    window_start = req_date(body, "window_start")
    window_end = req_date(body, "window_end")
    if parse_date(window_end) < parse_date(window_start):
        raise_error(ERR_AUTH_WINDOW_INVALID, "window_end is earlier than window_start")
    expected_version = req_int(body, "expected_referral_order_version")
    # Priority 6: optimistic concurrency on the parent order.
    if expected_version != order["version"]:
        raise_error(ERR_STALE_VERSION,
                    "expected_referral_order_version does not match the order's current version")
    # Priority 7: order authorizable state.
    if order["status"] not in ("RECEIVED", "AUTH_DENIED", "AUTHORIZED"):
        raise_error(ERR_ORDER_NOT_AUTHORIZABLE_STATE,
                    f"order status {order['status']} is not authorizable")
    # Side effects: supersede prior live authorizations of this order.
    for auth in db["authorizations"].values():
        if auth["order_id"] == order["id"] and auth["status"] in ("SUBMITTED", "APPROVED"):
            auth["status"] = "SUPERSEDED"
            touch(auth)
    rec = new_record("authorizations", {
        "order_id": order["id"],
        "payer_name": payer_name,
        "authorization_number": authorization_number,
        "approved_nights": approved_nights,
        "window_start": window_start,
        "window_end": window_end,
        "decided_at": None,
        "status": "SUBMITTED",
    })
    order["status"] = "AUTH_IN_PROGRESS"
    touch(order)
    return success_object(public(rec), status=201)


@bp.get("/authorizations")
def list_authorizations():
    return list_response("authorizations", query_filters("order_id", "status"))


@bp.get("/authorizations/<authorizationId>")
def get_authorization(authorizationId):
    return get_one("authorizations", authorizationId)


@bp.post("/authorizations/<authorizationId>/decision")
def authorization_decision(authorizationId):
    authorized(["Scheduler"])
    auth = require_path_resource("authorizations", authorizationId)
    body = get_body()
    outcome = req_enum(body, "outcome", {"APPROVED", "DENIED"})
    if auth["status"] != "SUBMITTED":
        raise_error(ERR_AUTH_NOT_PENDING,
                    f"authorization status {auth['status']} is not SUBMITTED")
    auth["status"] = "APPROVED" if outcome == "APPROVED" else "DENIED"
    auth["decided_at"] = CLOCK.now_iso()
    touch(auth)
    order = db["referral_orders"].get(auth["order_id"])
    if order is not None:
        order["status"] = "AUTHORIZED" if outcome == "APPROVED" else "AUTH_DENIED"
        touch(order)
    return success_object(public(auth))


def _withdraw_live_auths(order):
    for auth in db["authorizations"].values():
        if auth["order_id"] == order["id"] and auth["status"] in ("SUBMITTED", "APPROVED"):
            auth["status"] = "WITHDRAWN"
            touch(auth)


@bp.post("/referral-orders/<orderId>/provider-review")
def provider_review(orderId):
    authorized(["Scheduler"])
    order = require_path_resource("referral_orders", orderId)
    body = get_body()
    action = req_enum(body, "action", {"REINSTATE", "CANCEL"})
    if order["status"] != "NEEDS_PROVIDER_REVIEW":
        raise_error(ERR_ORDER_NOT_REVIEWABLE,
                    f"order status {order['status']} is not NEEDS_PROVIDER_REVIEW")
    if action == "REINSTATE":
        order["status"] = "AUTHORIZED"
        order["no_show_count"] = 0
    else:
        order["status"] = "CANCELLED"
        _withdraw_live_auths(order)
    touch(order)
    return success_object(public(order))


@bp.post("/referral-orders/<orderId>/cancel")
def cancel_order(orderId):
    authorized(["Scheduler"])
    order = require_path_resource("referral_orders", orderId)
    if order["status"] in ORDER_TERMINAL:
        raise_error(ERR_ORDER_NOT_AUTHORIZABLE_STATE,
                    f"order status {order['status']} is terminal and cannot be cancelled")
    prior = order["status"]
    if prior != "AUTH_DENIED":
        # Cancellation from RECEIVED/AUTH_IN_PROGRESS/AUTHORIZED/SCHEDULED is
        # blocked while a linked study is IN_PROGRESS.
        for study in db["sleep_studies"].values():
            if study["order_id"] == order["id"] and study["status"] == "IN_PROGRESS":
                raise_error(ERR_ORDER_HAS_ACTIVE_STUDY,
                            "order has a linked study IN_PROGRESS")
        _withdraw_live_auths(order)
        if prior in ("RECEIVED", "SCHEDULED"):
            for study in db["sleep_studies"].values():
                if study["order_id"] == order["id"] and study["status"] == "SCHEDULED":
                    study["status"] = "CANCELLED"
                    touch(study)
    order["status"] = "CANCELLED"
    touch(order)
    return success_object(public(order))
