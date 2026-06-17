"""Customer routes (PRD 3.1)."""

from flask import Blueprint, request

import db
import errors
from common import (body, new_entity, require_str, opt_enum, CREDIT_TIERS,
                    paginate, get_or_404, find_dealership)
from middleware import get_auth, require_role
from response import ok, created, ok_list

bp = Blueprint("customers", __name__)


@bp.post("/customers")
def create_customer():
    _, role = get_auth()
    require_role(role, {"SalesAgent", "ServiceAdvisor", "DealerManager"})
    data = body()
    did = data.get("dealership_id")
    find_dealership(did)
    full_name = require_str(data, "full_name")
    email = require_str(data, "email")
    credit_tier = opt_enum(data, "credit_tier", CREDIT_TIERS, "STANDARD")
    # email unique per dealership
    for c in db.store["customers"].values():
        if c["dealership_id"] == did and c["email"] == email:
            errors.err("ERR_DUPLICATE_EMAIL", "email already used in this dealership.")
    rec = new_entity({
        "dealership_id": did,
        "full_name": full_name,
        "email": email,
        "credit_tier": credit_tier,
    })
    db.store["customers"][rec["id"]] = rec
    return created(rec)


@bp.get("/customers")
def list_customers():
    _, role = get_auth()
    require_role(role, {"DealerManager", "SalesAgent", "ServiceAdvisor"})
    items = list(db.store["customers"].values())
    did = request.args.get("dealership_id")
    if did is not None:
        items = [c for c in items if c["dealership_id"] == did]
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@bp.get("/customers/<customer_id>")
def get_customer(customer_id):
    user_id, role = get_auth()
    require_role(role, {"DealerManager", "SalesAgent", "ServiceAdvisor", "Customer"})
    rec = get_or_404("customers", customer_id)
    if role == "Customer" and rec["id"] != user_id:
        errors.err("ERR_CUSTOMER_NOT_FOUND", "Customer not found.")
    return ok(rec)
