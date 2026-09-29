"""Service holds: pauses, vacation holds and delivery interruptions (PRD 3.7)."""
from flask import Blueprint

import config
import lookup
import middleware
import serializers
import validation as v
from clock import clock
from db import db
from errors import fail
from middleware import auth
from response import object_response, touch
from services import holds as holds_service
from services.derive import inclusive_days, pause_count_365, vacation_days_used_365
from services.pricing import recompute_next_price

bp = Blueprint("holds", __name__)

PRINT_HOLD_TYPES = ("VACATION_DELIVERY", "DELIVERY_INTERRUPTION")
READER_HOLD_TYPES = ("VACATION_DELIVERY", "PAUSE_BILLING")


@bp.post("/subscriptions/<subscription_id>/holds")
@auth(config.ROLE_READER, config.ROLE_OPS)
def create_hold(subscription_id):
    middleware.guard_subscription(subscription_id)
    data = v.body()
    hold_type = v.get_enum(data, "hold_type", config.HOLD_TYPES, required=True)
    start_date = v.get_date(data, "start_date", required=True)
    end_date = v.get_date(data, "end_date", required=True)

    sub = lookup.subscription(subscription_id)
    if sub["lifecycle_status"] in config.LIFECYCLE_TERMINAL:
        fail("ERR_SUBSCRIPTION_TERMINAL")
    if sub["lifecycle_status"] != "ACTIVE":
        fail("ERR_SUBSCRIPTION_NOT_ACTIVE")

    plan = db.offer_plans.get(sub["offer_plan_id"])
    if hold_type in PRINT_HOLD_TYPES:
        if (
            plan is None
            or plan["bundle_type"] != "PRINT_DIGITAL"
            or plan["print_deliveries_per_cycle"] < 1
        ):
            fail("ERR_PLAN_NOT_PRINT_BUNDLE")

    today = clock.date()
    if hold_type in READER_HOLD_TYPES and start_date <= today:
        fail("ERR_HOLD_START_NOT_FUTURE")
    if hold_type == "DELIVERY_INTERRUPTION" and start_date < today:
        fail("ERR_HOLD_START_IN_PAST")
    if end_date < start_date:
        fail("ERR_HOLD_INTERVAL_INVALID")
    if (end_date - start_date).days + 1 > config.HOLD_MAX_SPAN_DAYS:
        fail("ERR_HOLD_INTERVAL_INVALID")

    start_iso = start_date.isoformat()
    end_iso = end_date.isoformat()
    if holds_service.buffer_conflict(sub, hold_type, start_iso, end_iso):
        fail("ERR_HOLD_BUFFER_VIOLATION")
    if hold_type == "VACATION_DELIVERY":
        requested = inclusive_days(start_iso, end_iso)
        if vacation_days_used_365(sub, extra_days=requested) > config.ANNUAL_VACATION_DAY_CAP:
            fail("ERR_VACATION_DAY_CAP_EXCEEDED")
    if hold_type == "PAUSE_BILLING":
        if pause_count_365(sub) >= config.MAX_PAUSES_PER_YEAR:
            fail("ERR_PAUSE_LIMIT_EXCEEDED")

    delivery_days, credit_cents = holds_service.credit_computation(
        plan, hold_type, start_iso, end_iso
    )
    immediate = hold_type == "DELIVERY_INTERRUPTION" and start_date == today
    hold = holds_service.create_hold(
        sub,
        hold_type,
        start_iso,
        end_iso,
        delivery_days,
        credit_cents,
        "ACTIVE" if immediate else "SCHEDULED",
    )
    if immediate and sub["print_fulfillment_status"] == "SCHEDULED":
        sub["print_fulfillment_status"] = "INTERRUPTED"
    recompute_next_price(sub, plan)
    touch(sub)
    return object_response(serializers.hold(hold), 201)


@bp.post("/holds/<hold_id>/release")
@auth(config.ROLE_OPS)
def release_hold(hold_id):
    hold = lookup.hold(hold_id)
    if hold["status"] not in ("SCHEDULED", "ACTIVE") or hold["credit_applied"]:
        fail("ERR_HOLD_NOT_RELEASABLE")
    sub = db.subscriptions.get(hold["subscription_id"])
    holds_service.release_hold(hold, sub, db.offer_plans.get(sub["offer_plan_id"]))
    return object_response(serializers.hold(hold))


@bp.get("/holds/<hold_id>")
@auth(config.ROLE_OPS, config.ROLE_READER)
def read_hold(hold_id):
    middleware.guard_hold(hold_id)
    return object_response(serializers.hold(lookup.hold(hold_id)))
