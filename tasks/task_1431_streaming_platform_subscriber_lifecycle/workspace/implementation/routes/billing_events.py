"""Billing event endpoints."""
from flask import Blueprint, request

import db
from errors import ApiError
from middleware import require_roles
from response import success_object, paginate
from util import new_uuid, now_iso, parse_iso
from services.billing import EVENT_TYPES

bp = Blueprint("billing_events", __name__)


@bp.route("/v1/billing-events", methods=["GET"])
def list_events():
    require_roles("PlatformAdmin", "SupportAgent", "PartnerBillingOps")
    items = list(db.billing_events.values())
    for f in ["account_id", "subscription_id", "event_type"]:
        v = request.args.get(f)
        if v is not None:
            items = [e for e in items if str(e.get(f)) == v]
    from_utc = request.args.get("from_utc")
    to_utc = request.args.get("to_utc")
    if from_utc:
        fd = parse_iso(from_utc)
        items = [e for e in items if parse_iso(e["occurred_at_utc"]) >= fd]
    if to_utc:
        td = parse_iso(to_utc)
        items = [e for e in items if parse_iso(e["occurred_at_utc"]) <= td]
    return paginate(items, request.args)


@bp.route("/v1/billing-events/<bid>", methods=["GET"])
def get_event(bid):
    require_roles("PlatformAdmin", "SupportAgent", "PartnerBillingOps")
    ev = db.billing_events.get(bid)
    if not ev:
        raise ApiError("ERR_NOT_FOUND", 404, "billing event not found")
    return success_object(ev)


@bp.route("/v1/billing-events", methods=["POST"])
def post_manual_event():
    require_roles("PlatformAdmin", "SupportAgent", "PartnerBillingOps")
    body = request.get_json(silent=True) or {}
    for f in ["account_id", "subscription_id", "event_type", "amount_cents"]:
        if f not in body:
            raise ApiError("ERR_INVALID_REQUEST", 400, f"missing field: {f}")
    if body["event_type"] not in EVENT_TYPES:
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid event_type")
    if not isinstance(body["amount_cents"], int):
        raise ApiError("ERR_INVALID_REQUEST", 400, "amount_cents must be integer")
    acct = db.accounts.get(body["account_id"])
    sub = db.subscriptions.get(body["subscription_id"])
    if not acct or not sub:
        raise ApiError("ERR_REFERENTIAL_INTEGRITY", 422, "account or subscription not found")
    if sub["account_id"] != acct["account_id"]:
        raise ApiError("ERR_REFERENTIAL_INTEGRITY", 422, "subscription does not belong to account")
    from services.billing import post_event
    ev = post_event(acct["account_id"], sub["subscription_id"], body["event_type"],
                    body["amount_cents"],
                    external_reference=body.get("external_reference"),
                    notes=body.get("notes"))
    # PRD §3.4: a renewal charge failure on an ACTIVE/CURRENT subscription is
    # simultaneously a fall into PAST_DUE and a fall into DUNNING, with
    # dunning_attempt_count set to 1. Subsequent failures while in DUNNING
    # increment the count. The manual event POST is the client-reachable
    # driver for this renewal-failure transition.
    if body["event_type"] == "CHARGE_FAILED":
        from util import now_iso as _now_iso, touch as _touch
        if sub["subscription_status"] == "ACTIVE" and sub["billing_state"] == "CURRENT":
            sub["subscription_status"] = "PAST_DUE"
            sub["billing_state"] = "DUNNING"
            sub["dunning_attempt_count"] = 1
            sub["_first_failure_at"] = _now_iso()
            _touch(sub)
        elif sub["subscription_status"] == "PAST_DUE" and sub["billing_state"] == "DUNNING":
            sub["dunning_attempt_count"] = sub.get("dunning_attempt_count", 0) + 1
            _touch(sub)
    return success_object(ev, 201)
