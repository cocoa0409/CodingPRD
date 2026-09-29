"""Trial orders."""
from flask import Blueprint

from db import db, now, ordered, paginate, touch
from errors import api_error, invalid
from middleware import require, require_customer_owner
from response import collection, single
from serialize import TRIAL_ORDER, dump, dump_many
from services import calc, entities, orders as order_service
from util import whole_days
from validate import Fields, Query

bp = Blueprint("orders", __name__)

CHANNELS = ("DTC", "RETAIL_PARTNER")
FULFILLMENT_STATUSES = ("CREATED", "IN_TRANSIT", "DELIVERED",
                        "DAMAGED_REPORTED", "REPLACED", "CLOSED")
TRIAL_STATUSES = ("NOT_STARTED", "BREAK_IN", "TRIAL_ACTIVE", "TRIAL_EXPIRED",
                  "RETURN_REQUESTED", "RETURNED", "KEPT", "EXCHANGED")
KEEPABLE_TRIAL = ("BREAK_IN", "TRIAL_ACTIVE", "TRIAL_EXPIRED")


@bp.route("/trial-orders", methods=["POST"])
@require("TrialSupportAgent", "PlatformAdmin")
def create_trial_order():
    fields = Fields("customer_id", "model_id", "channel", "gross_price_cents",
                    "bundle_id", "retail_partner_id")
    customer_id = fields.reference("customer_id")
    model_id = fields.reference("model_id")
    channel = fields.enum("channel", CHANNELS)
    gross_price_cents = fields.integer("gross_price_cents", minimum=1)
    bundle_id = fields.reference("bundle_id", required=False, default=None)
    retail_partner_id = fields.reference("retail_partner_id", required=False,
                                         default=None)
    if channel == "RETAIL_PARTNER" and retail_partner_id is None:
        raise invalid("retail_partner_id is required when channel is "
                      "RETAIL_PARTNER")

    customer = entities.get_customer(customer_id)
    model = entities.get_model(model_id)
    bundle = entities.get_bundle(bundle_id) if bundle_id else None
    if retail_partner_id is not None:
        entities.get_retail_partner(retail_partner_id)

    if customer["status"] == "BLOCKED":
        raise api_error("ERR_TRIAL_ABUSE_BLOCK",
                        "Customer posture is BLOCKED")

    live = order_service.household_live_orders(customer["household_hash"],
                                               customer["id"])
    delivered = order_service.household_delivered_orders(
        customer["household_hash"])
    if live or len(delivered) >= calc.HOUSEHOLD_TRIAL_LIMIT:
        raise api_error("ERR_HOUSEHOLD_TRIAL_LIMIT",
                        "This household has reached its concurrent trial limit")

    order = order_service.new_order(customer, model, bundle, channel,
                                    retail_partner_id, gross_price_cents)
    return single(dump(order, TRIAL_ORDER), 201)


@bp.route("/trial-orders/<order_id>", methods=["GET"])
@require("Customer", "RetailPartner", "TrialSupportAgent",
         "LogisticsCoordinator", "FinanceController", "PlatformAdmin")
def read_trial_order(order_id):
    order = entities.get_order(order_id)
    require_customer_owner(order["customer_id"], "trial order")
    return single(dump(order, TRIAL_ORDER), 200)


@bp.route("/trial-orders", methods=["GET"])
@require("Customer", "RetailPartner", "TrialSupportAgent",
         "LogisticsCoordinator", "FinanceController", "PlatformAdmin")
def list_trial_orders():
    query = Query("customer_id", "model_id", "bundle_id", "retail_partner_id",
                  "exchanged_from_order_id", "trial_status",
                  "fulfillment_status")
    limit, offset = query.page()
    customer_id = query.string("customer_id")
    model_id = query.string("model_id")
    bundle_id = query.string("bundle_id")
    retail_partner_id = query.string("retail_partner_id")
    exchanged_from_order_id = query.string("exchanged_from_order_id")
    trial_status = query.enum("trial_status", TRIAL_STATUSES)
    fulfillment_status = query.enum("fulfillment_status",
                                    FULFILLMENT_STATUSES)
    records = [entities.derive_order(o) for o in db.trial_orders.values()]
    matches = ordered([
        o for o in records
        if (customer_id is None or o["customer_id"] == customer_id)
        and (model_id is None or o["model_id"] == model_id)
        and (bundle_id is None or o["bundle_id"] == bundle_id)
        and (retail_partner_id is None
             or o["retail_partner_id"] == retail_partner_id)
        and (exchanged_from_order_id is None
             or o["exchanged_from_order_id"] == exchanged_from_order_id)
        and (trial_status is None or o["trial_status"] == trial_status)
        and (fulfillment_status is None
             or o["fulfillment_status"] == fulfillment_status)
    ])
    page, total = paginate(matches, limit, offset)
    return collection(dump_many(page, TRIAL_ORDER), limit, offset, total)


@bp.route("/trial-orders/<order_id>/dispatch", methods=["POST"])
@require("LogisticsCoordinator")
def dispatch_trial_order(order_id):
    Fields()
    order = entities.get_order(order_id)
    if order["fulfillment_status"] != "CREATED":
        raise api_error("ERR_INVALID_ORDER_STATE",
                        "Only a CREATED order can be dispatched")
    order["fulfillment_status"] = "IN_TRANSIT"
    touch(order)
    return single(dump(order, TRIAL_ORDER), 200)


@bp.route("/trial-orders/<order_id>/deliver", methods=["POST"])
@require("LogisticsCoordinator")
def deliver_trial_order(order_id):
    Fields()
    order = entities.get_order(order_id)
    if order["fulfillment_status"] != "IN_TRANSIT":
        raise api_error("ERR_INVALID_ORDER_STATE",
                        "Only an IN_TRANSIT order can be delivered")
    customer = entities.get_customer(order["customer_id"])
    model = entities.model_of_order(order)
    order_service.deliver(order, customer, model)
    return single(dump(order, TRIAL_ORDER), 200)


@bp.route("/trial-orders/<order_id>/keep", methods=["POST"])
@require("Customer", "TrialSupportAgent")
def keep_trial_order(order_id):
    Fields()
    order = entities.get_order(order_id)
    require_customer_owner(order["customer_id"], "trial order")
    if (order["fulfillment_status"] not in ("DELIVERED", "DAMAGED_REPORTED")
            or order["trial_status"] not in KEEPABLE_TRIAL):
        raise api_error("ERR_INVALID_ORDER_STATE",
                        "This order cannot be kept from its current state")
    if entities.active_return_cases(order["id"]):
        raise api_error("ERR_INVALID_ORDER_STATE",
                        "A live return case exists on this order")
    order_service.freeze_nights(
        order, max(0, whole_days(order["delivered_at"], now())))
    order["trial_status"] = "KEPT"
    order["fulfillment_status"] = "CLOSED"
    touch(order)
    return single(dump(order, TRIAL_ORDER), 200)
