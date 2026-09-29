"""Change-order forecasting, decisions and receipt into the safe (PRD section 3.9)."""
from decimal import Decimal

from flask import Blueprint

import calc
import db
import domain
import response
import serializers
import validation
from auth import endpoint, user_id
from errors import err
from routes.common import list_collection

bp = Blueprint("change_orders", __name__)

SEASONAL_PROFILES = ("BASELINE", "BACK_TO_SCHOOL", "HOLIDAY")
ORDER_READ_ROLES = ["CashOfficeClerk", "StoreManager", "TreasuryAnalyst"]


@bp.post("/cash-ops/change-orders")
@endpoint(["CashOfficeClerk"])
def create_change_order():
    data = validation.body()
    store_id = validation.req_str(data, "store_id")
    target_week_start = validation.req_date(data, "target_week_start")
    days_covered = validation.req_int(data, "days_covered", minimum=1, maximum=14)
    baseline = validation.req_int(data, "baseline_daily_cash_demand_cents", minimum=0)
    growth_dec = validation.opt_number(
        data, "growth_pct", default=Decimal("0"), minimum="-0.50", maximum="2.00"
    )
    raw_growth = data.get("growth_pct")
    if raw_growth is None:
        raw_growth = 0
    override = validation.opt_enum(data, "seasonal_profile_override", SEASONAL_PROFILES)
    store = domain.get_store(store_id)
    applied = override if override is not None else store["seasonal_profile"]
    forecast = calc.forecast_demand(baseline, days_covered, applied, growth_dec)
    planned_lines, total_planned = calc.denomination_plan(forecast)
    record = db.base_record()
    record.update(
        {
            "store_id": store["id"],
            "target_week_start": target_week_start,
            "days_covered": days_covered,
            "baseline_daily_cash_demand_cents": baseline,
            "growth_pct": raw_growth,
            "seasonal_profile_override": override,
            "applied_seasonal_profile": applied,
            "forecast_demand_cents": forecast,
            "planned_lines": planned_lines,
            "total_planned_cents": total_planned,
            "status": "DRAFT",
            "approved_by_user_id": None,
            "received_amount_cents": None,
        }
    )
    db.change_orders[record["id"]] = record
    return response.object_response(serializers.change_order(record), 201)


@bp.post("/cash-ops/change-orders/<order_id>/approve")
@endpoint(["StoreManager"])
def approve_change_order(order_id):
    data = validation.body()
    validation.opt_str(data, "approval_note")
    order = domain.get_change_order(order_id)
    if order["status"] != "DRAFT":
        raise err("ERR_CHANGE_ORDER_INVALID_STATE", "only a DRAFT order may be approved")
    order["status"] = "APPROVED"
    order["approved_by_user_id"] = user_id()
    db.touch(order)
    return response.object_response(serializers.change_order(order))


@bp.post("/cash-ops/change-orders/<order_id>/reject")
@endpoint(["StoreManager"])
def reject_change_order(order_id):
    data = validation.body()
    validation.req_str(data, "rejection_reason")
    order = domain.get_change_order(order_id)
    if order["status"] != "DRAFT":
        raise err("ERR_CHANGE_ORDER_INVALID_STATE", "only a DRAFT order may be rejected")
    order["status"] = "REJECTED"
    order["approved_by_user_id"] = user_id()
    db.touch(order)
    return response.object_response(serializers.change_order(order))


@bp.post("/cash-ops/change-orders/<order_id>/receive")
@endpoint(["CashOfficeClerk"])
def receive_change_order(order_id):
    data = validation.body()
    received = validation.req_int(data, "received_amount_cents", minimum=0)
    order = domain.get_change_order(order_id)
    if order["status"] != "APPROVED":
        raise err("ERR_CHANGE_ORDER_INVALID_STATE", "only an APPROVED order may be received")
    safe = domain.earliest_safe(order["store_id"])
    if safe is None:
        raise err("ERR_SAFE_NOT_FOUND", "the store has no commissioned safe to receive into")
    if safe["posture"] == "FROZEN":
        raise err("ERR_SAFE_FROZEN", "the safe is frozen by an investigation")
    domain.write_txn(
        safe_id=safe["id"],
        txn_type="CHANGE_ORDER_RECEIPT",
        declared_amount_cents=received,
        actor_user_id=user_id(),
        memo="change order receipt for order %s" % order["id"],
        change_order_id=order["id"],
    )
    order["received_amount_cents"] = received
    order["status"] = "RECEIVED"
    db.touch(order)
    db.touch(safe)
    return response.object_response(serializers.change_order(order))


@bp.get("/cash-ops/change-orders/<order_id>")
@endpoint(ORDER_READ_ROLES)
def read_change_order(order_id):
    order = domain.get_change_order(order_id)
    return response.object_response(serializers.change_order(order))


@bp.get("/cash-ops/change-orders")
@endpoint(ORDER_READ_ROLES)
def list_change_orders():
    return list_collection(
        db.change_orders,
        [
            ("store_id", "store_id"),
            ("status", "status"),
            ("target_week_start", "target_week_start"),
        ],
        serializers.change_order,
    )
