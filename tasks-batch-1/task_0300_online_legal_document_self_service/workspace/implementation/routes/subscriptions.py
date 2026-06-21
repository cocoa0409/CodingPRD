"""Subscription routes + lifecycle transitions."""

from flask import Blueprint, request

import errors
import validators
from common import base_entity, get_or_404, list_collection, serialize, touch
from db import store
from middleware import get_json_body, parse_pagination, roles
from response import array_response, object_response
from services.cascades import cascade_subscription_cancelled

bp = Blueprint("subscriptions", __name__)

# Allowed subscription transitions: from-state -> set of valid to-states.
SUB_TRANSITIONS = {
    "PENDING_PAYMENT": {"ACTIVE"},
    "ACTIVE": {"PAST_DUE", "CANCELLED"},
    "PAST_DUE": {"ACTIVE", "CANCELLED"},
    "CANCELLED": set(),
}
SUB_STATES = {"PENDING_PAYMENT", "ACTIVE", "PAST_DUE", "CANCELLED"}


def recompute_credits(subscription, plan):
    remaining = plan["included_project_credits"] - subscription["credits_used"]
    if remaining < 0:
        remaining = 0
    subscription["credits_remaining"] = remaining


@bp.route("/legal/subscriptions", methods=["POST"])
@roles("Customer", "PlatformAdmin")
def create_subscription():
    body = get_json_body()
    # Existence (404) before well-formedness consistency, per validation order:
    # both customer_id and plan_id are FK fields resolved left-to-right.
    customer_id = validators.require_string(body, "customer_id")
    plan_id = validators.require_string(body, "plan_id")

    customer = store.customers.get(customer_id)
    if customer is None:
        raise errors.not_found("customer_id does not exist")
    plan = store.subscription_plans.get(plan_id)
    if plan is None:
        raise errors.not_found("plan_id does not exist")

    ent = base_entity()
    ent.update({
        "customer_id": customer_id,
        "plan_id": plan_id,
        "tier": plan["tier"],
        "status": "PENDING_PAYMENT",
        "credits_used": 0,
        "credits_remaining": plan["included_project_credits"],
    })
    store.subscriptions[ent["id"]] = ent
    return object_response(serialize(ent), 201)


@bp.route("/legal/subscriptions/<sid>", methods=["GET"])
@roles("Customer", "PlatformAdmin")
def get_subscription(sid):
    ent = get_or_404(store.subscriptions, sid)
    return object_response(serialize(ent), 200)


@bp.route("/legal/subscriptions", methods=["GET"])
@roles("Customer", "PlatformAdmin")
def list_subscriptions():
    limit, offset = parse_pagination()
    customer_id = request.args.get("customer_id")
    plan_id = request.args.get("plan_id")

    def predicate(e):
        if customer_id is not None and e["customer_id"] != customer_id:
            return False
        if plan_id is not None and e["plan_id"] != plan_id:
            return False
        return True

    page, total = list_collection(store.subscriptions, predicate, limit, offset)
    return array_response(page, limit, offset, total, 200)


@bp.route("/legal/subscriptions/<sid>/transition", methods=["POST"])
@roles("PlatformAdmin")
def transition_subscription(sid):
    sub = get_or_404(store.subscriptions, sid)
    body = get_json_body()
    to_status = validators.require_enum(body, "to_status", SUB_STATES)

    current = sub["status"]
    if to_status not in SUB_TRANSITIONS.get(current, set()):
        raise errors.invalid_state(
            f"Cannot transition subscription from {current} to {to_status}"
        )

    sub["status"] = to_status
    touch(sub)

    if to_status == "CANCELLED":
        cascade_subscription_cancelled(sub)

    return object_response(serialize(sub), 200)
