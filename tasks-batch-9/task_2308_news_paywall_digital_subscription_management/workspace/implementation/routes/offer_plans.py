"""Offer plans and the regulated price-increase pipeline (PRD 3.1 / 3.2)."""
from flask import Blueprint, g, request

import config
import lookup
import serializers
import validation as v
from clock import clock, parse_date
from db import by_seq, db, new_entity
from errors import fail
from middleware import auth
from response import listing, mark_created, object_response, touch
from services.derive import plan_subscriptions, tenure_cycles
from services.events import create_event
from services.pricing import recompute_next_price

bp = Blueprint("offer_plans", __name__)

PIPELINE_STATUSES = ("PENDING_ACTIVATION", "ACTIVE", "PAUSED")
NOTICED_STATUSES = ("PENDING_ACTIVATION", "ACTIVE", "PAUSED", "CANCEL_SCHEDULED")


# ------------------------------------------------------------------ ladder check
def validate_ladder(plan):
    """Priority 36: the step-up ladder must be strictly monotone in both axes."""
    intro_cycles = plan["intro_cycles"]
    standard_from_cycle = plan["standard_from_cycle"]
    schedule = plan["step_up_schedule"]

    if standard_from_cycle <= intro_cycles:
        fail("ERR_STEP_UP_SCHEDULE_INVALID")
    previous = None
    for step in schedule:
        if not intro_cycles < step["from_cycle"] < standard_from_cycle:
            fail("ERR_STEP_UP_SCHEDULE_INVALID")
        if previous is not None:
            if step["from_cycle"] <= previous["from_cycle"]:
                fail("ERR_STEP_UP_SCHEDULE_INVALID")
            if step["price_cents"] <= previous["price_cents"]:
                fail("ERR_STEP_UP_SCHEDULE_INVALID")
        previous = step
    if schedule:
        if schedule[0]["price_cents"] < plan["intro_price_cents"]:
            fail("ERR_STEP_UP_SCHEDULE_INVALID")
        if schedule[-1]["price_cents"] > plan["standard_price_cents"]:
            fail("ERR_STEP_UP_SCHEDULE_INVALID")


# ------------------------------------------------------------------ create
@bp.post("/offer-plans")
@auth(config.ROLE_REVENUE)
def create_offer_plan():
    data = v.body()
    name = v.get_string(data, "name", required=True, min_len=1, max_len=120)
    bundle_type = v.get_enum(data, "bundle_type", config.BUNDLE_TYPES, required=True)
    intro_price_cents = v.get_int(data, "intro_price_cents", required=True)
    intro_cycles = v.get_int(data, "intro_cycles", required=True)
    standard_price_cents = v.get_int(data, "standard_price_cents", required=True)
    standard_from_cycle = v.get_int(data, "standard_from_cycle", required=True)
    cycle_days = v.get_int(data, "cycle_days", default=30, minimum=1, maximum=92)
    step_up_schedule = v.get_step_up_schedule(data)
    print_component_cents = v.get_int(data, "print_component_cents", default=0)
    print_delivery_days = v.get_string_array(
        data, "print_delivery_days", allowed=config.WEEKDAY_CODES, default=[]
    )
    print_deliveries_per_cycle = v.get_int(data, "print_deliveries_per_cycle", default=0)
    per_seat_price_cents = v.get_int(data, "per_seat_price_cents", default=0)
    grandfather_policy = v.get_enum(
        data, "grandfather_policy", config.GRANDFATHER_POLICIES, default="NONE"
    )

    if any(p["name"] == name for p in db.offer_plans.values()):
        fail("ERR_INVALID_REQUEST", "Field 'name' must be unique across offer plans.")
    if print_component_cents > standard_price_cents:
        fail(
            "ERR_INVALID_REQUEST",
            "Field 'print_component_cents' must not exceed 'standard_price_cents'.",
        )
    if bundle_type == "PRINT_DIGITAL":
        if print_deliveries_per_cycle < 1:
            fail(
                "ERR_INVALID_REQUEST",
                "Field 'print_deliveries_per_cycle' must be at least 1 on a PRINT_DIGITAL plan.",
            )
    else:
        if print_component_cents != 0:
            fail(
                "ERR_INVALID_REQUEST",
                "Field 'print_component_cents' must be 0 unless the bundle is PRINT_DIGITAL.",
            )
        if print_delivery_days:
            fail(
                "ERR_INVALID_REQUEST",
                "Field 'print_delivery_days' must be empty unless the bundle is PRINT_DIGITAL.",
            )
        if print_deliveries_per_cycle != 0:
            fail(
                "ERR_INVALID_REQUEST",
                "Field 'print_deliveries_per_cycle' must be 0 unless the bundle is PRINT_DIGITAL.",
            )
    if bundle_type == "INSTITUTIONAL_SEAT" and per_seat_price_cents <= 0:
        fail(
            "ERR_INVALID_REQUEST",
            "Field 'per_seat_price_cents' must be greater than 0 on an INSTITUTIONAL_SEAT plan.",
        )

    plan = new_entity()
    plan.update(
        {
            "name": name,
            "bundle_type": bundle_type,
            "status": "DRAFT",
            "intro_price_cents": intro_price_cents,
            "intro_cycles": intro_cycles,
            "step_up_schedule": step_up_schedule,
            "standard_from_cycle": standard_from_cycle,
            "standard_price_cents": standard_price_cents,
            "cycle_days": cycle_days,
            "print_component_cents": print_component_cents,
            "print_delivery_days": print_delivery_days,
            "print_deliveries_per_cycle": print_deliveries_per_cycle,
            "per_seat_price_cents": per_seat_price_cents,
            "price_change_state": "NONE",
            "pending_price_cents": None,
            "pending_effective_on": None,
            "notice_sent_on": None,
            "notice_sent_by_user_id": None,
            "grandfather_policy": grandfather_policy,
        }
    )
    validate_ladder(plan)
    db.offer_plans[plan["id"]] = plan
    mark_created(plan)
    return object_response(serializers.offer_plan(plan), 201)


# ------------------------------------------------------------------ activate
@bp.post("/offer-plans/<plan_id>/activate")
@auth(config.ROLE_REVENUE)
def activate_offer_plan(plan_id):
    plan = lookup.offer_plan(plan_id)
    if plan["status"] == "ACTIVE":
        fail("ERR_PLAN_ALREADY_ACTIVE")
    validate_ladder(plan)
    plan["status"] = "ACTIVE"
    touch(plan)
    return object_response(serializers.offer_plan(plan))


# ------------------------------------------------------------------ schedule
@bp.post("/offer-plans/<plan_id>/price-change")
@auth(config.ROLE_REVENUE)
def schedule_price_change(plan_id):
    data = v.body()
    pending_price_cents = v.get_int(data, "pending_price_cents", required=True)
    pending_effective_on = v.get_date(data, "pending_effective_on", required=True)
    grandfather_policy = v.get_enum(
        data, "grandfather_policy", config.GRANDFATHER_POLICIES, default="NONE"
    )
    expected_version = v.get_int(data, "expected_offer_plan_version", required=True)

    plan = lookup.offer_plan(plan_id)
    if expected_version != plan["version"]:
        fail("ERR_STALE_OFFER_PLAN_VERSION")
    if plan["status"] != "ACTIVE":
        fail("ERR_PLAN_NOT_ACTIVE")
    if plan["price_change_state"] != "NONE":
        fail("ERR_PRICE_CHANGE_STATE_INVALID")
    if pending_price_cents <= plan["standard_price_cents"]:
        fail(
            "ERR_INVALID_REQUEST",
            "Field 'pending_price_cents' must be greater than the current standard price.",
        )
    if pending_effective_on <= clock.date():
        fail(
            "ERR_INVALID_REQUEST",
            "Field 'pending_effective_on' must be at least one day after the clock date.",
        )

    plan["pending_price_cents"] = pending_price_cents
    plan["pending_effective_on"] = pending_effective_on.isoformat()
    plan["grandfather_policy"] = grandfather_policy
    plan["price_change_state"] = "SCHEDULED"
    touch(plan)

    for sub in plan_subscriptions(plan["id"], PIPELINE_STATUSES):
        before = sub["next_cycle_price_cents"]
        recompute_next_price(sub, plan)
        if sub["next_cycle_price_cents"] != before:
            touch(sub)
    return object_response(serializers.offer_plan(plan))


# ------------------------------------------------------------------ notices
@bp.post("/offer-plans/<plan_id>/price-change/notices")
@auth(config.ROLE_COMPLIANCE)
def dispatch_price_notices(plan_id):
    plan = lookup.offer_plan(plan_id)
    if plan["price_change_state"] != "SCHEDULED":
        fail("ERR_PRICE_CHANGE_STATE_INVALID")
    effective_on = parse_date(plan["pending_effective_on"])
    if (effective_on - clock.date()).days < config.PRICE_NOTICE_WINDOW_DAYS:
        fail("ERR_PRICE_NOTICE_WINDOW_TOO_SHORT")

    plan["price_change_state"] = "NOTICE_SENT"
    plan["notice_sent_on"] = clock.date().isoformat()
    plan["notice_sent_by_user_id"] = g.user_id
    touch(plan)

    notified = []
    for sub in plan_subscriptions(plan["id"], NOTICED_STATUSES):
        reader = db.readers.get(sub["reader_id"])
        if reader is None or reader["id"] in notified:
            continue
        notified.append(reader["id"])
        create_event(reader, "PRICE_INCREASE_NOTICE")

    for sub in plan_subscriptions(plan["id"], PIPELINE_STATUSES):
        before = sub["next_cycle_price_cents"]
        recompute_next_price(sub, plan)
        if sub["next_cycle_price_cents"] != before:
            touch(sub)
    return object_response(serializers.offer_plan(plan))


# ------------------------------------------------------------------ apply
@bp.post("/offer-plans/<plan_id>/price-change/apply")
@auth(config.ROLE_COMPLIANCE)
def apply_price_change(plan_id):
    plan = lookup.offer_plan(plan_id)
    if plan["notice_sent_by_user_id"] is not None and plan["notice_sent_by_user_id"] == g.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES")
    if plan["price_change_state"] not in ("SCHEDULED", "NOTICE_SENT"):
        fail("ERR_PRICE_CHANGE_STATE_INVALID")
    if plan["notice_sent_on"] is None:
        fail("ERR_PRICE_NOTICE_NOT_SENT")
    if clock.date() < parse_date(plan["pending_effective_on"]):
        fail("ERR_PRICE_CHANGE_NOT_EFFECTIVE_YET")

    # hop 1
    pre_change_price = plan["standard_price_cents"]
    plan["_pre_change_standard_price_cents"] = pre_change_price
    plan["standard_price_cents"] = plan["pending_price_cents"]
    plan["price_change_state"] = "APPLIED"
    touch(plan)

    # hops 2 and 3
    policy = plan["grandfather_policy"]
    notice_sent_on = parse_date(plan["notice_sent_on"])
    for sub in plan_subscriptions(plan["id"], NOTICED_STATUSES):
        grandfathered = False
        if policy == "ALL_EXISTING":
            grandfathered = sub["_created_dt"].date() <= notice_sent_on
        elif policy == "TENURE_12_CYCLES":
            grandfathered = tenure_cycles(sub) >= config.GRANDFATHER_TENURE_CYCLES
        if grandfathered:
            sub["locked_price_cents"] = pre_change_price
            sub["grandfathered_until_cycle"] = sub["cycle_index"] + config.GRANDFATHER_LOCK_CYCLES
        before = sub["next_cycle_price_cents"]
        recompute_next_price(sub, plan)
        if grandfathered or sub["next_cycle_price_cents"] != before:
            touch(sub)
    return object_response(serializers.offer_plan(plan))


# ------------------------------------------------------------------ reads
@bp.get("/offer-plans")
@auth(config.ROLE_REVENUE, config.ROLE_COMPLIANCE, config.ROLE_OPS)
def list_offer_plans():
    rows = by_seq(list(db.offer_plans.values()))
    status = request.args.get("status")
    bundle_type = request.args.get("bundle_type")
    if status:
        rows = [r for r in rows if r["status"] == status]
    if bundle_type:
        rows = [r for r in rows if r["bundle_type"] == bundle_type]
    return listing(rows, serializers.offer_plan)


@bp.get("/offer-plans/<plan_id>")
@auth(config.ROLE_REVENUE, config.ROLE_COMPLIANCE, config.ROLE_OPS)
def read_offer_plan(plan_id):
    return object_response(serializers.offer_plan(lookup.offer_plan(plan_id)))
