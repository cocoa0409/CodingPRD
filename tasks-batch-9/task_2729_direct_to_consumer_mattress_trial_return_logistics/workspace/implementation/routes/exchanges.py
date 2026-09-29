"""Comfort exchanges."""
from flask import Blueprint

from db import base_record, db, now, ordered, paginate, touch
from errors import api_error
from middleware import require, require_customer_owner
from response import collection, single
from serialize import COMFORT_EXCHANGE, dump, dump_many
from services import calc, entities, orders as order_service
from validate import Fields, Query

bp = Blueprint("exchanges", __name__)

EXCHANGE_STATUSES = ("REQUESTED", "APPROVED", "DECLINED")


@bp.route("/comfort-exchanges", methods=["POST"])
@require("Customer", "TrialSupportAgent")
def create_comfort_exchange():
    fields = Fields("original_order_id", "target_model_id")
    original_order_id = fields.reference("original_order_id")
    target_model_id = fields.reference("target_model_id")
    order = entities.get_order(original_order_id)
    target_model = entities.get_model(target_model_id)
    require_customer_owner(order["customer_id"], "trial order")

    if (order["fulfillment_status"] not in ("DELIVERED", "DAMAGED_REPORTED")
            or order["trial_status"] not in ("BREAK_IN", "TRIAL_ACTIVE",
                                             "TRIAL_EXPIRED")):
        raise api_error("ERR_INVALID_ORDER_STATE",
                        "This order cannot be exchanged from its current "
                        "state")
    customer = entities.get_customer(order["customer_id"])
    if customer["status"] == "BLOCKED":
        raise api_error("ERR_TRIAL_ABUSE_BLOCK",
                        "Customer posture is BLOCKED")
    clock = now()
    if order["break_in_ends_at"] is None or clock < order["break_in_ends_at"]:
        raise api_error("ERR_BREAK_IN_NOT_ELAPSED",
                        "The break-in period has not elapsed yet")
    if order["trial_ends_at"] is None or clock >= order["trial_ends_at"]:
        raise api_error("ERR_TRIAL_WINDOW_EXPIRED",
                        "The trial window has closed")
    if order["exchange_chain_depth"] >= calc.MAX_EXCHANGES_PER_CHAIN:
        raise api_error("ERR_EXCHANGE_LIMIT_REACHED",
                        "This chain has already used its %d exchanges"
                        % calc.MAX_EXCHANGES_PER_CHAIN)
    original_model = entities.model_of_order(order)
    if target_model["size"] != original_model["size"]:
        raise api_error("ERR_MODEL_SIZE_MISMATCH",
                        "An exchange must keep the same bed size")

    settlement = calc.exchange_settlement(order, original_model, target_model)
    record = base_record()
    record.update({
        "original_order_id": order["id"],
        "target_model_id": target_model["id"],
        "replacement_order_id": None,
        "status": "REQUESTED",
        "decline_note": None,
    })
    record.update(settlement)
    db.comfort_exchanges[record["id"]] = record
    return single(dump(record, COMFORT_EXCHANGE), 201)


@bp.route("/comfort-exchanges/<exchange_id>", methods=["GET"])
@require("Customer", "TrialSupportAgent", "FinanceController", "PlatformAdmin")
def read_comfort_exchange(exchange_id):
    exchange = entities.get_exchange(exchange_id)
    order = entities.get_order(exchange["original_order_id"])
    require_customer_owner(order["customer_id"], "comfort exchange")
    return single(dump(exchange, COMFORT_EXCHANGE), 200)


@bp.route("/comfort-exchanges", methods=["GET"])
@require("Customer", "TrialSupportAgent", "FinanceController", "PlatformAdmin")
def list_comfort_exchanges():
    query = Query("original_order_id", "replacement_order_id",
                  "target_model_id", "status")
    limit, offset = query.page()
    original_order_id = query.string("original_order_id")
    replacement_order_id = query.string("replacement_order_id")
    target_model_id = query.string("target_model_id")
    status = query.enum("status", EXCHANGE_STATUSES)
    matches = ordered([
        e for e in db.comfort_exchanges.values()
        if (original_order_id is None
            or e["original_order_id"] == original_order_id)
        and (replacement_order_id is None
             or e["replacement_order_id"] == replacement_order_id)
        and (target_model_id is None
             or e["target_model_id"] == target_model_id)
        and (status is None or e["status"] == status)
    ])
    page, total = paginate(matches, limit, offset)
    return collection(dump_many(page, COMFORT_EXCHANGE), limit, offset, total)


@bp.route("/comfort-exchanges/<exchange_id>/approve", methods=["POST"])
@require("TrialSupportAgent")
def approve_comfort_exchange(exchange_id):
    fields = Fields("expected_trial_order_version")
    expected_version = fields.integer("expected_trial_order_version")
    exchange = entities.get_exchange(exchange_id)
    if exchange["status"] != "REQUESTED":
        raise api_error("ERR_INVALID_EXCHANGE_STATE",
                        "This exchange has already been decided")
    order = entities.get_order(exchange["original_order_id"])
    if order["fulfillment_status"] not in ("DELIVERED", "DAMAGED_REPORTED"):
        raise api_error("ERR_INVALID_ORDER_STATE",
                        "The original order is no longer exchangeable")
    if order["trial_status"] != "TRIAL_ACTIVE":
        raise api_error("ERR_INVALID_ORDER_STATE",
                        "The original order must be in TRIAL_ACTIVE")
    if expected_version != order["version"]:
        raise api_error("ERR_STALE_ORDER_VERSION",
                        "expected_trial_order_version does not match the "
                        "order's current version")
    customer = entities.get_customer(order["customer_id"])
    if customer["status"] == "BLOCKED":
        raise api_error("ERR_TRIAL_ABUSE_BLOCK",
                        "Customer posture is BLOCKED")

    target_model = db.mattress_models[exchange["target_model_id"]]
    replacement = order_service.new_order(
        customer, target_model, None, order["channel"],
        order["retail_partner_id"], target_model["list_price_cents"],
        exchanged_from_order_id=order["id"],
        exchange_chain_depth=order["exchange_chain_depth"] + 1)
    exchange["replacement_order_id"] = replacement["id"]

    order["trial_status"] = "EXCHANGED"
    order["fulfillment_status"] = "REPLACED"
    touch(order)

    for claim in ordered(list(db.quality_claims.values())):
        if (claim["order_id"] == order["id"]
                and claim["claim_type"] == "COMPRESSION_RECOVERY"
                and claim["status"] in entities.OPEN_CLAIM_STATUSES):
            claim["status"] = "WITHDRAWN"
            claim["resolution"] = "DENIED"
            claim["credit_cents"] = 0
            touch(claim)

    exchange["status"] = "APPROVED"
    touch(exchange)
    return single(dump(exchange, COMFORT_EXCHANGE), 200)


@bp.route("/comfort-exchanges/<exchange_id>/decline", methods=["POST"])
@require("TrialSupportAgent")
def decline_comfort_exchange(exchange_id):
    fields = Fields("decline_note")
    decline_note = fields.string("decline_note")
    exchange = entities.get_exchange(exchange_id)
    if exchange["status"] != "REQUESTED":
        raise api_error("ERR_INVALID_EXCHANGE_STATE",
                        "This exchange has already been decided")
    exchange["decline_note"] = decline_note
    exchange["status"] = "DECLINED"
    touch(exchange)
    return single(dump(exchange, COMFORT_EXCHANGE), 200)
