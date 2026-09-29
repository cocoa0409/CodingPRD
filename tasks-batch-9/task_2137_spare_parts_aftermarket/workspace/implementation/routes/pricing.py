"""Aftermarket price rules and the hypothetical price quote."""
from flask import Blueprint, request

import auth
import calc
import domain
import envelope
import serializers
import store
from errors import ApiError

bp = Blueprint("pricing", __name__)

CRITICALITY_CLASSES = {"VITAL", "ESSENTIAL", "DESIRABLE"}


@bp.post("/aftermarket/price-rules")
def create_price_rule():
    auth.require("PricingAnalyst")
    data = auth.body()
    criticality_class = auth.req_enum(data, "criticality_class", CRITICALITY_CLASSES)
    base_uplift_pct = auth.req_number(data, "base_uplift_pct", minimum=0)
    max_uplift_pct = auth.req_number(data, "max_uplift_pct", minimum=0)
    min_margin_pct = auth.req_number(data, "min_margin_pct", minimum=0, exclusive_max=1)

    base = calc.dec(base_uplift_pct)
    cap = calc.dec(max_uplift_pct)
    if base > cap:
        raise ApiError("ERR_UPLIFT_CAP_EXCEEDED")

    for rule in store.price_rules.values():
        if rule["criticality_class"] == criticality_class and rule["rule_status"] == "ACTIVE":
            rule["rule_status"] = "RETIRED"
            store.touch(rule)

    rec = store.new_record("AftermarketPriceRule", {
        "criticality_class": criticality_class,
        "base_uplift_pct": base,
        "max_uplift_pct": cap,
        "min_margin_pct": calc.dec(min_margin_pct),
        "rule_status": "ACTIVE",
    })
    store.price_rules[rec["id"]] = rec
    return envelope.created(serializers.price_rule(rec))


@bp.get("/aftermarket/price-rules")
def list_price_rules():
    auth.require("PricingAnalyst", "AftermarketPlanner", "InventoryController", "PlatformAdmin")
    limit, offset = auth.pagination()
    criticality_class = auth.query_enum("criticality_class", CRITICALITY_CLASSES)
    rule_status = auth.query_enum("rule_status", {"ACTIVE", "RETIRED"})

    rows = list(store.price_rules.values())
    if criticality_class is not None:
        rows = [r for r in rows if r["criticality_class"] == criticality_class]
    if rule_status is not None:
        rows = [r for r in rows if r["rule_status"] == rule_status]
    rows = store.sort_created(rows)
    page, total = auth.paginate(rows, limit, offset)
    return envelope.listing([serializers.price_rule(r) for r in page], limit, offset, total)


@bp.get("/aftermarket/parts/<part_id>/price-quote")
def price_quote(part_id):
    auth.require("PricingAnalyst", "AftermarketPlanner", "DealerUser")
    part = domain.get_part(part_id)

    raw = request.args.get("qty")
    if raw is None or raw == "":
        raise ApiError("ERR_INVALID_REQUEST", "qty is required.")
    try:
        qty = int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "qty must be an integer.")
    if qty < 1:
        raise ApiError("ERR_INVALID_REQUEST", "qty must be >= 1.")

    rule = domain.active_price_rule(part["criticality_class"])
    if rule is None:
        raise ApiError("ERR_PRICE_RULE_NOT_FOUND")

    figures = calc.price_uplift(part["unit_cost_cents"], part["lifecycle_state"], rule, qty)
    if figures["margin_pct"] < calc.dec(rule["min_margin_pct"]):
        raise ApiError("ERR_MARGIN_FLOOR_BREACH")

    return envelope.ok(figures)
