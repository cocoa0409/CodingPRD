"""Refund requests and settlement (PRD §3.8)."""
import datetime

from flask import Blueprint, request

import db
import middleware
from errors import ApiError
from response import object_response, paginate
from services import constants as C
from services import derive, lookup, refunds, serializers, workflow

bp = Blueprint("refund_requests", __name__)

_REFUNDABLE_PAYMENT_STATUSES = ("PAID", "REFUND_PENDING", "PARTIALLY_REFUNDED")


def _parse_item_refunds(payload):
    entries = payload.get("item_refunds")
    if entries is None:
        middleware.bad("item_refunds is required.")
    if not isinstance(entries, list) or len(entries) == 0:
        middleware.bad("item_refunds must be a non-empty array.")
    parsed = []
    for raw in entries:
        if not isinstance(raw, dict):
            middleware.bad("each entry of item_refunds must be an object.")
        parsed.append(
            {
                "order_item_id": middleware.req_string(raw, "order_item_id"),
                "quantity": middleware.req_int(raw, "quantity", minimum=1),
            }
        )
    return parsed


def _guard_scope(actor, refund_record):
    order = lookup.order(refund_record["order_id"])
    lookup.require_buyer_is(actor, order["buyer_id"])
    lookup.require_organizer_owns_event(actor, lookup.event(order["event_id"]))
    return order


@bp.route("/api/refund-requests", methods=["POST"])
def create_refund_request():
    actor = middleware.authenticate(["Buyer", "Organizer"])
    payload = middleware.body()
    order_id = middleware.req_string(payload, "order_id")
    item_refunds = _parse_item_refunds(payload)
    reason = middleware.req_string(payload, "reason", allow_empty=True)
    policy = middleware.opt_enum(payload, "policy", C.REFUND_POLICIES)

    order = lookup.order(order_id)
    for entry in item_refunds:
        item = lookup.order_item(entry["order_item_id"])
        if item["order_id"] != order["id"]:
            raise ApiError(
                "ERR_ORDER_ITEM_NOT_FOUND", "The order line does not belong to that order."
            )
    event = lookup.event(order["event_id"])

    lookup.require_buyer_is(actor, order["buyer_id"])
    lookup.require_organizer_owns_event(actor, event)

    if order["payment_status"] not in _REFUNDABLE_PAYMENT_STATUSES:
        raise ApiError("ERR_ORDER_NOT_PAID", "The order is not in a refundable payment state.")

    now = db.now()
    paid_at = db.parse_iso(order["paid_at"]) if order["paid_at"] else None
    window_end = (
        paid_at + datetime.timedelta(days=C.REFUND_REQUEST_WINDOW_DAYS)
        if paid_at
        else None
    )
    if window_end is None or now >= window_end or now >= db.parse_iso(event["starts_at"]):
        raise ApiError("ERR_REFUND_WINDOW_CLOSED", "The refund window is closed.")

    for entry in item_refunds:
        item = db.store.order_items[entry["order_item_id"]]
        remaining = item["quantity"] - derive.settled_refund_quantity(item["id"])
        if entry["quantity"] > remaining:
            raise ApiError(
                "ERR_REFUND_EXCEEDS_ORDER",
                "The requested quantity exceeds the unrefunded quantity on that line.",
            )

    record = db.base_record()
    record.update(
        {
            "order_id": order["id"],
            "policy": policy or event["refund_policy"],
            "status": "REQUESTED",
            "item_refunds": item_refunds,
            "refund_amount_cents": 0,
            "platform_retained_cents": 0,
            "organizer_charged_cents": 0,
            "reason": reason,
            "settled_at": None,
        }
    )
    db.store.refund_requests[record["id"]] = record
    return object_response(serializers.refund_request(record), 201)


@bp.route("/api/refund-requests/<refund_id>", methods=["GET"])
def read_refund_request(refund_id):
    actor = middleware.authenticate(["Buyer", "Organizer", "FinanceOfficer", "PlatformAdmin"])
    record = lookup.refund_request(refund_id)
    _guard_scope(actor, record)
    return object_response(serializers.refund_request(record))


@bp.route("/api/refund-requests", methods=["GET"])
def list_refund_requests():
    middleware.authenticate(["Buyer", "Organizer", "FinanceOfficer", "PlatformAdmin"])
    order_id = request.args.get("order_id")
    status = middleware.query_enum("status", C.REFUND_STATUSES)
    records = [
        r
        for r in db.store.refund_requests.values()
        if (order_id is None or r["order_id"] == order_id)
        and (status is None or r["status"] == status)
    ]
    return paginate(db.ordered(records), serializers.refund_request)


@bp.route("/api/refund-requests/<refund_id>/approve", methods=["POST"])
def approve_refund_request(refund_id):
    actor = middleware.authenticate(["Organizer"])
    middleware.body()
    record = lookup.refund_request(refund_id)
    order = _guard_scope(actor, record)
    event = lookup.event(order["event_id"])

    if record["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_REFUND_STATE", "The refund request is not in REQUESTED.")
    if order["payment_status"] not in _REFUNDABLE_PAYMENT_STATUSES:
        raise ApiError("ERR_ORDER_NOT_PAID", "The order is not in a refundable payment state.")

    record["status"] = "APPROVED"
    record.update(
        refunds.compute(order, record["item_refunds"], record["policy"], event["fee_mode"])
    )
    db.touch(record)
    return object_response(serializers.refund_request(record))


@bp.route("/api/refund-requests/<refund_id>/reject", methods=["POST"])
def reject_refund_request(refund_id):
    actor = middleware.authenticate(["Organizer"])
    payload = middleware.body()
    middleware.opt_string(payload, "reason")
    record = lookup.refund_request(refund_id)
    _guard_scope(actor, record)

    if record["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_REFUND_STATE", "The refund request is not in REQUESTED.")

    record["status"] = "REJECTED"
    record["refund_amount_cents"] = 0
    record["platform_retained_cents"] = 0
    record["organizer_charged_cents"] = 0
    db.touch(record)
    return object_response(serializers.refund_request(record))


@bp.route("/api/refund-requests/<refund_id>/settle", methods=["POST"])
def settle_refund_request(refund_id):
    middleware.authenticate(["FinanceOfficer"])
    middleware.body()
    record = lookup.refund_request(refund_id)
    lookup.order(record["order_id"])

    if record["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_REFUND_STATE", "The refund request is not APPROVED.")

    workflow.settle_refund(record)
    return object_response(serializers.refund_request(record))
