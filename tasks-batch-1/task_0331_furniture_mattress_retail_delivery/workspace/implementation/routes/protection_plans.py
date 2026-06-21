"""ProtectionPlan endpoints (PRD §3.7)."""
from flask import Blueprint

import db
import helpers
import response
from errors import err
from middleware import get_auth, require_role
from services import calculations as calc
from services import domain, serializers

bp = Blueprint("protection_plans", __name__)

TIERS = {"BASIC", "PREMIUM"}
COVERAGE_BY_TIER = {"BASIC": {1, 2}, "PREMIUM": {3, 5}}


@bp.post("/protection-plans")
def create_protection_plan():
    _, role = get_auth()
    require_role(role, {"SalesAssociate", "StoreManager"})
    body = helpers.get_body()

    # Existence (4).
    order_line_id = helpers.require_str(body, "order_line_id")
    line = helpers.fetch(db.order_lines, order_line_id)

    # Shape (5): tier + coverage_years (tier-dependent allowed values).
    tier = helpers.require_enum(body, "tier", TIERS)
    coverage_years = helpers.require_int(body, "coverage_years")
    if coverage_years not in COVERAGE_BY_TIER[tier]:
        raise err("ERR_INVALID_REQUEST",
                  "coverage_years %s invalid for tier %s." % (coverage_years, tier))

    # Business referential (20): product eligible + no existing ACTIVE plan.
    product = db.products.get(line["product_id"])
    if product is None or not product.get("protection_eligible", True):
        raise err("ERR_PROTECTION_NOT_ALLOWED", "Product is not protection-eligible.")
    if domain.active_protection_plans_for_line(order_line_id):
        raise err("ERR_PROTECTION_NOT_ALLOWED", "Line already has an active protection plan.")

    premium = calc.protection_premium(line["line_total_cents"], tier, coverage_years)
    rec = {
        "order_line_id": order_line_id,
        "tier": tier,
        "coverage_years": coverage_years,
        "premium_cents": premium,
        "status": "ACTIVE",
    }
    helpers.stamp_create(rec)
    db.protection_plans[rec["id"]] = rec
    return response.object_response(serializers.protection_plan(rec), status=201)


@bp.get("/protection-plans/<pid>")
def get_protection_plan(pid):
    user_id, role = get_auth()
    require_role(role, {"SalesAssociate", "StoreManager", "Customer"})
    rec = helpers.fetch(db.protection_plans, pid)
    if role == "Customer":
        line = db.order_lines.get(rec["order_line_id"])
        order = db.orders.get(line["order_id"]) if line else None
        if order is None or user_id != order["customer_id"]:
            raise err("ERR_FORBIDDEN_NOT_OWNER", "Not the owning customer.")
    return response.object_response(serializers.protection_plan(rec))
