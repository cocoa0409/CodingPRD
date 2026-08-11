"""Subscription endpoints (PRD §3.3)."""

from datetime import date

from flask import Blueprint, request

import errors
from clock import clock
from db import db, new_id
from middleware import require_roles
from response import success_list, success_object
from services.domain import debit_wallet, serialize_subscription
from services.pricing import compute_clawback
from util import (
    get_json_body,
    now_iso,
    paginate,
    parse_pagination,
    require_field,
    require_int,
    require_number,
    require_str,
    touch,
)

bp = Blueprint("subscriptions", __name__)

TIERS = {"HEARTH", "HEARTH_PLUS", "ESTATE"}


def _stacking_included(tier):
    return tier in ("HEARTH_PLUS", "ESTATE")


@bp.post("/api/v1/subscriptions")
def create_subscription():
    require_roles("CustomerService", "OperationsManager")
    body = get_json_body()
    customer_id = require_str(body, "customer_id")
    customer = db.customers.get(customer_id)
    if not customer:
        raise errors.referenced_not_found(f"Customer {customer_id} not found")
    tier = require_str(body, "tier")
    if tier not in TIERS:
        raise errors.validation(f"Invalid tier: {tier}")
    season_year = require_int(body, "season_year")
    commitment = require_number(body, "commitment_cord_equivalent")
    prepaid = require_int(body, "prepaid_cents")
    discount_pct = require_number(body, "discount_pct")
    expected_customer_version = require_int(body, "expected_customer_version")

    # Account standing (priority 8) — account must be ACTIVE
    if customer["account_status"] != "ACTIVE":
        raise errors.account_inactive()

    # OCC (priority 6): expected_customer_version vs current
    # NOTE: validation precedence in PRD §2.8 lists state (5) before OCC (6);
    # there is no state precondition on subscription create itself, so OCC is
    # the first version-sensitive check here.
    if expected_customer_version != customer["version"]:
        raise errors.stale_version("expected_customer_version does not match")

    # One ACTIVE subscription per season per customer
    for s in db.subscriptions.values():
        if (
            s["customer_id"] == customer_id
            and s["season_year"] == season_year
            and s["status"] == "ACTIVE"
        ):
            raise errors.subscription_active_exists()

    ts = now_iso()
    sid = new_id()
    sub = {
        "id": sid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "customer_id": customer_id,
        "tier": tier,
        "season_year": season_year,
        "commitment_cord_equivalent": commitment,
        "delivered_cord_equivalent": 0,
        "prepaid_cents": prepaid,
        "discount_pct": discount_pct,
        "stacking_included": _stacking_included(tier),
        "status": "PENDING",
        "activated_at": None,
        "closed_at": None,
    }
    db.subscriptions[sid] = sub
    # Creating a subscription increments Customer.version (PRD §3.3)
    touch(customer)
    return success_object(serialize_subscription(sub), status=201)


def _get_sub_or_404(sid):
    s = db.subscriptions.get(sid)
    if not s:
        raise errors.not_found(f"Subscription {sid} not found")
    return s


@bp.get("/api/v1/subscriptions/<sid>")
def get_subscription(sid):
    auth = require_roles("CustomerService", "OperationsManager", "Customer")
    sub = _get_sub_or_404(sid)
    if auth.is_customer() and auth.user_id != sub["customer_id"]:
        raise errors.unauthorized("Customers may only read their own subscriptions")
    return success_object(serialize_subscription(sub))


@bp.get("/api/v1/subscriptions")
def list_subscriptions():
    require_roles("CustomerService", "OperationsManager")
    limit, offset = parse_pagination()
    items = list(db.subscriptions.values())
    for f in ("customer_id", "status", "tier"):
        v = request.args.get(f)
        if v is not None:
            items = [s for s in items if str(s.get(f)) == v]
    sy = request.args.get("season_year")
    if sy is not None:
        try:
            syv = int(sy)
        except ValueError:
            raise errors.validation("season_year must be an integer")
        items = [s for s in items if s.get("season_year") == syv]
    page, total = paginate(items, limit, offset)
    return success_list([serialize_subscription(s) for s in page], total, limit, offset)


@bp.post("/api/v1/subscriptions/<sid>/activate")
def activate_subscription(sid):
    require_roles("OperationsManager")
    sub = _get_sub_or_404(sid)
    if sub["status"] != "PENDING":
        raise errors.invalid_state("Subscription is not PENDING")
    customer = db.customers.get(sub["customer_id"])
    if not customer or customer["account_status"] != "ACTIVE":
        raise errors.account_inactive("Customer account is not ACTIVE")
    # Temporal rule: logical date must be on or before Nov 1 of season_year
    now = clock.now()
    cutoff = date(sub["season_year"], 11, 1)
    now_d = date(now.year, now.month, now.day)
    if now_d > cutoff:
        raise errors.subscription_out_of_season("Activation after season start is forbidden")
    # One ACTIVE subscription per customer per season
    for s in db.subscriptions.values():
        if (
            s["id"] != sid
            and s["customer_id"] == sub["customer_id"]
            and s["season_year"] == sub["season_year"]
            and s["status"] == "ACTIVE"
        ):
            raise errors.subscription_active_exists()
    # Side effects
    customer["credit_balance_cents"] = customer.get("credit_balance_cents", 0) + sub["prepaid_cents"]
    touch(customer)
    sub["status"] = "ACTIVE"
    sub["activated_at"] = clock.now_iso()
    touch(sub)
    return success_object(serialize_subscription(sub))


@bp.post("/api/v1/subscriptions/<sid>/cancel")
def cancel_subscription(sid):
    require_roles("CustomerService", "OperationsManager")
    sub = _get_sub_or_404(sid)
    body = get_json_body() if request.is_json else {}
    reason = body.get("reason")
    if sub["status"] == "PENDING":
        sub["status"] = "CANCELLED"
        sub["closed_at"] = clock.now_iso()
        touch(sub)
        return success_object(serialize_subscription(sub))
    if sub["status"] == "ACTIVE":
        # No order referencing this subscription in SCHEDULED or OUT_FOR_DELIVERY
        for o in db.orders.values():
            if o.get("subscription_id") == sid and o["fulfillment_status"] in ("SCHEDULED", "OUT_FOR_DELIVERY"):
                raise errors.invalid_state(
                    "Cannot cancel subscription with orders SCHEDULED or OUT_FOR_DELIVERY"
                )
        customer = db.customers.get(sub["customer_id"])
        clawback = compute_clawback(sub)
        if customer:
            debit_wallet(customer, clawback)
            touch(customer)
        sub["status"] = "CANCELLED"
        sub["closed_at"] = clock.now_iso()
        sub["_clawback_at"] = clock.now_iso()  # for 7-day reconciliation
        sub["_clawback_paid"] = clawback
        touch(sub)
        return success_object(serialize_subscription(sub))
    raise errors.invalid_state("Subscription cannot be cancelled from current state")
