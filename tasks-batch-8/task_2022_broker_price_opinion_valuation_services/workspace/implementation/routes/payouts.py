"""Payout batch endpoints (PRD 3.8)."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    ERR_EMPTY_BATCH,
    ERR_ORDER_NOT_COMPLETED,
)
from middleware import allowed
from response import success_object, success_list
from serializers import ser_payout_batch
from validation import body, req_iso, sort_and_page

bp = Blueprint("payouts", __name__)


def _get_batch_or_404(batch_id: str) -> dict:
    batch = db.payout_batches.get(batch_id)
    if batch is None:
        raise ApiError(ERR_NOT_FOUND, f"PayoutBatch {batch_id} not found", 404)
    return batch


def _contributing_orders(broker_id: str, period_start, period_end):
    """COMPLETED orders for the broker with completed_at in [start, end)."""
    return [
        o for o in db.orders.values()
        if o["fulfillment_status"] == "COMPLETED"
        and o["assigned_broker_id"] == broker_id
        and o["completed_at"] is not None
        and period_start <= o["completed_at"] < period_end
    ]


@bp.post("/bpo/payout-batches")
@allowed("BillingClerk")
def create_payout_batch(user_id, role):
    b = body()
    broker_id = b.get("broker_id")
    if broker_id is None or not isinstance(broker_id, str):
        raise ApiError(ERR_INVALID_REQUEST, "Field 'broker_id': required string", 400)
    if db.brokers.get(broker_id) is None:
        raise ApiError(ERR_NOT_FOUND, f"Broker {broker_id} not found", 404)
    period_start = req_iso(b, "period_start")
    period_end = req_iso(b, "period_end")
    if period_end <= period_start:
        raise ApiError(ERR_INVALID_REQUEST, "Field 'period_end' must be strictly after 'period_start'", 400)

    contributing = _contributing_orders(broker_id, period_start, period_end)
    # Round-per-line: each order's net_payable_cents is already integer cents.
    total = sum(o["net_payable_cents"] for o in contributing)

    record = db.stamp_new({
        "id": db.new_id(),
        "broker_id": broker_id,
        "period_start": period_start,
        "period_end": period_end,
        "total_payable_cents": total,
        "order_count": len(contributing),
        "status": "OPEN",
        "_contributing_order_ids": [o["id"] for o in contributing],
    })
    db.payout_batches[record["id"]] = record
    return success_object(ser_payout_batch(record), 201)


@bp.get("/bpo/payout-batches")
@allowed("BillingClerk", "OperationsManager", "PlatformAdmin", "Broker")
def list_payout_batches(user_id, role):
    records = list(db.payout_batches.values())
    broker_id = request.args.get("broker_id")
    if broker_id is not None:
        records = [r for r in records if r["broker_id"] == broker_id]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    items, limit, offset, total = sort_and_page(records, ser_payout_batch)
    return success_list(items, limit, offset, total)


@bp.get("/bpo/payout-batches/<batch_id>")
@allowed("BillingClerk", "OperationsManager", "PlatformAdmin", "Broker")
def get_payout_batch(user_id, role, batch_id):
    batch = _get_batch_or_404(batch_id)
    return success_object(ser_payout_batch(batch))


@bp.post("/bpo/payout-batches/<batch_id>/approve")
@allowed("BillingClerk")
def approve_payout_batch(user_id, role, batch_id):
    b = body()
    batch = _get_batch_or_404(batch_id)
    if batch["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, f"PayoutBatch is {batch['status']}, expected OPEN", 409)
    # Priority 21: non-empty batch
    if batch["order_count"] < 1:
        raise ApiError(ERR_EMPTY_BATCH, "PayoutBatch has no contributing orders", 409)
    # Priority 28: optimistic concurrency
    expected = b.get("expected_batch_version")
    if expected is None or not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError(ERR_INVALID_REQUEST, "Field 'expected_batch_version': required integer", 400)
    if expected != batch["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            f"expected_batch_version {expected} does not match current version {batch['version']}",
            412,
        )
    # Snapshot: total_payable_cents is never recomputed after approval.
    batch["status"] = "APPROVED"
    db.touch(batch)
    return success_object(ser_payout_batch(batch))


@bp.post("/bpo/payout-batches/<batch_id>/disburse")
@allowed("BillingClerk")
def disburse_payout_batch(user_id, role, batch_id):
    batch = _get_batch_or_404(batch_id)
    if batch["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, f"PayoutBatch is {batch['status']}, expected APPROVED", 409)
    # Priority 22: every contributing order must still be COMPLETED
    contributing = [
        db.orders[oid] for oid in batch["_contributing_order_ids"] if oid in db.orders
    ]
    for order in contributing:
        if order["fulfillment_status"] != "COMPLETED":
            raise ApiError(ERR_ORDER_NOT_COMPLETED, f"Order {order['id']} is not COMPLETED", 409)
    for order in contributing:
        order["payment_status"] = "PAID"
        db.touch(order)
    batch["status"] = "DISBURSED"
    db.touch(batch)
    return success_object(ser_payout_batch(batch))


@bp.post("/bpo/payout-batches/<batch_id>/void")
@allowed("BillingClerk")
def void_payout_batch(user_id, role, batch_id):
    batch = _get_batch_or_404(batch_id)
    if batch["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, f"PayoutBatch is {batch['status']}, expected OPEN", 409)
    batch["status"] = "VOIDED"
    db.touch(batch)
    return success_object(ser_payout_batch(batch))
