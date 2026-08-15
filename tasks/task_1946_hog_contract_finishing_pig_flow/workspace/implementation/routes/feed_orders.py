"""Feed orders (PRD §3.3): phase-diet gating, lifetime budget, variance delivery."""

from flask import Blueprint, request

from db import store
from errors import (
    conflict,
    ERR_INVALID_STATE_TRANSITION,
    ERR_GROUP_NOT_ACTIVE,
    ERR_FEED_DATE_PAST,
    ERR_PHASE_MISMATCH,
    ERR_FEED_BUDGET_EXCEEDED,
)
from middleware import (
    require_roles, ROLE_INTEGRATOR_ADMIN, ROLE_FIELD_TECH, ROLE_FEED_MILL, ROLE_GROWER,
)
from response import success_object, paginate
from services.core import (
    new_record, touch, ser_feed_order,
    group_committed_feed, group_cumulative_feed,
    group_phase_committed_feed, group_phase_delivered_feed,
    PHASE_PLAN_PCT,
)
from util import (
    get_body, req, as_str, as_int, as_date, as_enum, load_or_404, round_half_up_int,
)
from decimal import Decimal

bp = Blueprint("feed_orders", __name__)

ROLES_READ = [ROLE_INTEGRATOR_ADMIN, ROLE_FIELD_TECH, ROLE_FEED_MILL, ROLE_GROWER]
PHASES = {"STARTER", "GROWER", "FINISHER_1", "FINISHER_2"}


@bp.route("/feed-orders", methods=["POST"])
def create_feed_order():
    require_roles([ROLE_FIELD_TECH])
    body = get_body()
    group_id = as_str(req(body, "group_id"), "group_id")
    group = load_or_404(store.pig_groups, group_id, "PigGroup")
    phase = as_enum(req(body, "phase"), "phase", PHASES)
    diet_code = as_str(req(body, "diet_code"), "diet_code")
    quantity_lbs = as_int(req(body, "quantity_lbs"), "quantity_lbs", 1)
    requested_date = as_date(req(body, "requested_delivery_date"), "requested_delivery_date")
    # state (7): group must be PLACED or MARKETING
    if group["group_status"] not in ("PLACED", "MARKETING"):
        raise conflict(ERR_GROUP_NOT_ACTIVE,
                       "Feed orders require a PLACED or MARKETING group")
    # temporal (9): requested delivery date must not lie before the clock date
    if requested_date < store.now().date():
        raise conflict(ERR_FEED_DATE_PAST,
                       "requested_delivery_date is before the clock date")
    # quota (11): the order's phase must equal the group's current phase
    if phase != group["current_phase"]:
        raise conflict(ERR_PHASE_MISMATCH,
                       f"Order phase {phase} != group phase {group['current_phase']}")
    # fiscal (12): lifetime hard-cap gate on chronological, actual grounds
    contract = store.contracts[group["contract_id"]]
    budget_lbs = group["head_placed"] * contract["feed_budget_lbs_per_head"]
    committed = group_committed_feed(group_id)
    delivered = group_cumulative_feed(group_id)
    hard_remaining = budget_lbs - committed - delivered
    if quantity_lbs > hard_remaining:
        raise conflict(ERR_FEED_BUDGET_EXCEEDED,
                       f"quantity_lbs {quantity_lbs} exceeds hard remaining "
                       f"{hard_remaining} lbs")
    # advisory phase-plan flag (never rejects): allotment minus phase drawdowns
    phase_plan_qty = round_half_up_int(PHASE_PLAN_PCT[phase] * Decimal(budget_lbs))
    phase_remaining = (phase_plan_qty - group_phase_committed_feed(group_id, phase)
                       - group_phase_delivered_feed(group_id, phase))
    over_phase_plan = quantity_lbs > phase_remaining
    rec = new_record()
    rec.update({
        "group_id": group_id, "phase": phase, "diet_code": diet_code,
        "quantity_lbs": quantity_lbs, "requested_delivery_date": requested_date,
        "scheduled_delivery_date": None, "delivered_lbs": None,
        "over_phase_plan": over_phase_plan, "order_status": "REQUESTED",
    })
    store.feed_orders[rec["id"]] = rec
    return success_object(ser_feed_order(rec), 201)


@bp.route("/feed-orders", methods=["GET"])
def list_feed_orders():
    require_roles(ROLES_READ)
    group_id = request.args.get("group_id")
    status = request.args.get("order_status")
    phase = request.args.get("phase")
    items = list(store.feed_orders.values())
    if group_id is not None:
        items = [o for o in items if o["group_id"] == group_id]
    if status is not None:
        items = [o for o in items if o["order_status"] == status]
    if phase is not None:
        items = [o for o in items if o["phase"] == phase]
    return paginate(items, request.args, ser_feed_order)


@bp.route("/feed-orders/<oid>", methods=["GET"])
def get_feed_order(oid):
    require_roles(ROLES_READ)
    return success_object(ser_feed_order(load_or_404(store.feed_orders, oid, "FeedOrder")))


@bp.route("/feed-orders/<oid>/schedule", methods=["POST"])
def schedule_feed_order(oid):
    require_roles([ROLE_FEED_MILL])
    order = load_or_404(store.feed_orders, oid, "FeedOrder")
    body = get_body()
    scheduled_date = as_date(req(body, "scheduled_delivery_date"), "scheduled_delivery_date")
    if order["order_status"] != "REQUESTED":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       f"Cannot schedule an order in {order['order_status']}")
    # temporal (9): scheduled date must not lie before the clock date
    if scheduled_date < store.now().date():
        raise conflict(ERR_FEED_DATE_PAST,
                       "scheduled_delivery_date is before the clock date")
    order["scheduled_delivery_date"] = scheduled_date
    order["order_status"] = "SCHEDULED"
    touch(order)
    return success_object(ser_feed_order(order))


@bp.route("/feed-orders/<oid>/deliver", methods=["POST"])
def deliver_feed_order(oid):
    require_roles([ROLE_FEED_MILL])
    order = load_or_404(store.feed_orders, oid, "FeedOrder")
    body = get_body()
    delivered_lbs = as_int(req(body, "delivered_lbs"), "delivered_lbs", 0)
    if order["order_status"] != "SCHEDULED":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       f"Cannot deliver an order in {order['order_status']}")
    # variance branch pinned at 80% of the ordered quantity (exact integer math)
    order["delivered_lbs"] = delivered_lbs
    order["order_status"] = ("DELIVERED" if delivered_lbs * 5 >= order["quantity_lbs"] * 4
                             else "SHORTED")
    touch(order)
    # either way the delivered pounds accumulate into the group's lifetime total
    group = store.pig_groups.get(order["group_id"])
    if group is not None:
        touch(group)
    return success_object(ser_feed_order(order))


@bp.route("/feed-orders/<oid>/cancel", methods=["POST"])
def cancel_feed_order(oid):
    require_roles([ROLE_FIELD_TECH])
    order = load_or_404(store.feed_orders, oid, "FeedOrder")
    if order["order_status"] not in ("REQUESTED", "SCHEDULED"):
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       f"Cannot cancel an order in {order['order_status']}")
    order["order_status"] = "CANCELLED"
    touch(order)
    return success_object(ser_feed_order(order))
