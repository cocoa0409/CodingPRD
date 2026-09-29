"""Shopper profiles and their return-policy overrides (PRD 3.7)."""

from flask import Blueprint

import constants as C
import validate as V
from db import db, new_row, touch
from errors import ApiError
from lookup import get_customer
from middleware import authenticate
from response import object_response
from routes.policies import build_policy_row, read_policy_body

bp = Blueprint("customer_profiles", __name__)


@bp.post("/fit-program/customer-profiles")
def create_customer_profile():
    authenticate(C.ROLE_MERCH_OPS_ADMIN)
    body = V.get_body()

    email = V.req_str(body, "email", min_len=1)
    tier = V.opt_enum(body, "tier", C.CUSTOMER_TIERS, default="STANDARD")

    for existing in db.customers.values():
        if existing["email"] == email:
            raise ApiError("ERR_DUPLICATE_RESOURCE_KEY",
                           "email '%s' is already registered." % email)

    customer = new_row({
        "email": email,
        "tier": tier,
        "purchase_line_count": 0,
        "return_case_count": 0,
        "change_of_mind_count": 0,
        "return_rate_bp": 0,
        "abuse_strike_count": 0,
        "abuse_status": "CLEAR",
        "policy_class": "EXTENDED_WINDOW" if tier == "PLUS" else "STANDARD_WINDOW",
        "refunded_total_cents": 0,
    })
    db.customers[customer["id"]] = customer
    return object_response(customer, 201)


@bp.get("/fit-program/customer-profiles/<customer_id>")
def read_customer_profile(customer_id):
    authenticate(C.ROLE_MERCH_OPS_ADMIN, C.ROLE_RETURNS_AUDITOR, C.ROLE_CUSTOMER)
    return object_response(get_customer(customer_id))


def _intervals_intersect(new_from, new_to, old_from, old_to):
    """Closed intervals; a null end is unbounded; touching endpoints intersect."""
    if new_to is not None and old_from > new_to:
        return False
    if old_to is not None and new_from > old_to:
        return False
    return True


@bp.post("/fit-program/customer-profiles/<customer_id>/return-policy-overrides")
def create_override(customer_id):
    authenticate(C.ROLE_MERCH_OPS_ADMIN)
    customer = get_customer(customer_id)
    body = V.get_body()

    fields = read_policy_body(body)
    expected_version = V.req_int(body, "expected_customer_profile_version")

    if expected_version != customer["version"]:
        raise ApiError("ERR_STALE_CUSTOMER_PROFILE_VERSION",
                       "The customer profile is at version %d, not %d."
                       % (customer["version"], expected_version))

    for existing in db.policies.values():
        if existing["scope"] != "CUSTOMER_OVERRIDE":
            continue
        if existing["customer_profile_id"] != customer["id"]:
            continue
        if existing["category_code"] != fields["category_code"]:
            continue
        if _intervals_intersect(fields["effective_from"], fields["effective_to"],
                                existing["effective_from"], existing["effective_to"]):
            raise ApiError("ERR_POLICY_WINDOW_OVERLAP",
                           "An override for this shopper and category already "
                           "covers part of that interval.")

    policy = build_policy_row("CUSTOMER_OVERRIDE", customer["id"], fields)
    db.policies[policy["id"]] = policy
    touch(customer)
    return object_response(policy, 201)
