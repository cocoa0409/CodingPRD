"""Feed shipment + withdrawal plan routes."""

from flask import Blueprint

import errors
import util
from db import store
from middleware import require_roles
from response import success_object
from services import core
from routes.onboarding import _paginate
from routes.feed_orders import _compensating_return

bp = Blueprint("shipments", __name__)


@bp.get("/vfd/feed-shipments/<sid>")
def get_shipment(sid):
    require_roles("Inspector", "Veterinarian", "FeedMillOperator", "Producer")
    return success_object(core.get_shipment(sid))


@bp.get("/vfd/feed-orders/<oid>/feed-shipments")
def list_shipments_for_order(oid):
    require_roles("Inspector", "Veterinarian", "FeedMillOperator", "Producer")
    core.get_feed_order(oid)
    items = [s for s in store.feed_shipments.values() if s.get("feed_order_id") == oid]
    return _paginate(items)


def _producer_gate(shipment):
    order = core.get_feed_order(shipment["feed_order_id"])
    if shipment["status"] != "IN_TRANSIT":
        raise errors.invalid_state("Shipment must be IN_TRANSIT")
    return order


@bp.post("/vfd/feed-shipments/<sid>/deliver")
def deliver_shipment(sid):
    user_id, _ = require_roles("Producer")
    shipment = core.get_shipment(sid)
    order = _producer_gate(shipment)
    if user_id != order.get("producer_id"):
        raise errors.forbidden("X-User-ID must equal order.producer_id")
    body = util.get_json_body()
    last_feed_consumed_at = util.require_field(body, "last_feed_consumed_at")
    util.parse_iso(last_feed_consumed_at, "last_feed_consumed_at")

    shipment["status"] = "DELIVERED"
    shipment["delivered_at"] = util.logical_now_iso()
    util.touch(shipment)

    order["status"] = "DELIVERED"
    util.touch(order)

    mill = core.get_feed_mill(order["feed_mill_id"])
    mill["pending_order_count"] = max(0, mill.get("pending_order_count", 0) - 1)
    util.touch(mill)

    # Finalize withdrawal plan
    plan = next(
        (p for p in store.withdrawal_plans.values() if p.get("feed_order_id") == order["id"]),
        None,
    )
    if plan is not None and plan["status"] == "PROVISIONAL":
        plan["last_feed_consumed_at"] = last_feed_consumed_at
        final_market_date = core.compute_final_market_date(
            last_feed_consumed_at, plan["withdrawal_window_hours"])
        plan["final_market_date"] = final_market_date
        vfd = core.get_vfd(order["vfd_authorization_id"])
        group = core.get_animal_group(vfd["animal_group_id"])
        emd = util.parse_iso(group["earliest_market_date"], "earliest_market_date")
        fmd = util.parse_iso(final_market_date, "final_market_date")
        if fmd <= emd:
            plan["status"] = "FINALIZED"
        else:
            plan["status"] = "VIOLATED"
            # Auto-open a ResidueCase on the producer
            case = util.new_entity({
                "producer_id": order["producer_id"],
                "feed_order_id": order["id"],
                "detected_at": util.logical_now_iso(),
                "residue_ppb": None,
                "tolerance_ppb": None,
                "investigator_id": None,
                "severity_tier": None,
                "penalty_score_deduction": 0,
                "status": "OPEN",
            })
            store.residue_cases[case["id"]] = case
            core.recompute_all_clinics_audit_ready()
        util.touch(plan)

    return success_object(shipment)


@bp.post("/vfd/feed-shipments/<sid>/return")
def return_shipment(sid):
    user_id, _ = require_roles("Producer")
    shipment = core.get_shipment(sid)
    order = _producer_gate(shipment)
    if user_id != order.get("producer_id"):
        raise errors.forbidden("X-User-ID must equal order.producer_id")
    shipment["status"] = "RETURNED"
    util.touch(shipment)
    order["status"] = "CANCELLED"
    util.touch(order)
    _compensating_return(order)
    return success_object(shipment)


@bp.post("/vfd/feed-shipments/<sid>/reject-receipt")
def reject_receipt_shipment(sid):
    user_id, _ = require_roles("Producer")
    shipment = core.get_shipment(sid)
    order = _producer_gate(shipment)
    if user_id != order.get("producer_id"):
        raise errors.forbidden("X-User-ID must equal order.producer_id")
    shipment["status"] = "REJECTED_AT_RECEIPT"
    util.touch(shipment)
    order["status"] = "CANCELLED"
    util.touch(order)
    _compensating_return(order)
    return success_object(shipment)


# ---------------------------------------------------------------------------
# Withdrawal plans
# ---------------------------------------------------------------------------

@bp.get("/vfd/withdrawal-plans/<pid>")
def get_withdrawal_plan(pid):
    require_roles("Inspector", "Veterinarian", "FeedMillOperator", "Producer")
    return success_object(core.get_withdrawal_plan(pid))


@bp.get("/vfd/feed-orders/<oid>/withdrawal-plans")
def list_withdrawal_plans_for_order(oid):
    require_roles("Inspector", "Veterinarian", "FeedMillOperator", "Producer")
    core.get_feed_order(oid)
    items = [p for p in store.withdrawal_plans.values() if p.get("feed_order_id") == oid]
    return _paginate(items)
