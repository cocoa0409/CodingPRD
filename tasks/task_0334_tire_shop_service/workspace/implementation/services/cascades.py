"""Cross-entity helpers and cascade side effects (PRD §3.2, §3.4, §3.7).

Centralises the multi-entity operations: work-order approval, cancellation
compensation, and the queries those depend on (order lines, fitment, stock
coverage). All callers hold db.mutation_lock.
"""
from __future__ import annotations

from typing import Dict, List

import db
from services.calculations import road_hazard_premium, work_order_pricing

SERVICE_TYPES = {"MOUNT_BALANCE", "ROTATION", "TPMS_SERVICE", "ALIGNMENT"}


def order_lines(work_order_id: str) -> List[Dict]:
    """All WorkOrderLine rows of an order, in creation order."""
    lines = [l for l in db.work_order_lines.values()
             if l["work_order_id"] == work_order_id]
    lines.sort(key=db.created_then_seq)
    return lines


def non_void_lines(work_order_id: str) -> List[Dict]:
    return [l for l in order_lines(work_order_id) if l["line_status"] != "VOID"]


def order_requires_alignment(work_order_id: str) -> bool:
    """True iff the order has any non-VOID ALIGNMENT line."""
    return any(
        l["line_type"] == "ALIGNMENT"
        for l in order_lines(work_order_id)
        if l["line_status"] != "VOID"
    )


def fitment_approved(vehicle_id: str, tire_model_id: str) -> bool:
    """True iff some FitmentRule pairs the vehicle+tire with an approved grade."""
    approved = {"OE_EXACT", "APPROVED_PLUS"}
    for r in db.fitment_rules.values():
        if (r["vehicle_id"] == vehicle_id
                and r["tire_model_id"] == tire_model_id
                and r["fitment_grade"] in approved):
            return True
    return False


def has_open_or_received_special_order(work_order_line_id: str) -> bool:
    """True iff a SpecialOrder covering the line is ORDERED or RECEIVED."""
    for so in db.special_orders.values():
        if (so["work_order_line_id"] == work_order_line_id
                and so["status"] in ("ORDERED", "RECEIVED")):
            return True
    return False


# ---- approval side effects (PRD §3.2) ---------------------------------------


def apply_approval(order: Dict) -> None:
    """Run pricing + all non-pricing side effects of DRAFT->APPROVED.

    Assumes all guards already passed. Caller flips fulfillment_status and
    bumps version.
    """
    customer = db.customers[order["customer_id"]]
    lines = non_void_lines(order["id"])

    pricing = work_order_pricing(
        lines,
        db.tire_models,
        order.get("store_credit_applied_cents", 0),
        customer["store_credit_cents"],
    )

    order["parts_subtotal_cents"] = pricing["parts_subtotal_cents"]
    order["service_subtotal_cents"] = pricing["service_subtotal_cents"]
    order["disposal_fee_cents"] = pricing["disposal_fee_cents"]
    order["road_hazard_premium_cents"] = pricing["road_hazard_premium_cents"]
    order["tax_cents"] = pricing["tax_cents"]
    order["total_due_cents"] = pricing["total_due_cents"]

    applied = pricing["applied_credit"]
    order["store_credit_applied_cents"] = applied
    customer["store_credit_cents"] -= applied
    if applied > 0:
        db.bump(customer)

    # Lines PENDING->COMMITTED, snapshot extended_cents (already set by pricing).
    for line in lines:
        line["line_status"] = "COMMITTED"
        db.bump(line)

    # Debit stock for committed TIRE lines backed by sufficient stock.
    for line in lines:
        if line["line_type"] != "TIRE":
            continue
        model = db.tire_models[line["tire_model_id"]]
        if model["stock_qty"] >= line["quantity"]:
            model["stock_qty"] -= line["quantity"]
            line["_stock_debited"] = True
            db.bump(model)
        else:
            line["_stock_debited"] = False

    # Create + activate RoadHazardWarranty for opted committed TIRE lines.
    for line in lines:
        if line["line_type"] == "TIRE" and line.get("road_hazard_opted"):
            premium = road_hazard_premium(line["extended_cents"], line["quantity"])
            warranty = {
                "work_order_line_id": line["id"],
                "tire_model_id": line["tire_model_id"],
                "covered_quantity": line["quantity"],
                "premium_cents": premium,
                "status": "ACTIVE",
            }
            db.stamp_common(warranty)
            db.road_hazard_warranties[warranty["id"]] = warranty


# ---- cancellation compensation (PRD §3.7) -----------------------------------


def apply_cancellation(order: Dict) -> None:
    """Full compensation for DRAFT/APPROVED -> CANCELLED.

    Caller flips fulfillment_status, handles payment refund, and bumps version.
    """
    lines = order_lines(order["id"])
    for line in lines:
        if line["line_status"] == "VOID":
            continue
        was_committed = line["line_status"] == "COMMITTED"
        line["line_status"] = "VOID"
        db.bump(line)
        # Restock committed TIRE lines that had debited stock.
        if (was_committed and line["line_type"] == "TIRE"
                and line.get("_stock_debited")):
            model = db.tire_models.get(line["tire_model_id"])
            if model is not None:
                model["stock_qty"] += line["quantity"]
                line["_stock_debited"] = False
                db.bump(model)

    # Void any ACTIVE RoadHazardWarranty on the order's lines.
    line_ids = {l["id"] for l in lines}
    for w in db.road_hazard_warranties.values():
        if w["work_order_line_id"] in line_ids and w["status"] == "ACTIVE":
            w["status"] = "VOID"
            db.bump(w)

    # Refund applied store credit.
    applied = order.get("store_credit_applied_cents", 0)
    if applied > 0:
        customer = db.customers.get(order["customer_id"])
        if customer is not None:
            customer["store_credit_cents"] += applied
            db.bump(customer)
        order["store_credit_applied_cents"] = 0

    # Cancel SCHEDULED / RESCHEDULE_PENDING appointments for the order.
    for a in db.appointments.values():
        if (a["work_order_id"] == order["id"]
                and a["status"] in ("SCHEDULED", "RESCHEDULE_PENDING")):
            a["status"] = "CANCELLED"
            db.bump(a)
