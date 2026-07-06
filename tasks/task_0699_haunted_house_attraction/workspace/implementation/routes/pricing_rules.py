"""PricingRule endpoints (PRD §3.2). Pricing rules are immutable (PRD §2.4)."""
from flask import Blueprint, request

import db
import response
from middleware import get_identity, require_role, get_json_body, parse_pagination
from services import lookup
from services.common import (
    require_int, require_enum, optional_number, optional_int, base_record, sort_and_paginate,
)
from services.serialize import serialize_pricing_rule

bp = Blueprint("pricing_rules", __name__)

READ_ROLES = {"OpsManager", "BoxOffice", "Guest", "Actor"}


@bp.route("/attractions/<attraction_id>/pricing-rules", methods=["POST"])
def create_pricing_rule(attraction_id):
    _, role = get_identity()
    require_role(role, {"OpsManager"})
    attraction = lookup.attraction(attraction_id)
    body = get_json_body()
    tier = require_enum(body, "tier", {"GA", "FAST_PASS", "VIP"})
    base_price_cents = require_int(body, "base_price_cents", minimum=0)
    low_demand_max_ratio = optional_number(body, "low_demand_max_ratio", default=0.5)
    high_demand_min_ratio = optional_number(body, "high_demand_min_ratio", default=0.8)
    mid_surge_pct = optional_int(body, "mid_surge_pct", default=20)
    high_surge_pct = optional_int(body, "high_surge_pct", default=50)

    # Immutable record: id + created_at only (PRD §2.4).
    rule = base_record(with_version=False)
    rule.update({
        "attraction_id": attraction["id"],
        "tier": tier,
        "base_price_cents": base_price_cents,
        "low_demand_max_ratio": low_demand_max_ratio,
        "high_demand_min_ratio": high_demand_min_ratio,
        "mid_surge_pct": mid_surge_pct,
        "high_surge_pct": high_surge_pct,
    })
    db.pricing_rules[rule["id"]] = rule
    return response.success(serialize_pricing_rule(rule), 201)


@bp.route("/pricing-rules/<pricing_rule_id>", methods=["GET"])
def get_pricing_rule(pricing_rule_id):
    _, role = get_identity()
    require_role(role, READ_ROLES)
    rule = lookup.pricing_rule(pricing_rule_id)
    return response.success(serialize_pricing_rule(rule), 200)


@bp.route("/pricing-rules", methods=["GET"])
def list_pricing_rules():
    _, role = get_identity()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    attraction_id = request.args.get("attraction_id")
    records = list(db.pricing_rules.values())
    if attraction_id is not None:
        records = [r for r in records if r["attraction_id"] == attraction_id]
    page, total = sort_and_paginate(records, limit, offset)
    return response.success_list(
        [serialize_pricing_rule(r) for r in page], limit, offset, total, 200
    )
