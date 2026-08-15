"""Customer endpoints."""

from flask import Blueprint, request

import db
import serializers
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_CUSTOMER_NOT_FOUND, ERR_STALE_VERSION,
)
from middleware import get_auth, require_role, get_pagination, apply_pagination
from response import success_object, success_list
from services.constants import DISCOUNT_TIERS, OVERRUN_POLICIES

bp = Blueprint("customers", __name__)


def get_customer_or_404(customer_id):
    c = db.customers.get(customer_id)
    if not c:
        raise ApiError(ERR_CUSTOMER_NOT_FOUND, "Customer id does not exist", 404)
    return c


@bp.route("/customers", methods=["POST"])
def create_customer():
    _, role = get_auth()
    require_role(role, ["CustomerServiceRep"])
    body = request.get_json(silent=True) or {}

    name = body.get("name")
    contact_email = body.get("contact_email")
    credit_limit_cents = body.get("credit_limit_cents")
    discount_tier = body.get("discount_tier", "STANDARD")
    overrun_policy = body.get("overrun_policy", "ACCEPT_AND_BILL_10")

    if not isinstance(name, str) or not name:
        raise ApiError(ERR_INVALID_REQUEST, "name is required", 400)
    if not isinstance(contact_email, str) or not contact_email:
        raise ApiError(ERR_INVALID_REQUEST, "contact_email is required", 400)
    if not isinstance(credit_limit_cents, int) or isinstance(credit_limit_cents, bool):
        raise ApiError(ERR_INVALID_REQUEST, "credit_limit_cents must be an integer", 400)
    if credit_limit_cents < 0:
        raise ApiError(ERR_INVALID_REQUEST, "credit_limit_cents must be >= 0", 400)
    if discount_tier not in DISCOUNT_TIERS:
        raise ApiError(ERR_INVALID_REQUEST, "invalid discount_tier", 400)
    if overrun_policy not in OVERRUN_POLICIES:
        raise ApiError(ERR_INVALID_REQUEST, "invalid overrun_policy", 400)

    now = db.timestamp_now()
    customer = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "name": name,
        "contact_email": contact_email,
        "credit_limit_cents": credit_limit_cents,
        "discount_tier": discount_tier,
        "overrun_policy": overrun_policy,
        "status": "ACTIVE",
        "trailing_billed_cents": 0,
    }
    db.customers[customer["id"]] = customer
    return success_object(serializers.customer(customer), 201)


@bp.route("/customers", methods=["GET"])
def list_customers():
    get_auth()
    limit, offset = get_pagination()
    status = request.args.get("status")
    items = list(db.customers.values())
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, total = apply_pagination(items, limit, offset)
    return success_list([serializers.customer(c) for c in page], limit, offset, total)


@bp.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    get_auth()
    return success_object(serializers.customer(get_customer_or_404(cid)))


@bp.route("/customers/<cid>/credit-limit-revisions", methods=["POST"])
def credit_limit_revision(cid):
    _, role = get_auth()
    require_role(role, ["CustomerServiceRep"])
    customer = get_customer_or_404(cid)
    body = request.get_json(silent=True) or {}

    new_limit = body.get("new_credit_limit_cents")
    expected = body.get("expected_customer_version")
    new_tier = body.get("discount_tier")

    if not isinstance(new_limit, int) or isinstance(new_limit, bool) or new_limit < 0:
        raise ApiError(ERR_INVALID_REQUEST, "new_credit_limit_cents must be a non-negative integer", 400)
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError(ERR_INVALID_REQUEST, "expected_customer_version is required", 400)
    if new_tier is not None and new_tier not in DISCOUNT_TIERS:
        raise ApiError(ERR_INVALID_REQUEST, "invalid discount_tier", 400)

    if expected != customer["version"]:
        raise ApiError(ERR_STALE_VERSION, "expected_customer_version is stale", 412)

    customer["credit_limit_cents"] = new_limit
    if new_tier is not None:
        customer["discount_tier"] = new_tier
    customer["version"] += 1
    customer["updated_at"] = db.timestamp_now()
    return success_object(serializers.customer(customer))


@bp.route("/customers/<cid>/credit-status", methods=["POST"])
def credit_status(cid):
    _, role = get_auth()
    require_role(role, ["BillingClerk"])
    customer = get_customer_or_404(cid)
    body = request.get_json(silent=True) or {}
    action = body.get("action")
    if action not in ("SUSPEND", "REINSTATE"):
        raise ApiError(ERR_INVALID_REQUEST, "action must be SUSPEND or REINSTATE", 400)

    if action == "SUSPEND":
        customer["status"] = "SUSPENDED"
    else:
        customer["status"] = "ACTIVE"
    customer["version"] += 1
    customer["updated_at"] = db.timestamp_now()
    return success_object(serializers.customer(customer))
