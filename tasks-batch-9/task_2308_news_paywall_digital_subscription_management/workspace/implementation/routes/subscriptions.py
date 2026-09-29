"""Opening subscriptions and reading their dimensions (PRD 3.5)."""
from flask import Blueprint, request

import config
import lookup
import middleware
import serializers
import validation as v
from clock import clock, parse_date
from db import by_seq, db, new_entity
from errors import fail
from middleware import auth
from response import listing, mark_created, object_response, touch
from services.cancellation import requests_of
from services.derive import subscription_holds, subscription_invoices
from services.pricing import assemble_invoice, recompute_next_price

bp = Blueprint("subscriptions", __name__)


@bp.post("/subscriptions")
@auth(config.ROLE_OPS)
def create_subscription():
    data = v.body()
    reader_id = v.get_id(data, "reader_id", required=True)
    offer_plan_id = v.get_id(data, "offer_plan_id", required=True)
    expected_version = v.get_int(data, "expected_offer_plan_version", required=True)
    group_account_id = v.get_id(data, "group_account_id")

    reader = lookup.reader(reader_id)
    plan = lookup.offer_plan(offer_plan_id)
    if group_account_id is not None:
        lookup.group_account_body(group_account_id)

    if expected_version != plan["version"]:
        fail("ERR_STALE_OFFER_PLAN_VERSION")
    if plan["status"] != "ACTIVE":
        fail("ERR_PLAN_NOT_ACTIVE")
    if not reader["is_registered"] or reader.get("email") is None:
        fail("ERR_READER_NOT_REGISTERED")

    sub = new_entity()
    sub.update(
        {
            "reader_id": reader_id,
            "offer_plan_id": offer_plan_id,
            "group_account_id": group_account_id,
            "lifecycle_status": "PENDING_ACTIVATION",
            "dunning_status": "CURRENT",
            "print_fulfillment_status": "NOT_APPLICABLE",
            "cycle_index": 1,
            "cycle_start_on": clock.date().isoformat(),
            "paid_through_on": None,
            "access_until": None,
            "next_cycle_price_cents": 0,
            "locked_price_cents": None,
            "grandfathered_until_cycle": None,
            "retention_discount_pct": 0,
            "retention_discount_cycles_remaining": 0,
            "dunning_first_failed_on": None,
            "next_retry_on": None,
            "cancel_effective_on": None,
        }
    )
    db.subscriptions[sub["id"]] = sub
    mark_created(sub)

    assemble_invoice(sub, plan, 1, sub["cycle_start_on"])
    recompute_next_price(sub, plan)
    touch(plan)
    return object_response(serializers.subscription(sub), 201)


@bp.get("/subscriptions")
@auth(
    config.ROLE_OPS,
    config.ROLE_REVENUE,
    config.ROLE_COMPLIANCE,
    config.ROLE_GROUP_ADMIN,
    config.ROLE_READER,
)
def list_subscriptions():
    reader_id = middleware.guard_filter("reader_id") if middleware.is_reader() else request.args.get("reader_id")
    group_account_id = (
        middleware.guard_filter("group_account_id")
        if middleware.is_group_admin()
        else request.args.get("group_account_id")
    )
    if middleware.is_reader():
        reader_id = middleware.user_id()
    if middleware.is_group_admin():
        group_account_id = middleware.user_id()

    rows = by_seq(list(db.subscriptions.values()))
    if reader_id:
        rows = [r for r in rows if r["reader_id"] == reader_id]
    if group_account_id:
        rows = [r for r in rows if r["group_account_id"] == group_account_id]
    for param in ("offer_plan_id", "lifecycle_status", "dunning_status"):
        value = request.args.get(param)
        if value:
            rows = [r for r in rows if r[param] == value]
    return listing(rows, serializers.subscription)


@bp.get("/subscriptions/<subscription_id>")
@auth(config.ROLE_OPS, config.ROLE_REVENUE, config.ROLE_COMPLIANCE, config.ROLE_READER)
def read_subscription(subscription_id):
    middleware.guard_subscription(subscription_id)
    return object_response(serializers.subscription(lookup.subscription(subscription_id)))


@bp.get("/subscriptions/<subscription_id>/invoices")
@auth(config.ROLE_OPS, config.ROLE_COMPLIANCE, config.ROLE_READER)
def list_subscription_invoices(subscription_id):
    middleware.guard_subscription(subscription_id)
    lookup.subscription(subscription_id)
    rows = subscription_invoices(subscription_id)
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return listing(rows, serializers.invoice)


@bp.get("/subscriptions/<subscription_id>/holds")
@auth(config.ROLE_OPS, config.ROLE_READER)
def list_subscription_holds(subscription_id):
    middleware.guard_subscription(subscription_id)
    lookup.subscription(subscription_id)
    rows = sorted(
        subscription_holds(subscription_id),
        key=lambda h: (parse_date(h["start_date"]), h["_seq"]),
    )
    for param in ("hold_type", "status"):
        value = request.args.get(param)
        if value:
            rows = [r for r in rows if r[param] == value]
    return listing(rows, serializers.hold)


@bp.get("/subscriptions/<subscription_id>/cancellation-requests")
@auth(config.ROLE_OPS, config.ROLE_COMPLIANCE, config.ROLE_READER)
def list_subscription_cancellation_requests(subscription_id):
    middleware.guard_subscription(subscription_id)
    lookup.subscription(subscription_id)
    rows = by_seq(requests_of(subscription_id))
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return listing(rows, serializers.cancellation_request)
