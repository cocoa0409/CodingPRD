"""State machines, cascades and the two deferred-action sweeps."""

from datetime import timedelta
from decimal import Decimal

from db import db, make_row, now, sort_rows, today, touch
from services import calc
from services.events import SYSTEM_ACTOR, append_event
from services.ledger import (
    has_open_hold,
    reconcile_customer_id,
    reconcile_prescription_boxes,
    settled_settlements_on_order,
)

VOIDABLE_CLAIM_STATUSES = ("DRAFT", "GENERATED", "SUBMITTED")


# ------------------------------------------------------------------ row builders


def orders_for_prescription(prescription_id):
    return sort_rows([o for o in db.orders.values() if o["prescription_id"] == prescription_id])


def schedules_for_prescription(prescription_id, status=None):
    rows = [s for s in db.auto_reorder_schedules.values() if s["prescription_id"] == prescription_id]
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    return sort_rows(rows)


def claims_for_order(order_id):
    return sort_rows([c for c in db.reimbursement_claims.values() if c["order_id"] == order_id])


def open_hold(customer_id, prescription_id, reason, opened_by_user_id):
    row = make_row(
        {
            "customer_id": customer_id,
            "prescription_id": prescription_id,
            "reason": reason,
            "opened_by_user_id": opened_by_user_id,
            "released_by_user_id": None,
            "escalated_reason": None,
            "status": "OPEN",
        }
    )
    db.reorder_holds[row["id"]] = row
    return row


def create_order(customer, prescription, product, boxes_od, boxes_os, itemized_receipt_reference=None):
    unit_price = product["unit_price_cents"]
    subtotal, shipping, total = calc.price_order(unit_price, boxes_od + boxes_os)
    row = make_row(
        {
            "customer_id": customer["id"],
            "prescription_id": prescription["id"],
            "ordered_product_id": product["id"],
            "fulfilled_product_id": product["id"],
            "boxes_od": boxes_od,
            "boxes_os": boxes_os,
            "unit_price_cents": unit_price,
            "lenses_per_box_at_capture": product["lenses_per_box"],
            "subtotal_cents": subtotal,
            "shipping_cents": shipping,
            "total_cents": total,
            "verification_state": "RX_CLEARED" if prescription["status"] == "VERIFIED_ACTIVE" else "RX_PENDING",
            "fulfillment_state": "PENDING",
            "substitution_type": "NONE",
            "parameter_deviation_index": Decimal("0.00"),
            "fulfilled_od_sphere": None,
            "fulfilled_os_sphere": None,
            "itemized_receipt_reference": itemized_receipt_reference,
            "recall_flagged": False,
            "cancellation_reason": None,
            "shipped_at": None,
            "delivered_at": None,
        }
    )
    db.orders[row["id"]] = row
    reconcile_prescription_boxes(prescription)
    reconcile_customer_id(customer["id"])
    return row


# ------------------------------------------------------------------- transitions


def clear_pending_orders(prescription, event_type, actor):
    """Move every RX_PENDING order on the prescription to RX_CLEARED."""
    for order in orders_for_prescription(prescription["id"]):
        if order["verification_state"] != "RX_PENDING":
            continue
        order["verification_state"] = "RX_CLEARED"
        touch(order)
        append_event(prescription["id"], event_type, "Order", order["id"], actor)


def block_pending_orders(prescription, actor, detail=None):
    for order in orders_for_prescription(prescription["id"]):
        if order["fulfillment_state"] != "PENDING":
            continue
        if order["verification_state"] == "RX_BLOCKED":
            continue
        order["verification_state"] = "RX_BLOCKED"
        touch(order)
        append_event(prescription["id"], "ORDER_BLOCKED", "Order", order["id"], actor, detail)


def pause_active_schedules(prescription, reason, actor, emit_event):
    paused = 0
    for schedule in schedules_for_prescription(prescription["id"], "ACTIVE"):
        schedule["status"] = "PAUSED"
        schedule["pause_reason"] = reason
        touch(schedule)
        paused += 1
        if emit_event:
            append_event(prescription["id"], "SCHEDULE_PAUSED", "AutoReorderSchedule", schedule["id"], actor)
    return paused


def void_claims_on_order(order, voided_reason, actor, emit_event):
    for claim in claims_for_order(order["id"]):
        if claim["status"] not in VOIDABLE_CLAIM_STATUSES:
            continue
        claim["status"] = "VOIDED"
        claim["voided_reason"] = voided_reason
        touch(claim)
        if emit_event:
            append_event(order["prescription_id"], "CLAIM_VOIDED", "ReimbursementClaim", claim["id"], actor)


def supersede_prescription(prescription, actor):
    """Upload-branch supersession cascade (PRD 3.3): invalidate and cancel schedules."""
    if prescription is None:
        return
    prescription["status"] = "INVALIDATED"
    touch(prescription)
    for schedule in schedules_for_prescription(prescription["id"], "ACTIVE"):
        schedule["status"] = "CANCELLED"
        touch(schedule)
    reconcile_customer_id(prescription["customer_id"])


def deny_prescription(prescription, actor):
    """POST /verification-requests/{id}/respond with DENIED (PRD 3.4)."""
    prescription["status"] = "INVALIDATED"
    touch(prescription)
    append_event(prescription["id"], "RX_INVALIDATED", "Prescription", prescription["id"], actor)
    open_hold(prescription["customer_id"], prescription["id"], "PRESCRIBER_DENIED", "system")
    block_pending_orders(prescription, actor)
    pause_active_schedules(prescription, "HOLD_OPEN", actor, emit_event=True)
    reconcile_customer_id(prescription["customer_id"])


def expire_prescription(prescription, actor=SYSTEM_ACTOR):
    """Step two of the verification sweep (PRD 3.4)."""
    prescription["status"] = "EXPIRED"
    touch(prescription)
    append_event(prescription["id"], "RX_EXPIRED", "Prescription", prescription["id"], actor)
    open_hold(prescription["customer_id"], prescription["id"], "PRESCRIPTION_EXPIRED", "system")
    paused = pause_active_schedules(prescription, "HOLD_OPEN", actor, emit_event=False)
    for order in orders_for_prescription(prescription["id"]):
        if order["verification_state"] == "RX_CLEARED" and order["fulfillment_state"] == "PENDING":
            order["verification_state"] = "RX_BLOCKED"
            touch(order)
            append_event(
                prescription["id"], "ORDER_BLOCKED", "Order", order["id"], actor, "prescription expired"
            )
    reconcile_customer_id(prescription["customer_id"])
    return paused


def cancel_order(order, cancellation_reason, actor, voided_reason="CUSTOMER_REQUEST", emit_cancel_event=True):
    """Compensating cancellation (PRD 3.7)."""
    order["fulfillment_state"] = "CANCELLED"
    order["cancellation_reason"] = cancellation_reason
    touch(order)
    prescription = db.prescriptions.get(order["prescription_id"])
    reconcile_prescription_boxes(prescription)
    void_claims_on_order(order, voided_reason, actor, emit_event=False)
    reconcile_customer_id(order["customer_id"])
    if emit_cancel_event:
        append_event(order["prescription_id"], "ORDER_CANCELLED", "Order", order["id"], actor)


def uphold_dispute(prescription, actor):
    """Widest cascade in the system (PRD 3.9)."""
    prescription["status"] = "INVALIDATED"
    touch(prescription)
    append_event(prescription["id"], "RX_INVALIDATED", "Prescription", prescription["id"], actor)
    affected_customers = []
    for order in orders_for_prescription(prescription["id"]):
        touched = False
        if order["fulfillment_state"] == "PENDING":
            order["fulfillment_state"] = "CANCELLED"
            order["cancellation_reason"] = "DISPUTE_UPHELD"
            touch(order)
            touched = True
        elif order["fulfillment_state"] in ("SHIPPED", "DELIVERED"):
            order["recall_flagged"] = True
            touch(order)
            touched = True
        if touched:
            void_claims_on_order(order, "DISPUTE_UPHELD", actor, emit_event=True)
            if order["customer_id"] not in affected_customers:
                affected_customers.append(order["customer_id"])
    reconcile_prescription_boxes(prescription)
    if prescription["customer_id"] not in affected_customers:
        affected_customers.append(prescription["customer_id"])
    for customer_id in affected_customers:
        reconcile_customer_id(customer_id)


# ------------------------------------------------------------------------ sweeps


def verification_sweep():
    actor = SYSTEM_ACTOR
    promoted_prescription_ids = []
    timed_out_request_ids = []
    expired_prescription_ids = []
    holds_opened = 0
    schedules_paused = 0
    current = now()

    # Step one -- passive promotion.
    for request_row in sort_rows([r for r in db.verification_requests.values() if r["status"] == "SENT"]):
        deadline = request_row.get("passive_deadline_at")
        if deadline is None or current < deadline:
            continue
        request_row["status"] = "PASSIVE_TIMEOUT"
        touch(request_row)
        timed_out_request_ids.append(request_row["id"])
        prescription = db.prescriptions.get(request_row["prescription_id"])
        if prescription is not None and prescription["status"] == "PENDING_VERIFICATION":
            prescription["status"] = "VERIFIED_ACTIVE"
            touch(prescription)
            append_event(
                prescription["id"], "PASSIVE_PROMOTED", "Prescription", prescription["id"], actor
            )
            promoted_prescription_ids.append(prescription["id"])
            clear_pending_orders(prescription, "PASSIVE_PROMOTED", actor)

    # Step two -- expiry.
    current_date = today()
    due = [
        p
        for p in db.prescriptions.values()
        if p["status"] == "VERIFIED_ACTIVE" and p["expiry_date"] <= current_date
    ]
    for prescription in sort_rows(due):
        paused = expire_prescription(prescription, actor)
        expired_prescription_ids.append(prescription["id"])
        holds_opened += 1
        schedules_paused += paused

    return {
        "promoted_prescription_ids": promoted_prescription_ids,
        "timed_out_request_ids": timed_out_request_ids,
        "expired_prescription_ids": expired_prescription_ids,
        "holds_opened_count": holds_opened,
        "schedules_paused_count": schedules_paused,
    }


def auto_reorder_run():
    actor = SYSTEM_ACTOR
    current = now()
    current_date = today()
    shipped_order_ids = []
    skipped_schedule_ids = []
    paused_schedule_ids = []

    due = [
        s
        for s in db.auto_reorder_schedules.values()
        if s["status"] == "ACTIVE" and s.get("next_run_at") is not None and s["next_run_at"] <= current
    ]
    due.sort(key=lambda s: (s["next_run_at"], s["created_at"], s["_seq"]))

    for schedule in due:
        prescription = db.prescriptions.get(schedule["prescription_id"])
        customer = db.customers.get(schedule["customer_id"])
        product = db.products.get(schedule["product_id"])
        eligible = (
            prescription is not None
            and customer is not None
            and product is not None
            and prescription["status"] == "VERIFIED_ACTIVE"
            and prescription["expiry_date"] > current_date
            and not has_open_hold(schedule["customer_id"])
            and (prescription["boxes_consumed"] + schedule["boxes_per_run"])
            <= prescription["boxes_authorized_total"]
        )
        if eligible:
            order = create_order(customer, prescription, product, schedule["boxes_per_run"], 0)
            order["fulfillment_state"] = "SHIPPED"
            order["shipped_at"] = current
            touch(order)
            shipped_order_ids.append(order["id"])
            reconcile_customer_id(schedule["customer_id"])
        else:
            schedule["consecutive_skip_count"] = schedule["consecutive_skip_count"] + 1
            skipped_schedule_ids.append(schedule["id"])
            if schedule["consecutive_skip_count"] >= calc.MAX_CONSECUTIVE_SKIPS:
                schedule["status"] = "PAUSED"
                schedule["pause_reason"] = "SKIP_LIMIT"
                paused_schedule_ids.append(schedule["id"])
                append_event(
                    schedule["prescription_id"],
                    "SCHEDULE_PAUSED",
                    "AutoReorderSchedule",
                    schedule["id"],
                    actor,
                )
        schedule["next_run_at"] = schedule["next_run_at"] + timedelta(days=schedule["cadence_days"])
        touch(schedule)
        reconcile_customer_id(schedule["customer_id"])

    return {
        "run_at": current,
        "shipped_order_ids": shipped_order_ids,
        "skipped_schedule_ids": skipped_schedule_ids,
        "paused_schedule_ids": paused_schedule_ids,
    }
