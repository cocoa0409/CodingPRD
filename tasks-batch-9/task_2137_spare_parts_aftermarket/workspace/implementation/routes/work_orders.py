"""Service work orders, part lines, the air-freight decision, consume and cancel."""
from decimal import Decimal

from flask import Blueprint

import auth
import calc
import domain
import envelope
import serializers
import store
from errors import ApiError
from routes.registry import fk

bp = Blueprint("work_orders", __name__)

WORK_TYPES = {"SCHEDULED_MAINTENANCE", "BREAKDOWN", "CAMPAIGN"}
DOWNTIME_PRIORITIES = {"MACHINE_DOWN", "DEGRADED", "PLANNED"}
LINE_STATUSES = {"REQUESTED", "RESERVED", "BACKORDERED", "CONSUMED", "CANCELLED"}
WO_STATUSES = {"OPEN", "PARTS_PENDING", "CLOSED"}


# --------------------------------------------------------- work orders -----
@bp.post("/aftermarket/work-orders")
def open_work_order():
    user_id, role = auth.require("DealerUser")
    data = auth.body()
    unit = fk(data, "installed_unit_id", domain.get_installed_unit)
    if unit is not None:
        auth.dealer_scope(role, user_id, unit["dealer_id"])

    installed_unit_id = auth.req_id(data, "installed_unit_id")
    if unit is None:
        unit = domain.get_installed_unit(installed_unit_id)
        auth.dealer_scope(role, user_id, unit["dealer_id"])
    work_type = auth.req_enum(data, "work_type", WORK_TYPES)
    downtime_priority = auth.req_enum(data, "downtime_priority", DOWNTIME_PRIORITIES)

    rec = store.new_record("ServiceWorkOrder", {
        "installed_unit_id": unit["id"],
        "dealer_id": unit["dealer_id"],
        "work_type": work_type,
        "downtime_priority": downtime_priority,
        "status": "OPEN",
        "opened_at": store.now(),
        "closed_at": None,
    })
    store.work_orders[rec["id"]] = rec
    return envelope.created(serializers.work_order(rec))


@bp.get("/aftermarket/work-orders/<wo_id>")
def read_work_order(wo_id):
    auth.require("DealerUser", "AftermarketPlanner", "InventoryController", "PlatformAdmin")
    return envelope.ok(serializers.work_order(domain.get_work_order(wo_id)))


@bp.get("/aftermarket/work-orders")
def list_work_orders():
    auth.require("DealerUser", "AftermarketPlanner", "InventoryController", "PlatformAdmin")
    limit, offset = auth.pagination()
    installed_unit_id = auth.query_str("installed_unit_id")
    dealer_id = auth.query_str("dealer_id")
    status = auth.query_enum("status", WO_STATUSES)

    rows = list(store.work_orders.values())
    if installed_unit_id is not None:
        rows = [r for r in rows if r["installed_unit_id"] == installed_unit_id]
    if dealer_id is not None:
        rows = [r for r in rows if r["dealer_id"] == dealer_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = store.sort_created(rows)
    page, total = auth.paginate(rows, limit, offset)
    return envelope.listing([serializers.work_order(r) for r in page], limit, offset, total)


@bp.post("/aftermarket/work-orders/<wo_id>/close")
def close_work_order(wo_id):
    user_id, role = auth.require("DealerUser")
    wo = domain.get_work_order(wo_id)
    auth.dealer_scope(role, user_id, wo["dealer_id"])

    if wo["status"] != "OPEN":
        raise ApiError("ERR_WORK_ORDER_STATE_INVALID")
    if domain.lines_for_work_order(wo["id"], domain.OPEN_LINE_STATES):
        raise ApiError("ERR_OPEN_LINES_BLOCK_CLOSE")

    wo["status"] = "CLOSED"
    wo["closed_at"] = store.now()
    store.touch(wo)
    return envelope.ok(serializers.work_order(wo))


# ----------------------------------------------------------- part lines ----
@bp.post("/aftermarket/work-orders/<wo_id>/part-lines")
def add_part_line(wo_id):
    user_id, role = auth.require("DealerUser")
    wo = domain.get_work_order(wo_id)
    auth.dealer_scope(role, user_id, wo["dealer_id"])

    data = auth.body()
    part = fk(data, "part_id", domain.get_part)
    part_id = auth.req_id(data, "part_id")
    if part is None:
        part = domain.get_part(part_id)
    qty_requested = auth.req_int(data, "qty_requested", minimum=1)

    if wo["status"] != "OPEN":
        raise ApiError("ERR_WORK_ORDER_STATE_INVALID")

    unit = store.installed_units.get(wo["installed_unit_id"])
    dealer = store.dealers.get(wo["dealer_id"])

    # priority 10 — applicability gate
    row = domain.covering_row(part["id"], unit["model_id"], unit["build_revision"]) if unit else None
    if row is None:
        raise ApiError("ERR_PART_NOT_APPLICABLE")

    # priority 11 — the freight decision, then the dangerous-goods gate
    decision = calc.air_freight_decision(
        available_units=domain.available_units(part),
        qty=qty_requested,
        lead_time_days=part["lead_time_days"],
        downtime_priority=wo["downtime_priority"],
        weight_kg=part["weight_kg"],
        hazmat=part["hazmat"],
        lifecycle_state=part["lifecycle_state"],
        dealer_tier=dealer["tier"] if dealer else None,
    )
    if decision["fulfillment_mode"] == "AIR_FREIGHT" and part["hazmat"]:
        raise ApiError("ERR_HAZMAT_AIR_PROHIBITED")

    # priority 12 — a superseded part must be ordered through its successor
    if part["lifecycle_state"] == "SUPERSEDED":
        raise ApiError("ERR_PART_SUPERSEDED")

    # priority 14 — an ACTIVE rule must price the part's band
    rule = domain.active_price_rule(part["criticality_class"])
    if rule is None:
        raise ApiError("ERR_PRICE_RULE_NOT_FOUND")

    # priority 20 — an obsolete part with nothing available
    if part["lifecycle_state"] == "OBSOLETE" and domain.available_units(part) == 0:
        raise ApiError("ERR_PART_OBSOLETE_NO_SUPPLY")

    # priority 27 — margin floor
    figures = calc.price_uplift(part["unit_cost_cents"], part["lifecycle_state"],
                                rule, qty_requested)
    if figures["margin_pct"] < calc.dec(rule["min_margin_pct"]):
        raise ApiError("ERR_MARGIN_FLOOR_BREACH")

    # priority 29 — credit hold
    if dealer is not None and dealer["credit_hold"]:
        raise ApiError("ERR_DEALER_CREDIT_HOLD")

    mode = decision["fulfillment_mode"]
    line = store.new_record("WorkOrderPartLine", {
        "work_order_id": wo["id"],
        "part_id": part["id"],
        "qty_requested": qty_requested,
        "qty_consumed": 0,
        "line_status": "REQUESTED",
        "fulfillment_mode": mode,
        "decision_net_benefit_cents": decision["decision_net_benefit_cents"],
        "freight_cost_cents": decision["freight_cost_cents"],
        "charged_amount_cents": 0,
        "consumed_at": None,
    })
    line.update(figures)
    store.part_lines[line["id"]] = line

    if mode == "STOCK":
        line["line_status"] = "RESERVED"
        part["allocated_units"] += qty_requested
        store.touch(part)
    else:
        line["line_status"] = "BACKORDERED"
        if wo["status"] == "OPEN":
            wo["status"] = "PARTS_PENDING"
            store.touch(wo)
        if mode == "AIR_FREIGHT":
            order = store.new_record("ReplenishmentOrder", {
                "part_id": part["id"],
                "order_type": "EMERGENCY_AIR",
                "qty": qty_requested,
                "unit_cost_cents": part["unit_cost_cents"],
                "freight_cost_cents": decision["freight_cost_cents"],
                "total_landed_cost_cents": (part["unit_cost_cents"] * qty_requested
                                            + decision["freight_cost_cents"]),
                "approval_status": "PENDING",
                "logistics_status": "NOT_STARTED",
                "auto_generated": True,
                "rejection_reason": None,
            })
            store.replenishment_orders[order["id"]] = order

    return envelope.created(serializers.part_line(line))


@bp.get("/aftermarket/work-order-part-lines/<line_id>")
def read_part_line(line_id):
    auth.require("DealerUser", "AftermarketPlanner", "InventoryController",
                 "PricingAnalyst", "PlatformAdmin")
    return envelope.ok(serializers.part_line(domain.get_part_line(line_id)))


@bp.get("/aftermarket/work-order-part-lines")
def list_part_lines():
    auth.require("DealerUser", "AftermarketPlanner", "InventoryController",
                 "PricingAnalyst", "PlatformAdmin")
    limit, offset = auth.pagination()
    work_order_id = auth.query_str("work_order_id")
    part_id = auth.query_str("part_id")
    line_status = auth.query_enum("line_status", LINE_STATUSES)

    rows = list(store.part_lines.values())
    if work_order_id is not None:
        rows = [r for r in rows if r["work_order_id"] == work_order_id]
    if part_id is not None:
        rows = [r for r in rows if r["part_id"] == part_id]
    if line_status is not None:
        rows = [r for r in rows if r["line_status"] == line_status]
    rows = store.sort_created(rows)
    page, total = auth.paginate(rows, limit, offset)
    return envelope.listing([serializers.part_line(r) for r in page], limit, offset, total)


@bp.post("/aftermarket/work-order-part-lines/<line_id>/consume")
def consume_part_line(line_id):
    user_id, role = auth.require("DealerUser")
    line = domain.get_part_line(line_id)
    wo = store.work_orders.get(line["work_order_id"])
    auth.dealer_scope(role, user_id, wo["dealer_id"] if wo else None)

    data = auth.body()
    qty_consumed = auth.req_int(data, "qty_consumed", minimum=1,
                                maximum=line["qty_requested"])

    if line["line_status"] != "RESERVED":
        raise ApiError("ERR_LINE_STATE_INVALID")
    if wo is None or wo["status"] != "OPEN":
        raise ApiError("ERR_WORK_ORDER_STATE_INVALID")

    dealer = store.dealers.get(wo["dealer_id"])
    if dealer is not None and dealer["credit_hold"]:
        raise ApiError("ERR_DEALER_CREDIT_HOLD")

    part = store.parts.get(line["part_id"])

    line["qty_consumed"] = qty_consumed
    line["consumed_at"] = store.now()
    line["line_status"] = "CONSUMED"

    part["allocated_units"] -= line["qty_requested"]
    part["on_hand_units"] -= qty_consumed
    domain.append_ledger(part, "ISSUE", -qty_consumed, "WORK_ORDER_PART_LINE", line["id"])

    charged = calc.money(Decimal(part["unit_cost_cents"]) * Decimal(qty_consumed)
                         * (Decimal(1) + calc.dec(line["effective_uplift_pct"])))
    line["charged_amount_cents"] = charged
    store.touch(line)

    if dealer is not None:
        dealer["outstanding_balance_cents"] += charged
        domain.recompute_credit_hold(dealer)
        store.touch(dealer)

    domain.auto_stock_replenishment(part)
    store.touch(part)

    return envelope.ok(serializers.part_line(line))


@bp.post("/aftermarket/work-order-part-lines/<line_id>/cancel")
def cancel_part_line(line_id):
    user_id, role = auth.require("DealerUser")
    line = domain.get_part_line(line_id)
    wo = store.work_orders.get(line["work_order_id"])
    auth.dealer_scope(role, user_id, wo["dealer_id"] if wo else None)

    if line["line_status"] not in domain.OPEN_LINE_STATES:
        raise ApiError("ERR_LINE_STATE_INVALID")

    previous = line["line_status"]
    line["line_status"] = "CANCELLED"
    store.touch(line)

    if previous == "RESERVED":
        part = store.parts.get(line["part_id"])
        if part is not None:
            part["allocated_units"] -= line["qty_requested"]
            store.touch(part)
    elif previous == "BACKORDERED" and wo is not None:
        domain.sync_work_order_backorders(wo)

    return envelope.ok(serializers.part_line(line))
