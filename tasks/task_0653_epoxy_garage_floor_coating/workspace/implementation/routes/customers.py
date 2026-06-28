"""Customer endpoints (SCAFFOLD §1.5 / PRD §3.2, §3.9)."""
from flask import Blueprint, request

from db import db, new_referral_code
from errors import err
from middleware import authenticate, require_role
from response import success
from services import serialize
from services.common import (get_body, new_row, parse_pagination, paginate,
                             require_str)

bp = Blueprint("customers", __name__)


@bp.route("/customers", methods=["POST"])
def create_customer():
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "SalesRep"})
    body = get_body()
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    row = new_row({
        "full_name": full_name,
        "email": email,
        "referral_code": new_referral_code(),
        "account_credit_balance_cents": 0,
    })
    db.customers[row["id"]] = row
    return success(serialize.customer(row), 201)


@bp.route("/customers/<id>", methods=["GET"])
def get_customer(id):
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "SalesRep", "WarrantyAgent", "Customer"})
    row = db.customers.get(id)
    if row is None:
        raise err("ERR_NOT_FOUND", "Customer not found")
    return success(serialize.customer(row), 200)


@bp.route("/customers/<id>/projects", methods=["GET"])
def list_customer_projects(id):
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "SalesRep", "Customer"})
    if db.customers.get(id) is None:
        raise err("ERR_NOT_FOUND", "Customer not found")
    limit, offset = parse_pagination()
    rows = [p for p in db.projects.values() if p["customer_id"] == id]
    page, meta = paginate(rows, limit, offset)
    return success([serialize.project(r) for r in page], 200, pagination=meta)


@bp.route("/customers/<id>/referrals", methods=["GET"])
def list_customer_referrals(id):
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "SalesRep", "Customer"})
    if db.customers.get(id) is None:
        raise err("ERR_NOT_FOUND", "Customer not found")
    limit, offset = parse_pagination()
    role_filter = request.args.get("role")
    if role_filter == "referrer":
        rows = [r for r in db.referrals.values() if r["referrer_customer_id"] == id]
    elif role_filter == "referred":
        rows = [r for r in db.referrals.values() if r["referred_customer_id"] == id]
    else:
        rows = [r for r in db.referrals.values()
                if r["referrer_customer_id"] == id or r["referred_customer_id"] == id]
    page, meta = paginate(rows, limit, offset)
    return success([serialize.referral(r) for r in page], 200, pagination=meta)
