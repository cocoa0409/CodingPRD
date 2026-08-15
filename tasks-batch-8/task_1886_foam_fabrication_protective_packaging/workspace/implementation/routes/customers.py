"""Customers (PRD §3.1)."""
from flask import Blueprint

import db
from middleware import get_auth_context, require_role
from response import success_object
from services.common import (
    body, get_single, opt_bool, owner_of_customer, req_enum, req_str, stamp_new,
)

bp = Blueprint("customers", __name__)

ACCOUNT_TIERS = ("STANDARD", "CONTRACT")


@bp.route("/customers", methods=["POST"])
def create_customer():
    user_id, role = get_auth_context()
    require_role(role, ("SalesEngineer",))
    data = body()
    name = req_str(data, "name")
    tier = req_enum(data, "account_tier", ACCOUNT_TIERS)
    branding = opt_bool(data, "branding_required", False)
    rec = stamp_new({
        "name": name,
        "account_tier": tier,
        "branding_required": branding,
        "credit_balance_cents": 0,
    })
    db.customers[rec["id"]] = rec
    return success_object({k: v for k, v in rec.items() if not k.startswith("_")}, 201)


@bp.route("/customers/<rid>", methods=["GET"])
def get_customer(rid):
    return get_single(db.customers, rid, owner_of_customer, "Customer")
