"""The regulated cancellation flow and its single save offer (PRD 3.8)."""
from decimal import Decimal

from flask import Blueprint, request

import config
import lookup
import middleware
import serializers
import validation as v
from clock import clock, parse_date
from db import db, new_entity
from errors import fail
from middleware import auth
from response import listing, mark_created, object_response, touch
from services import cancellation, engagement

bp = Blueprint("cancellations", __name__)


@bp.post("/subscriptions/<subscription_id>/cancellation-requests")
@auth(config.ROLE_READER, config.ROLE_OPS)
def create_cancellation_request(subscription_id):
    middleware.guard_subscription(subscription_id)
    data = v.body()
    reason_code = v.get_enum(data, "reason_code", config.REASON_CODES, required=True)

    sub = lookup.subscription(subscription_id)
    if sub["lifecycle_status"] in config.LIFECYCLE_TERMINAL:
        fail("ERR_SUBSCRIPTION_TERMINAL")
    if sub["lifecycle_status"] != "ACTIVE":
        fail("ERR_SUBSCRIPTION_NOT_ACTIVE")

    reader = db.readers.get(sub["reader_id"])
    projection = engagement.cohort_normalized(reader) if reader else Decimal("0.00")

    req = new_entity()
    req.update(
        {
            "subscription_id": sub["id"],
            "status": "INITIATED",
            "reason_code": reason_code,
            "projected_engagement_score": float(projection),
            "eligible_save_offer_tier": cancellation.save_offer_tier(projection),
            "confirmed_on": None,
            "effective_on": None,
            "retained": False,
        }
    )
    db.cancellation_requests[req["id"]] = req
    mark_created(req)
    return object_response(serializers.cancellation_request(req), 201)


@bp.post("/cancellation-requests/<request_id>/save-offers")
@auth(config.ROLE_OPS)
def create_save_offer(request_id):
    data = v.body()
    offer_type = v.get_enum(data, "offer_type", config.OFFER_TYPES, required=True)
    discount_pct = v.get_fraction(data, "discount_pct", default=Decimal("0"))
    duration_cycles = v.get_int(data, "duration_cycles", default=0)
    pause_days = v.get_int(data, "pause_days", default=0)

    if offer_type == "RETENTION_DISCOUNT" and discount_pct <= 0:
        fail(
            "ERR_INVALID_REQUEST",
            "Field 'discount_pct' is required and must be greater than 0 for a RETENTION_DISCOUNT.",
        )
    if offer_type == "PAUSE" and "pause_days" not in data:
        fail("ERR_INVALID_REQUEST", "Field 'pause_days' is required for a PAUSE offer.")

    req = lookup.cancellation_request(request_id)
    if req["status"] not in config.CANCELLATION_OPEN_STATUSES:
        fail("ERR_CANCELLATION_REQUEST_CLOSED")
    if len(cancellation.save_offers_of(req["id"])) >= config.MAX_SAVE_OFFERS_PER_REQUEST:
        fail("ERR_SAVE_OFFER_LIMIT_EXCEEDED")

    if discount_pct > Decimal(config.SAVE_OFFER_DISCOUNT_CAP_PCT):
        fail("ERR_SAVE_OFFER_DISCOUNT_CAP")
    if offer_type in ("RETENTION_DISCOUNT", "DOWNGRADE") and not 1 <= duration_cycles <= 12:
        fail("ERR_SAVE_OFFER_DISCOUNT_CAP")
    if offer_type == "PAUSE" and not 7 <= pause_days <= 90:
        fail("ERR_SAVE_OFFER_DISCOUNT_CAP")

    offer = new_entity()
    offer.update(
        {
            "cancellation_request_id": req["id"],
            "offer_type": offer_type,
            "discount_pct": float(discount_pct),
            "duration_cycles": duration_cycles,
            "pause_days": pause_days,
            "status": "PRESENTED",
            "presented_on": clock.date().isoformat(),
            "decided_on": None,
        }
    )
    db.save_offers[offer["id"]] = offer
    mark_created(offer)

    req["status"] = "SAVE_OFFER_PRESENTED"
    touch(req)
    return object_response(serializers.save_offer(offer), 201)


@bp.post("/save-offers/<offer_id>/decision")
@auth(config.ROLE_READER)
def decide_save_offer(offer_id):
    middleware.guard_save_offer(offer_id)
    data = v.body()
    decision = v.get_enum(data, "decision", config.DECISION_VALUES, required=True)

    offer = lookup.save_offer(offer_id)
    req = db.cancellation_requests.get(offer["cancellation_request_id"])
    sub = db.subscriptions.get(req["subscription_id"]) if req else None
    if sub is None or sub["lifecycle_status"] != "ACTIVE":
        fail("ERR_SUBSCRIPTION_NOT_ACTIVE")
    if offer["status"] != "PRESENTED":
        fail("ERR_SAVE_OFFER_ALREADY_DECIDED")

    plan = db.offer_plans.get(sub["offer_plan_id"])
    if decision == "ACCEPTED":
        cancellation.accept_offer(offer, req, sub, plan)
    else:
        cancellation.decline_offer(offer, req)
    return object_response(serializers.save_offer(offer))


@bp.post("/cancellation-requests/<request_id>/confirm")
@auth(config.ROLE_READER, config.ROLE_COMPLIANCE)
def confirm_cancellation(request_id):
    middleware.guard_cancellation_request(request_id)
    req = lookup.cancellation_request(request_id)
    sub = db.subscriptions.get(req["subscription_id"])
    if sub is None or sub["lifecycle_status"] != "ACTIVE":
        fail("ERR_SUBSCRIPTION_NOT_ACTIVE")
    if req["status"] not in config.CANCELLATION_OPEN_STATUSES:
        fail("ERR_CANCELLATION_REQUEST_CLOSED")

    cancellation.confirm(req, sub, db.offer_plans.get(sub["offer_plan_id"]))
    return object_response(serializers.cancellation_request(req))


@bp.get("/cancellation-requests/<request_id>")
@auth(config.ROLE_OPS, config.ROLE_COMPLIANCE, config.ROLE_READER)
def read_cancellation_request(request_id):
    middleware.guard_cancellation_request(request_id)
    return object_response(
        serializers.cancellation_request(lookup.cancellation_request(request_id))
    )


@bp.get("/cancellation-requests/<request_id>/save-offers")
@auth(config.ROLE_OPS, config.ROLE_COMPLIANCE, config.ROLE_READER)
def list_save_offers(request_id):
    middleware.guard_cancellation_request(request_id)
    lookup.cancellation_request(request_id)
    rows = sorted(
        cancellation.save_offers_of(request_id),
        key=lambda o: (parse_date(o["presented_on"]), o["_seq"]),
    )
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return listing(rows, serializers.save_offer)


@bp.get("/save-offers/<offer_id>")
@auth(config.ROLE_OPS, config.ROLE_COMPLIANCE, config.ROLE_READER)
def read_save_offer(offer_id):
    middleware.guard_save_offer(offer_id)
    return object_response(serializers.save_offer(lookup.save_offer(offer_id)))
