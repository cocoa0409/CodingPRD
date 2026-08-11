"""Subscription endpoints."""

from datetime import timedelta

from flask import Blueprint, request

import errors
import validation as v
from db import store, new_entity, touch, clock, parse_datetime, format_instant
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services.calculations import subscription_loyalty_fee, subscription_cancel_credit

bp = Blueprint("subscriptions", __name__)


@bp.post("/api/subscriptions")
def create_subscription():
    require_roles(["BillingSpecialist"])
    body = v.require_body(request.get_json(silent=True))
    v.reject_unknown_fields(body, {"client_id", "device_model_id", "period_start", "auto_renew"})
    client_id = v.req_string(body, "client_id")
    device_model_id = v.req_string(body, "device_model_id")
    period_start = v.req_datetime(body, "period_start")
    auto_renew = v.opt_bool(body, "auto_renew", default=False)

    if client_id not in store.clients:
        raise errors.not_found("Client not found")
    model = store.device_models.get(device_model_id)
    if model is None:
        raise errors.not_found("DeviceModel not found")
    if model["subscription_monthly_cents"] <= 0:
        raise errors.validation("Model must carry subscription_monthly_cents > 0")

    period_end = period_start + timedelta(days=30)

    # closed-interval overlap per client+model: new.period_start <= existing.period_end conflicts
    for sub in store.subscriptions.values():
        if sub["client_id"] != client_id or sub["device_model_id"] != device_model_id:
            continue
        if sub["status"] not in ("ACTIVE", "PAST_DUE"):
            continue
        existing_end = parse_datetime(sub["period_end"])
        if period_start <= existing_end:
            raise errors.subscription_overlap()

    fee = subscription_loyalty_fee(0, model["subscription_monthly_cents"])

    sub = new_entity()
    sub.update({
        "client_id": client_id,
        "device_model_id": device_model_id,
        "period_start": format_instant(period_start),
        "period_end": format_instant(period_end),
        "auto_renew": auto_renew,
        "total_paid_cents": fee,
        "last_fee_cents": fee,
        "credit_cents": None,
        "past_due_since": None,
        "status": "ACTIVE",
    })
    store.subscriptions[sub["id"]] = sub
    return success_object(sub, status=201)


@bp.get("/api/subscriptions/<sid>")
def get_subscription(sid):
    require_roles(ALL_ROLES)
    sub = store.subscriptions.get(sid)
    if sub is None:
        raise errors.not_found("Subscription not found")
    return success_object(sub)


@bp.get("/api/subscriptions")
def list_subscriptions():
    require_roles(ALL_ROLES)
    limit, offset = v.parse_pagination(request.args)
    items = v.apply_filters(list(store.subscriptions.values()), [
        (request.args.get("client_id"), "client_id"),
        (request.args.get("device_model_id"), "device_model_id"),
        (request.args.get("status"), "status"),
    ])
    items = v.sort_by_created(items)
    total = len(items)
    return success_list(items[offset:offset + limit], limit, offset, total)


@bp.post("/api/subscriptions/<sid>/renew")
def renew_subscription(sid):
    require_roles(["BillingSpecialist"])
    sub = store.subscriptions.get(sid)
    if sub is None:
        raise errors.not_found("Subscription not found")
    if sub["status"] not in ("ACTIVE", "PAST_DUE"):
        raise errors.invalid_state("Subscription cannot be renewed from its current state")

    model = store.device_models[sub["device_model_id"]]
    fee = subscription_loyalty_fee(sub["total_paid_cents"], model["subscription_monthly_cents"])
    sub["last_fee_cents"] = fee
    sub["total_paid_cents"] += fee

    now = clock.now()
    if sub["status"] == "ACTIVE":
        new_end = parse_datetime(sub["period_end"]) + timedelta(days=30)
        sub["period_end"] = format_instant(new_end)
    else:  # PAST_DUE
        sub["period_end"] = format_instant(now + timedelta(days=30))
        sub["past_due_since"] = None
        sub["status"] = "ACTIVE"
    touch(sub)
    return success_object(sub)


@bp.post("/api/subscriptions/<sid>/cancel")
def cancel_subscription(sid):
    require_roles(["BillingSpecialist"])
    sub = store.subscriptions.get(sid)
    if sub is None:
        raise errors.not_found("Subscription not found")
    if sub["status"] not in ("ACTIVE", "PAST_DUE", "SUSPENDED"):
        raise errors.invalid_state("Subscription cannot be cancelled from its current state")

    model = store.device_models[sub["device_model_id"]]
    if sub["status"] == "ACTIVE":
        sub["credit_cents"] = subscription_cancel_credit(
            model["subscription_monthly_cents"], parse_datetime(sub["period_end"]), clock.now(),
        )
    else:
        sub["credit_cents"] = 0
    sub["status"] = "CANCELLED"
    touch(sub)
    return success_object(sub)
