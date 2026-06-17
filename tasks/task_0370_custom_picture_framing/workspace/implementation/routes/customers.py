"""Customer endpoints (PRD §3.1)."""
from flask import Blueprint

import errors
import validate
from db import db
from middleware import get_auth, require_role
from response import ok_array, ok_object
from services import calc, domain

bp = Blueprint("customers", __name__)

LOYALTY_TIERS = {"STANDARD", "PREFERRED", "TRADE"}


def _find_customer_or_404(customer_id):
    c = db.customers.get(customer_id)
    if c is None:
        errors.raise_err(errors.ERR_CUSTOMER_NOT_FOUND, "Customer not found")
    return c


@bp.route("/customers", methods=["POST"])
def create_customer():
    auth = get_auth()
    require_role(auth, ("FrontDeskClerk", "FrameDesigner"))
    body = validate.get_json_body()

    full_name = validate.as_string(validate.require(body, "full_name"), "full_name")
    email = validate.as_string(validate.require(body, "email"), "email")
    phone = validate.as_string(validate.require(body, "phone"), "phone")
    loyalty_tier = validate.opt(body, "loyalty_tier", "STANDARD")
    validate.as_enum(loyalty_tier, "loyalty_tier", LOYALTY_TIERS)

    c = {
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "loyalty_tier": loyalty_tier,
        "loyalty_discount_pct": calc.to_float(calc.LOYALTY_DISCOUNT[loyalty_tier]),
        "open_order_count": 0,
        "no_show_risk_score": 0,
        "settled_reputation_score": calc.SEED_BASE,
    }
    domain.stamp_create(c)
    db.customers[c["id"]] = c
    return ok_object(domain.serialize_customer(c), status=201)


@bp.route("/customers", methods=["GET"])
def list_customers():
    auth = get_auth()
    require_role(auth, ("FrontDeskClerk", "FrameDesigner", "FrameProductionTech"))
    limit, offset = validate.parse_pagination()
    items = list(db.customers.values())
    items.sort(key=lambda c: (c["created_at"], c["id"]))
    for c in items:
        domain.refresh_customer_derived(c)
    page, total = validate.paginate(items, limit, offset)
    return ok_array([domain.serialize_customer(c) for c in page], limit, offset, total)


@bp.route("/customers/<customer_id>", methods=["GET"])
def get_customer(customer_id):
    auth = get_auth()
    require_role(auth, ("FrontDeskClerk", "FrameDesigner", "FrameProductionTech", "Customer"))
    c = _find_customer_or_404(customer_id)
    if auth.role == "Customer" and auth.user_id != customer_id:
        errors.raise_err(errors.ERR_FORBIDDEN_ROLE, "Customer may only read own profile")
    domain.refresh_customer_derived(c)
    return ok_object(domain.serialize_customer(c))


@bp.route("/customers/<customer_id>/framing-orders", methods=["GET"])
def list_customer_orders(customer_id):
    auth = get_auth()
    require_role(auth, ("FrontDeskClerk", "FrameDesigner", "FrameProductionTech", "Customer"))
    c = _find_customer_or_404(customer_id)
    if auth.role == "Customer" and auth.user_id != customer_id:
        errors.raise_err(errors.ERR_FORBIDDEN_ROLE, "Customer may only read own orders")
    limit, offset = validate.parse_pagination()
    items = domain.customer_orders(customer_id)
    items.sort(key=lambda o: (o["created_at"], o["id"]))
    page, total = validate.paginate(items, limit, offset)
    return ok_array([domain.serialize_order(o) for o in page], limit, offset, total)
