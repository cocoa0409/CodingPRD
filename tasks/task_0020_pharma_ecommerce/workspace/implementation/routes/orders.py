"""Orders — placement, payment, cancel, open-pharmacist-review, dispense, ship, deliver."""

from __future__ import annotations

from flask import Blueprint, g, request

from db import (
    append_audit_log,
    db,
    emit_external_event,
    filter_by_platform,
    order_by_seq,
    platform_clock,
    serialize,
    serialize_list,
    stamp_create,
    stamp_update,
)
from errors import err
from lookups import get_order, get_platform
from middleware import current_actor, require_roles
from pagination import paginate, parse_limit_offset
from response import success_array, success_object
from services.calculations import order_total_cents
from services.cascades import evaluate_prescription_archive, refund_if_paid
from services.purchase_limits import run_purchase_limits
from validate import occ_check, optional_field, require_field, require_json

bp = Blueprint("orders", __name__)


def _validate_items(body, pid: str):
    items_raw = body.get("items")
    if not isinstance(items_raw, list) or not items_raw:
        raise err("ERR_INVALID_REQUEST", "items must be a non-empty array.")
    items = []
    for line in items_raw:
        if not isinstance(line, dict):
            raise err("ERR_INVALID_REQUEST", "items entries must be objects.")
        drug_id = line.get("drug_id")
        qty = line.get("qty")
        unit = line.get("unit_price_cents")
        if not isinstance(drug_id, str):
            raise err("ERR_INVALID_REQUEST", "items entry requires drug_id (str).")
        if not isinstance(qty, int) or isinstance(qty, bool) or qty < 1:
            raise err("ERR_INVALID_REQUEST", "items entry requires qty (int>=1).")
        if not isinstance(unit, int) or isinstance(unit, bool) or unit < 0:
            raise err("ERR_INVALID_REQUEST", "items entry requires unit_price_cents (int>=0).")
        items.append({"drug_id": drug_id, "qty": qty, "unit_price_cents": unit})
    return items


def _drug_index(items, pid):
    idx = {}
    for line in items:
        d = db.drugs.get(line["drug_id"])
        if not d or d.get("platform_id") != pid:
            raise err("ERR_DRUG_NOT_FOUND", f"Drug '{line['drug_id']}' not found.")
        idx[d["id"]] = d
    return idx


@bp.post("/pharma-platforms/<pid>/orders")
@require_roles("Customer")
def create_order(pid: str):
    platform = get_platform(pid)
    body = require_json(request.get_json(silent=True))
    customer_id = require_field(body, "customer_id", kind=str)
    if customer_id not in db.customers or db.customers[customer_id].get("platform_id") != pid:
        raise err("ERR_CUSTOMER_NOT_FOUND", f"Customer '{customer_id}' not found.")
    if g.user_id != customer_id:
        raise err("ERR_INSUFFICIENT_PERMISSIONS", "Customer X-User-ID must equal customer_id.")
    customer = db.customers[customer_id]

    prescription_id = optional_field(body, "prescription_id", kind=str, default=None)
    items = _validate_items(body, pid)
    drug_index = _drug_index(items, pid)

    has_prescription_drug = any(
        drug_index[i["drug_id"]].get("classification") == "PRESCRIPTION" for i in items
    )

    if has_prescription_drug:
        if not prescription_id:
            raise err("ERR_INVALID_REQUEST", "prescription_id required when ordering prescription drug.")
        rx = db.prescriptions.get(prescription_id)
        if not rx or rx.get("platform_id") != pid:
            raise err("ERR_PRESCRIPTION_NOT_FOUND", f"Prescription '{prescription_id}' not found.")
        # Real-name verification
        if not customer.get("real_name_verified") or not (customer.get("id_document_no") or "").strip():
            raise err(
                "ERR_REAL_NAME_REQUIRED",
                "Real-name verification required for prescription drug orders.",
            )
    else:
        if prescription_id:
            # Validate it exists if supplied (else null)
            rx = db.prescriptions.get(prescription_id)
            if not rx or rx.get("platform_id") != pid:
                raise err("ERR_PRESCRIPTION_NOT_FOUND", f"Prescription '{prescription_id}' not found.")

    # Purchase-limit checks (per_order_qty_cap → special_pop → window)
    run_purchase_limits(platform, customer, items, drug_index)

    total = order_total_cents(items)
    cold = any(drug_index[i["drug_id"]].get("cold_chain_required") for i in items)
    row = {
        "platform_id": pid,
        "customer_id": customer_id,
        "prescription_id": prescription_id if prescription_id else None,
        "items": items,
        "total_amount_cents": total,
        "cold_chain_required": bool(cold),
        "payment_status": "UNPAID",
        "dispensing_status": "PENDING_REVIEW",
        "paid_at": None,
        "pharmacist_review_id": None,
        "cold_chain_shipment_id": None,
    }
    stamp_create(row, platform)
    db.orders[row["id"]] = row
    return success_object(serialize(row)), 201


@bp.get("/pharma-platforms/<pid>/orders")
@require_roles("PlatformAdmin", "RegulatoryGateway")
def list_orders(pid: str):
    get_platform(pid)
    rows = filter_by_platform(db.orders, pid)
    cust = request.args.get("customer_id")
    if cust:
        rows = [r for r in rows if r.get("customer_id") == cust]
    disp = request.args.get("dispensing_status")
    if disp:
        rows = [r for r in rows if r.get("dispensing_status") == disp]
    pay = request.args.get("payment_status")
    if pay:
        rows = [r for r in rows if r.get("payment_status") == pay]
    rows = order_by_seq(rows)
    limit, offset = parse_limit_offset()
    page, total = paginate(rows, limit, offset)
    return success_array(serialize_list(page), limit, offset, total), 200


@bp.get("/pharma-platforms/<pid>/orders/<order_id>")
@require_roles("Customer", "PlatformAdmin", "PharmacistReReviewer", "RegulatoryGateway")
def get_order_route(pid: str, order_id: str):
    _, o = get_order(pid, order_id)
    if g.user_role == "Customer" and g.user_id != o.get("customer_id"):
        raise err("ERR_INSUFFICIENT_PERMISSIONS", "Customer can only view their own orders.")
    return success_object(serialize(o)), 200


@bp.post("/pharma-platforms/<pid>/orders/<order_id>/pay")
@require_roles("Customer")
def pay_order(pid: str, order_id: str):
    platform, o = get_order(pid, order_id)
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        occ_check(body, o)
    if g.user_id != o.get("customer_id"):
        raise err("ERR_INSUFFICIENT_PERMISSIONS", "Only the placing customer may pay this order.")
    if o.get("payment_status") != "UNPAID":
        raise err("ERR_ORDER_NOT_PAYABLE", "Order is not in UNPAID state.")
    if o.get("dispensing_status") not in {"PENDING_REVIEW", "PHARMACIST_REVIEWING", "APPROVED"}:
        raise err("ERR_ORDER_NOT_PAYABLE", "Order dispensing state is not payable.")
    # Prescription drug → prescription must be APPROVED
    has_rx_drug = any(
        (db.drugs.get(i["drug_id"]) or {}).get("classification") == "PRESCRIPTION"
        for i in (o.get("items") or [])
    )
    if has_rx_drug:
        rx = db.prescriptions.get(o.get("prescription_id"))
        if not rx or rx.get("status") != "APPROVED":
            raise err("ERR_PRESCRIPTION_NOT_APPROVED", "Prescription must be APPROVED to pay.")
    o["payment_status"] = "PAID"
    o["paid_at"] = platform_clock(platform)
    stamp_update(o, platform)
    emit_external_event(
        platform=platform,
        channel="PAYMENT",
        event_type="order.paid",
        subject_type="ORDER",
        subject_id=o["id"],
        payload={"order_id": o["id"], "version": o["version"]},
        idempotency_key=f"order.paid:{o['id']}:{o['version']}",
    )
    return success_object(serialize(o)), 200


@bp.post("/pharma-platforms/<pid>/orders/<order_id>/cancel")
@require_roles("Customer")
def cancel_order(pid: str, order_id: str):
    platform, o = get_order(pid, order_id)
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        occ_check(body, o)
    if g.user_id != o.get("customer_id"):
        raise err("ERR_INSUFFICIENT_PERMISSIONS", "Only the placing customer may cancel this order.")
    if o.get("dispensing_status") != "PENDING_REVIEW":
        raise err("ERR_ORDER_NOT_CANCELLABLE", "Order is not PENDING_REVIEW.")
    o["dispensing_status"] = "CANCELLED"
    stamp_update(o, platform)
    refund_if_paid(platform, o)
    evaluate_prescription_archive(platform, o.get("prescription_id"))
    return success_object(serialize(o)), 200


@bp.post("/pharma-platforms/<pid>/orders/<order_id>/open-pharmacist-review")
@require_roles("PharmacistReReviewer")
def open_pharmacist_review(pid: str, order_id: str):
    platform, o = get_order(pid, order_id)
    body = require_json(request.get_json(silent=True))
    occ_check(body, o)
    if o.get("pharmacist_review_id"):
        raise err("ERR_REVIEW_ALREADY_OPEN", "Order already has a pharmacist review.")
    if o.get("dispensing_status") != "PENDING_REVIEW":
        raise err("ERR_ORDER_NOT_REVIEWABLE", "Order dispensing_status must be PENDING_REVIEW.")

    has_rx_drug = any(
        (db.drugs.get(i["drug_id"]) or {}).get("classification") == "PRESCRIPTION"
        for i in (o.get("items") or [])
    )
    rx = None
    if has_rx_drug:
        rx = db.prescriptions.get(o.get("prescription_id"))
        if not rx or rx.get("status") != "APPROVED":
            raise err("ERR_PRESCRIPTION_NOT_APPROVED", "Prescription must be APPROVED.")
        if rx.get("reviewer_pharmacist_id") and rx["reviewer_pharmacist_id"] == g.user_id:
            raise err(
                "ERR_SEGREGATION_OF_DUTIES_VIOLATION",
                "Acting pharmacist cannot be the prescription reviewer.",
            )

    actor = db.pharmacists.get(g.user_id)
    if not actor or actor.get("platform_id") != pid:
        raise err("ERR_PHARMACIST_NOT_ACTIVE", "Acting pharmacist not on platform.")
    if actor.get("qualification_status") != "ACTIVE":
        raise err("ERR_PHARMACIST_NOT_ACTIVE", "Acting pharmacist must be ACTIVE.")

    assigned_id = require_field(body, "assigned_pharmacist_id", kind=str)
    assigned = db.pharmacists.get(assigned_id)
    if not assigned or assigned.get("platform_id") != pid:
        raise err("ERR_PHARMACIST_NOT_FOUND", f"Pharmacist '{assigned_id}' not found.")

    # Purchase-limit re-check
    customer = db.customers.get(o["customer_id"])
    drug_index = {}
    for line in o.get("items") or []:
        d = db.drugs.get(line["drug_id"])
        if d:
            drug_index[d["id"]] = d
    run_purchase_limits(platform, customer, o.get("items") or [], drug_index, exclude_order_id=o["id"])

    # All preconditions satisfied — create review and transition order.
    review = {
        "platform_id": pid,
        "order_id": o["id"],
        "assigned_pharmacist_id": assigned_id,
        "interaction_check_passed": None,
        "dosage_rationality_passed": None,
        "decision_notes": None,
        "revision_count": 0,
        "status": "IN_REVIEW",
    }
    stamp_create(review, platform)
    db.pharmacist_reviews[review["id"]] = review

    o["dispensing_status"] = "PHARMACIST_REVIEWING"
    o["pharmacist_review_id"] = review["id"]
    stamp_update(o, platform)
    return success_object(serialize(review)), 201


@bp.post("/pharma-platforms/<pid>/orders/<order_id>/dispense")
@require_roles("Pharmacist", "PharmacistReReviewer")
def dispense_order(pid: str, order_id: str):
    platform, o = get_order(pid, order_id)
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        occ_check(body, o)
    if o.get("dispensing_status") != "APPROVED":
        raise err("ERR_ORDER_NOT_APPROVED", "Order is not APPROVED.")
    if o.get("payment_status") != "PAID":
        raise err("ERR_ORDER_NOT_PAID", "Order must be PAID before dispense.")
    o["dispensing_status"] = "DISPENSED"
    stamp_update(o, platform)
    actor_id, actor_role = current_actor()
    append_audit_log(
        platform=platform,
        subject_type="ORDER",
        subject_id=o["id"],
        action="ORDER_DISPENSED",
        actor_role=actor_role,
        actor_id=actor_id,
        payload={
            "dispensing_status": o["dispensing_status"],
            "total_amount_cents": o["total_amount_cents"],
            "version": o["version"],
        },
    )
    return success_object(serialize(o)), 200


@bp.post("/pharma-platforms/<pid>/orders/<order_id>/ship")
@require_roles("PlatformAdmin")
def ship_order(pid: str, order_id: str):
    platform, o = get_order(pid, order_id)
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        occ_check(body, o)
    if o.get("dispensing_status") != "DISPENSED":
        raise err("ERR_ORDER_NOT_DISPENSED", "Order is not DISPENSED.")
    if o.get("cold_chain_required"):
        s = db.cold_chain_shipments.get(o.get("cold_chain_shipment_id") or "")
        if not s or s.get("status") != "DISPATCHED":
            raise err(
                "ERR_COLD_CHAIN_SHIPMENT_REQUIRED",
                "Cold-chain order requires a DISPATCHED shipment.",
            )
    o["dispensing_status"] = "SHIPPED"
    stamp_update(o, platform)
    actor_id, actor_role = current_actor()
    append_audit_log(
        platform=platform,
        subject_type="ORDER",
        subject_id=o["id"],
        action="ORDER_SHIPPED",
        actor_role=actor_role,
        actor_id=actor_id,
        payload={"dispensing_status": o["dispensing_status"], "version": o["version"]},
    )
    emit_external_event(
        platform=platform,
        channel="LOGISTICS",
        event_type="order.shipped",
        subject_type="ORDER",
        subject_id=o["id"],
        payload={"order_id": o["id"], "version": o["version"]},
        idempotency_key=f"order.shipped:{o['id']}:{o['version']}",
    )
    if o.get("cold_chain_shipment_id"):
        s = db.cold_chain_shipments.get(o["cold_chain_shipment_id"])
        if s and s.get("status") == "DISPATCHED":
            s["status"] = "IN_TRANSIT"
            stamp_update(s, platform)
    return success_object(serialize(o)), 200


@bp.post("/pharma-platforms/<pid>/orders/<order_id>/deliver")
@require_roles("PlatformAdmin")
def deliver_order(pid: str, order_id: str):
    platform, o = get_order(pid, order_id)
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        occ_check(body, o)
    from services.calculations import COLD_CHAIN_DISPOSE_THRESHOLD

    if o.get("dispensing_status") != "SHIPPED":
        raise err("ERR_ORDER_NOT_SHIPPED", "Order is not SHIPPED.")
    if o.get("cold_chain_required"):
        s = db.cold_chain_shipments.get(o.get("cold_chain_shipment_id") or "")
        if not s or s.get("status") not in {"IN_TRANSIT", "DELIVERED"}:
            raise err("ERR_COLD_CHAIN_OUT_OF_RANGE", "Cold-chain shipment not in valid state.")
        if int(s.get("excursion_score") or 0) > COLD_CHAIN_DISPOSE_THRESHOLD:
            raise err("ERR_COLD_CHAIN_OUT_OF_RANGE", "excursion_score exceeds threshold.")
    o["dispensing_status"] = "DELIVERED"
    stamp_update(o, platform)
    actor_id, actor_role = current_actor()
    append_audit_log(
        platform=platform,
        subject_type="ORDER",
        subject_id=o["id"],
        action="ORDER_DELIVERED",
        actor_role=actor_role,
        actor_id=actor_id,
        payload={"dispensing_status": o["dispensing_status"], "version": o["version"]},
    )
    emit_external_event(
        platform=platform,
        channel="LOGISTICS",
        event_type="order.delivered",
        subject_type="ORDER",
        subject_id=o["id"],
        payload={"order_id": o["id"], "version": o["version"]},
        idempotency_key=f"order.delivered:{o['id']}:{o['version']}",
    )
    if o.get("cold_chain_shipment_id"):
        s = db.cold_chain_shipments.get(o["cold_chain_shipment_id"])
        if s and s.get("status") == "IN_TRANSIT":
            s["status"] = "DELIVERED"
            stamp_update(s, platform)
    evaluate_prescription_archive(platform, o.get("prescription_id"))
    return success_object(serialize(o)), 200
