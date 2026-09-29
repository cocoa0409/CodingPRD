"""Price change order endpoints (PRD 3.6, 3.7)."""
from flask import Blueprint, request

import clock
import db
from errors import err
from middleware import (ALL_ROLES, PRICING_ANALYST, PRICING_MANAGER, body,
                        endpoint)
from response import object_response
from routes.common import (FK_PRODUCT, FK_SIGNAGE_STORE, FK_SUPERSEDES, filtered,
                           list_page, path_lookup, resolve_fks)
from services import calc, cascades, serialize
from util import as_dt, as_enum, as_int, as_str, get_required

bp = Blueprint("change_orders", __name__)

CREATABLE_ORIGINS = ("AUTOMATED_RULE", "MANUAL")
DECISIONS = ("APPROVE", "REJECT")
SUPERSEDABLE = ("DRAFT", "PENDING_APPROVAL", "APPROVED", "SUSPENDED")


@bp.post("/change-orders")
@endpoint([PRICING_ANALYST, PRICING_MANAGER])
def create_change_order(user_id, role):
    payload = body()
    fks = resolve_fks(payload, [FK_PRODUCT, FK_SIGNAGE_STORE, FK_SUPERSEDES])

    product = fks["product_id"]
    if product is None:
        get_required(payload, "product_id")
    origin_raw = as_str(get_required(payload, "origin"), "origin", min_len=1)
    effective_from = as_dt(get_required(payload, "effective_from"),
                           "effective_from")
    expected_product_version = as_int(
        get_required(payload, "expected_product_version"),
        "expected_product_version", minimum=0)
    requested_price_cents = None
    if payload.get("requested_price_cents") is not None:
        requested_price_cents = as_int(payload["requested_price_cents"],
                                      "requested_price_cents", gt=0)
    effective_until = None
    if payload.get("effective_until") is not None:
        effective_until = as_dt(payload["effective_until"], "effective_until")

    origin = as_enum(origin_raw, "origin", CREATABLE_ORIGINS)

    if expected_product_version != product["version"]:
        raise err("ERR_STALE_PRODUCT_VERSION",
                  "expected_product_version %d does not match the product's "
                  "current version %d."
                  % (expected_product_version, product["version"]))

    superseded = fks["supersedes_order_id"]
    if superseded is not None:
        if superseded["product_id"] != product["id"]:
            raise err("ERR_INVALID_STATE",
                      "The superseded order names a different product.")
        if superseded["status"] not in SUPERSEDABLE:
            raise err("ERR_INVALID_STATE",
                      "An order in %s cannot be superseded." % superseded["status"])

    market = db.markets.get(product["market_id"])
    if market is not None and market["pricing_posture"] == "FROZEN":
        raise err("ERR_MARKET_POSTURE_BLOCKED",
                  "The market's pricing_posture is FROZEN.")

    if origin == "AUTOMATED_RULE" and product["brand_repricing_restricted"]:
        raise err("ERR_BRAND_REPRICING_RESTRICTED",
                  "The brand forbids automated repricing of this product.")

    signage_store = fks["signage_store_id"]
    if signage_store is not None and signage_store["market_id"] != product["market_id"]:
        raise err("ERR_MARKET_MISMATCH",
                  "signage_store_id names a store outside the product's market.")

    rule = None
    benchmark_price_cents = None
    if origin == "AUTOMATED_RULE":
        rule = calc.select_rule_or_fail(product)
        benchmark_price_cents = calc.select_benchmark_or_fail(product)

    if cascades.effective_window_overlap(product["id"], effective_from,
                                         effective_until):
        raise err("ERR_EFFECTIVE_WINDOW_OVERLAP",
                  "The effective window overlaps a live order on this product.")

    if origin == "MANUAL" and requested_price_cents is None:
        raise err("ERR_REQUESTED_PRICE_MISMATCH",
                  "A MANUAL order must carry requested_price_cents.")
    if origin == "AUTOMATED_RULE" and requested_price_cents is not None:
        raise err("ERR_REQUESTED_PRICE_MISMATCH",
                  "An AUTOMATED_RULE order must not carry requested_price_cents.")

    proposal = calc.repricing_proposal(
        product, origin, rule=rule,
        benchmark_price_cents=benchmark_price_cents,
        hand_set_price_cents=requested_price_cents)

    record = db.new_record()
    record.update({
        "product_id": product["id"],
        "market_id": product["market_id"],
        "rule_id": rule["id"] if rule is not None else None,
        "source_claim_id": None,
        "signage_store_id": signage_store["id"] if signage_store is not None else None,
        "supersedes_order_id": superseded["id"] if superseded is not None else None,
        "label_batch_id": None,
        "origin": origin,
        "requested_price_cents": requested_price_cents,
        "benchmark_price_cents": benchmark_price_cents,
        "effective_from": effective_from,
        "effective_until": effective_until,
        "status": "DRAFT",
        "signage_status": "NOT_REQUIRED",
        "authored_by_user_id": user_id,
        "decided_by_user_id": None,
    })
    record.update(proposal)
    db.orders[record["id"]] = record
    db.touch(product)

    if superseded is not None:
        cascades.supersede_order(superseded)

    return object_response(serialize.order(record), 201)


@bp.post("/change-orders/<order_id>/submit")
@endpoint([PRICING_ANALYST, PRICING_MANAGER])
def submit_change_order(user_id, role, order_id):
    order = path_lookup("orders", order_id, "ERR_ORDER_NOT_FOUND")
    if order["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Only a DRAFT order may be submitted.")
    _require_posture(order, ("OPEN", "RESTRICTED"))
    order["status"] = "PENDING_APPROVAL"
    db.touch(order)
    return object_response(serialize.order(order))


@bp.post("/change-orders/<order_id>/decide")
@endpoint([PRICING_MANAGER])
def decide_change_order(user_id, role, order_id):
    order = path_lookup("orders", order_id, "ERR_ORDER_NOT_FOUND")
    payload = body()
    decision_raw = as_str(get_required(payload, "decision"), "decision", min_len=1)
    if payload.get("note") is not None:
        as_str(payload["note"], "note", min_len=1)
    decision = as_enum(decision_raw, "decision", DECISIONS)

    if order["status"] != "PENDING_APPROVAL":
        raise err("ERR_INVALID_STATE",
                  "Only a PENDING_APPROVAL order may be decided.")
    if decision == "APPROVE":
        _require_posture(order, ("OPEN", "RESTRICTED"))
    if user_id == order["authored_by_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES",
                  "The author of an order may not decide it.")

    order["decided_by_user_id"] = user_id
    if decision == "APPROVE":
        order["status"] = "APPROVED"
        cascades.label_batch_selection(order)
    else:
        order["status"] = "DRAFT"
    db.touch(order)
    return object_response(serialize.order(order))


@bp.post("/change-orders/<order_id>/execute")
@endpoint([PRICING_MANAGER])
def execute_change_order(user_id, role, order_id):
    order = path_lookup("orders", order_id, "ERR_ORDER_NOT_FOUND")
    if order["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Only an APPROVED order may be executed.")
    if clock.now() < order["effective_from"]:
        raise err("ERR_INVALID_STATE",
                  "The order's effective_from has not been reached.")
    _require_posture(order, ("OPEN",))

    product = db.products.get(order["product_id"])
    rule = db.rules.get(order["rule_id"]) if order["rule_id"] else None
    if order["origin"] == "AUTOMATED_RULE" and rule is not None:
        if not calc.frequency_limit_satisfied(product, rule):
            raise err("ERR_CHANGE_FREQUENCY_LIMIT",
                      "The rule's change_frequency_limit_days has not elapsed.")

    cascades.execute_order(order, product, rule)
    return object_response(serialize.order(order))


@bp.get("/change-orders/<order_id>")
@endpoint(ALL_ROLES)
def read_change_order(user_id, role, order_id):
    order = path_lookup("orders", order_id, "ERR_ORDER_NOT_FOUND")
    return object_response(serialize.order(order))


@bp.get("/change-orders")
@endpoint(ALL_ROLES)
def list_change_orders(user_id, role):
    rows = filtered(db.ordered(db.orders), request.args,
                    [("product_id", "product_id"), ("market_id", "market_id"),
                     ("rule_id", "rule_id"),
                     ("source_claim_id", "source_claim_id"),
                     ("supersedes_order_id", "supersedes_order_id"),
                     ("label_batch_id", "label_batch_id"),
                     ("signage_store_id", "signage_store_id"),
                     ("status", "status"), ("signage_status", "signage_status"),
                     ("origin", "origin")])
    return list_page(rows, serialize.order)


def _require_posture(order, allowed):
    market = db.markets.get(order["market_id"])
    if market is None:
        return
    if market["pricing_posture"] not in allowed:
        raise err("ERR_MARKET_POSTURE_BLOCKED",
                  "The market's pricing_posture is %s." % market["pricing_posture"])
