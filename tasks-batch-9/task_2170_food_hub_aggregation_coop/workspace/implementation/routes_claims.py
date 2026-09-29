"""Rejection claims and shrink apportionment between producer and hub."""

from flask import Blueprint, request

import domain
import fetch
import governance
import serializers
from constants import (CLAIM_DECISIONS, CLAIM_REASONS, ROLE_BUYER,
                       ROLE_COMPLIANCE, ROLE_HUB_ADMIN, ROLE_PRODUCER)
from envelope import list_response, ok
from errors import ApiError
from store import base_record, db, sorted_records, touch
from validators import (actor, body, endpoint, opt_string, req_enum, req_int,
                        req_string)

bp = Blueprint("claims", __name__)


@bp.get("/allocations/<allocation_id>/rejection-claims")
@endpoint([ROLE_HUB_ADMIN, ROLE_COMPLIANCE, ROLE_PRODUCER, ROLE_BUYER])
def list_claims(allocation_id):
    fetch.get("allocation", allocation_id)
    records = sorted_records([c for c in db.claims.values()
                              if c["allocation_id"] == allocation_id])
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return list_response(records, serializers.claim_out)


@bp.post("/rejection-claims")
@endpoint([ROLE_BUYER, ROLE_HUB_ADMIN])
def file_claim():
    payload = body()
    allocation = fetch.body_fk(payload, "allocation_id", "allocation")   # rung 5

    # rung 6
    req_string(payload, "allocation_id")
    quantity_rejected = req_int(payload, "quantity_rejected", minimum=1)
    reason_code = req_enum(payload, "reason_code", CLAIM_REASONS)
    note = opt_string(payload, "note")

    order = domain.allocation_order(allocation)
    user_id, role = actor()
    if role == ROLE_BUYER:                                               # rung 7
        if order is None or user_id != order["buyer_id"]:
            raise ApiError("ERR_NOT_RESOURCE_OWNER")

    # rung 10 — claims only against goods that have actually been billed
    if allocation["status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_ORDER_STATE")
    if order is None or order["fulfillment_status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_ORDER_STATE")
    if order["settlement_status"] not in ("INVOICED", "PARTIALLY_PAID"):
        raise ApiError("ERR_INVALID_ORDER_STATE")

    # rung 26 — rejection quantity headroom
    headroom = allocation["delivered_quantity"] - allocation["rejected_quantity"]
    if quantity_rejected > headroom:
        raise ApiError("ERR_REJECTION_EXCEEDS_DELIVERED")

    claim = base_record({
        "allocation_id": allocation["id"],
        "quantity_rejected": quantity_rejected,
        "reason_code": reason_code,
        "note": note,
        "filed_by_user_id": user_id,
        "adjudicated_by_user_id": None,
        "status": "FILED",
        "producer_fault_bp": 0,
        "buyer_credit_cents": 0,
        "producer_charge_cents": 0,
        "hub_absorbed_cents": 0,
    })
    db.claims[claim["id"]] = claim
    return ok(serializers.claim_out(claim), 201)


@bp.post("/rejection-claims/<claim_id>/adjudication")
@endpoint([ROLE_COMPLIANCE, ROLE_BUYER])
def adjudicate_claim(claim_id):
    claim = fetch.get("claim", claim_id)                                 # rung 4
    payload = body()
    decision = req_enum(payload, "decision", CLAIM_DECISIONS)            # rung 6
    opt_string(payload, "note")

    allocation = db.allocations.get(claim["allocation_id"])
    order = domain.allocation_order(allocation) if allocation else None
    user_id, role = actor()

    # rung 7 — only the owning buyer may act on its own claim
    if role == ROLE_BUYER:
        if order is None or user_id != order["buyer_id"]:
            raise ApiError("ERR_NOT_RESOURCE_OWNER")

    # rung 8 — decision authority
    if decision in ("APPROVE", "DENY") and role != ROLE_COMPLIANCE:
        raise ApiError("ERR_DECISION_ROLE_MISMATCH")
    if decision == "WITHDRAW" and role != ROLE_BUYER:
        raise ApiError("ERR_DECISION_ROLE_MISMATCH")

    # rung 10 — a claim is resolved exactly once
    if claim["status"] != "FILED":
        raise ApiError("ERR_INVALID_CLAIM_STATE")

    # rung 12 — an officer may not adjudicate a claim they filed
    if decision in ("APPROVE", "DENY") and user_id == claim["filed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    claim["adjudicated_by_user_id"] = user_id

    if decision == "DENY":
        claim["status"] = "DENIED"
        touch(claim)
        return ok(serializers.claim_out(claim))

    if decision == "WITHDRAW":
        claim["status"] = "WITHDRAWN"
        touch(claim)
        return ok(serializers.claim_out(claim))

    producer = domain.allocation_producer(allocation)
    result = governance.compute_shrink(claim, allocation, producer)

    claim["status"] = "APPROVED"
    claim["producer_fault_bp"] = result["producer_fault_bp"]
    claim["buyer_credit_cents"] = result["buyer_credit_cents"]
    claim["producer_charge_cents"] = result["producer_charge_cents"]
    claim["hub_absorbed_cents"] = result["hub_absorbed_cents"]
    touch(claim)

    allocation["rejected_quantity"] += claim["quantity_rejected"]
    allocation["producer_charge_cents"] += result["producer_charge_cents"]
    allocation["hub_absorbed_cents"] += result["hub_absorbed_cents"]
    touch(allocation)

    line = db.lines.get(allocation["order_line_id"])
    if line is not None:
        line["quantity_rejected"] += claim["quantity_rejected"]
        touch(line)

    if order is not None:
        order["credit_memo_cents"] += result["buyer_credit_cents"]
        touch(order)
        buyer = db.buyers.get(order["buyer_id"])
        if buyer is not None:
            buyer["outstanding_balance_cents"] -= result["buyer_credit_cents"]
            touch(buyer)

    if producer is not None:
        producer["shrink_charge_cents"] += result["producer_charge_cents"]
        touch(producer)

    return ok(serializers.claim_out(claim))
