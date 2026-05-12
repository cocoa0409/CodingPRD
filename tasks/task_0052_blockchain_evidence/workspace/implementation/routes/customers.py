"""Customer + Recharge routes."""
from flask import Blueprint, g, request

import db
from errors import err
from middleware import require_auth, get_pagination
from response import success
from services import audit
from services.lookup import get_customer, get_recharge
from services.validation import get_body, require_str, require_int, maybe_check_version


bp = Blueprint("customers", __name__)


def _customer_public(c: dict) -> dict:
    return {
        "id": c["id"],
        "email": c["email"],
        "display_name": c["display_name"],
        "wallet_balance_cents": c["wallet_balance_cents"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def _recharge_public(r: dict) -> dict:
    return {
        "id": r["id"],
        "customer_id": r["customer_id"],
        "amount_cents": r["amount_cents"],
        "external_payment_ref": r["external_payment_ref"],
        "status": r["status"],
        "created_at": r["created_at"],
    }


@bp.route("/customers", methods=["POST"])
@require_auth(roles={"PlatformAdmin"})
def create_customer():
    body = get_body()
    email = require_str(body, "email", max_len=320)
    display_name = require_str(body, "display_name", max_len=200)

    # email uniqueness across ACTIVE customers
    for c in db.customers.values():
        if c.get("status") == "ACTIVE" and c["email"].lower() == email.lower():
            raise err("ERR_VALIDATION_FAILED", f"email already in use: {email}")

    customer = {
        "email": email,
        "display_name": display_name,
        "wallet_balance_cents": 0,
        "status": "ACTIVE",
    }
    db.stamp_create(customer, common_fields=True)
    db.customers[customer["id"]] = customer

    # paired FeeAccount
    fa = {
        "customer_id": customer["id"],
        "lifetime_recharge_cents": 0,
        "lifetime_deduction_cents": 0,
    }
    db.stamp_create(fa, common_fields=False)
    db.fee_accounts[customer["id"]] = fa

    return success(_customer_public(customer), 201)


@bp.route("/customers/<cust_id>", methods=["GET"])
@require_auth(roles={"Customer", "PlatformAdmin"})
def read_customer(cust_id):
    c = get_customer(cust_id)
    if g.user_role == "Customer" and g.user_id != c["id"]:
        raise err("ERR_PERMISSION_DENIED", "Customer may only read its own record")
    return success(_customer_public(c), 200)


# ----- Recharge -----

@bp.route("/recharges", methods=["POST"])
@require_auth(roles={"Customer"})
def create_recharge():
    body = get_body()
    customer_id = require_str(body, "customer_id")
    amount_cents = require_int(body, "amount_cents", min_val=100, max_val=10_000_000)
    external_payment_ref = require_str(body, "external_payment_ref", max_len=200)

    # ownership before existence
    if g.user_id != customer_id:
        raise err("ERR_PERMISSION_DENIED",
                  "X-User-ID does not match body customer_id")

    # customer existence
    get_customer(customer_id, body_ref=True)

    # unique external_payment_ref
    if external_payment_ref in db.recharge_ref_index:
        raise err("ERR_DUPLICATE_PAYMENT_REF",
                  f"external_payment_ref already in use: {external_payment_ref}")

    r = {
        "customer_id": customer_id,
        "amount_cents": amount_cents,
        "external_payment_ref": external_payment_ref,
        "status": "PENDING",
    }
    db.stamp_create(r, common_fields=False)
    db.recharges[r["id"]] = r
    db.recharge_ref_index[external_payment_ref] = r["id"]
    return success(_recharge_public(r), 201)


@bp.route("/recharges/<r_id>", methods=["GET"])
@require_auth(roles={"Customer", "PlatformAdmin"})
def read_recharge(r_id):
    r = get_recharge(r_id)
    if g.user_role == "Customer" and g.user_id != r["customer_id"]:
        raise err("ERR_PERMISSION_DENIED", "Customer may only read its own recharges")
    return success(_recharge_public(r), 200)
