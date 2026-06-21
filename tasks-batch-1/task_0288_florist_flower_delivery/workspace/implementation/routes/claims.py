"""Quality-claim routes: file/approve/reject/resolve, with redelivery spawn
and refund (PRD §3.7)."""
from flask import Blueprint, request

import errors
from db import store
from middleware import require_auth, require_role
from helpers import (
    get_body, make_record, touch, public, parse_pagination, paginate,
    require_fields, as_int, as_str, as_enum,
)
from response import success, success_list
from services import clock
from services import pricing

bp = Blueprint("claims", __name__)

REASONS = {"WILTED", "WRONG_ITEM", "LATE", "DAMAGED"}
REMEDIES = {"REDELIVERY", "REFUND"}


@bp.route("/floral/claims", methods=["POST"])
def file_claim():
    user_id, role = require_auth()
    require_role(role, {"Customer", "Dispatcher"})
    body = get_body()
    require_fields(body, ["order_id", "customer_id", "reason", "requested_remedy"])
    order_id = as_str(body, "order_id")
    customer_id = as_str(body, "customer_id")
    reason = as_enum(body, "reason", REASONS)
    requested_remedy = as_enum(body, "requested_remedy", REMEDIES)

    # Ownership: a Customer files under its own identity.
    if role == "Customer" and customer_id != user_id:
        raise errors.not_resource_owner("Customer identity mismatch")

    # Existence: FKs left-to-right.
    order = store.orders.get(order_id)
    if order is None:
        raise errors.not_found("order_id not found")
    if customer_id not in store.customers:
        raise errors.not_found("customer_id not found")

    # Claimant must own the order.
    if order["customer_id"] != customer_id:
        raise errors.not_resource_owner("Claimant does not own the order")

    # Claim window: order must be DELIVERED.
    if order["fulfillment_status"] != "DELIVERED":
        raise errors.ApiError(errors.ERR_CLAIM_WINDOW_INVALID, 409,
                              "Order is not in DELIVERED state")

    rec = make_record()
    rec.update({
        "order_id": order_id,
        "customer_id": customer_id,
        "reason": reason,
        "requested_remedy": requested_remedy,
        "status": "OPEN",
        "refund_cents": 0,
        "redelivery_order_id": None,
    })
    store.claims[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.route("/floral/claims/<cid>", methods=["GET"])
def get_claim(cid):
    _, role = require_auth()
    require_role(role, {"Customer", "Dispatcher", "CatalogAdmin"})
    rec = store.claims.get(cid)
    if rec is None:
        raise errors.not_found("Claim not found")
    return success(public(rec))


@bp.route("/floral/claims", methods=["GET"])
def list_claims():
    _, role = require_auth()
    require_role(role, {"Customer", "Dispatcher", "CatalogAdmin"})
    limit, offset = parse_pagination()
    rows = list(store.claims.values())
    order_id = request.args.get("order_id")
    customer_id = request.args.get("customer_id")
    if order_id is not None:
        rows = [r for r in rows if r["order_id"] == order_id]
    if customer_id is not None:
        rows = [r for r in rows if r["customer_id"] == customer_id]
    page, total = paginate(rows, limit, offset)
    return success_list([public(r) for r in page], limit, offset, total)


@bp.route("/floral/claims/<cid>/approve", methods=["POST"])
def approve_claim(cid):
    _, role = require_auth()
    require_role(role, {"Dispatcher"})
    claim = store.claims.get(cid)
    if claim is None:
        raise errors.not_found("Claim not found")
    if claim["status"] != "OPEN":
        raise errors.invalid_state("Approve is only defined from OPEN")
    order = store.orders.get(claim["order_id"])
    if order is None or order["fulfillment_status"] != "DELIVERED":
        raise errors.precondition_not_met("Linked order must be DELIVERED")
    if claim["requested_remedy"] == "REFUND":
        claim["refund_cents"] = pricing.compute_claim_refund(claim, order)
    claim["status"] = "APPROVED"
    touch(claim)
    return success(public(claim))


@bp.route("/floral/claims/<cid>/reject", methods=["POST"])
def reject_claim(cid):
    _, role = require_auth()
    require_role(role, {"Dispatcher"})
    claim = store.claims.get(cid)
    if claim is None:
        raise errors.not_found("Claim not found")
    if claim["status"] != "OPEN":
        raise errors.invalid_state("Reject is only defined from OPEN")
    claim["status"] = "REJECTED"
    touch(claim)
    return success(public(claim))


@bp.route("/floral/claims/<cid>/resolve", methods=["POST"])
def resolve_claim(cid):
    _, role = require_auth()
    require_role(role, {"Dispatcher"})
    claim = store.claims.get(cid)
    if claim is None:
        raise errors.not_found("Claim not found")
    body = get_body()
    require_fields(body, ["expected_order_version"])
    expected_version = as_int(body, "expected_order_version")
    if claim["status"] != "APPROVED":
        raise errors.invalid_state("Resolve is only defined from APPROVED")
    order = store.orders.get(claim["order_id"])
    if order is None:
        raise errors.not_found("Linked order not found")
    # OCC: expected_order_version must equal linked order's current version.
    if expected_version != order["version"]:
        raise errors.stale_order_version("expected_order_version is stale")

    if claim["requested_remedy"] == "REDELIVERY":
        original = order
        new_order = make_record()
        new_order.update({
            "customer_id": original["customer_id"],
            "arrangement_id": original["arrangement_id"],
            "zone_id": original["zone_id"],
            "parent_recurrence_id": None,
            "source_order_id": original["id"],
            "occasion": original["occasion"],
            "card_message": original["card_message"],
            "delivery_date": clock.add_days(clock.clock_date(), 1)
                if clock.clock_date() is not None else original["delivery_date"],
            "window_start_minute": original["window_start_minute"],
            "window_end_minute": original["window_end_minute"],
            "apply_wallet_credit": False,
            "fulfillment_status": "DRAFT",
            "payment_status": "UNPAID",
            "estimated_total_cents": 0,
            "final_total_cents": 0,
            "wallet_credit_applied_cents": 0,
            "is_same_day": False,
            "_authorized_amount_cents": 0,
        })
        store.orders[new_order["id"]] = new_order
        claim["redelivery_order_id"] = new_order["id"]
    else:  # REFUND
        if order["payment_status"] == "CAPTURED":
            order["payment_status"] = "REFUNDED"
        customer = store.customers[order["customer_id"]]
        customer["wallet_credit_cents"] += claim["refund_cents"]
        touch(customer)

    # Linked order's version increments on resolution.
    touch(order)
    claim["status"] = "RESOLVED"
    touch(claim)
    return success(public(claim))
