"""Customer + credit-adjustment + test-driving loyalty/clock routes."""
from flask import Blueprint

import db
import serializers as S
from auth import authenticate, authorize
from errors import err
from helpers import get_json_body, require_resource, require_fields
from response import success
from clock import clock
from util import parse_iso

bp = Blueprint("customers", __name__)


def _validate_email(value):
    if not isinstance(value, str) or value.strip() == "":
        raise err("ERR_INVALID_REQUEST", "email must be a non-empty string")
    return value.strip().lower()


def _validate_str(value, label):
    if not isinstance(value, str) or value.strip() == "":
        raise err("ERR_INVALID_REQUEST", "%s must be a non-empty string" % label)
    return value


@bp.route("/cleaning/customers", methods=["POST"])
def create_customer():
    principal = authenticate()
    authorize(principal, {"Anonymous"})
    body = get_json_body()
    require_fields(body, ["email", "full_name"])
    email = _validate_email(body["email"])
    full_name = _validate_str(body["full_name"], "full_name")
    rec = {
        "email": email,
        "full_name": full_name,
        "wallet_credit_cents": 0,
        "lifetime_booking_count": 0,
    }
    db.insert(db.customers, rec)
    return success(S.customer(rec), status=201)


@bp.route("/cleaning/customers/<cid>", methods=["GET"])
def get_customer(cid):
    principal = authenticate()
    authorize(principal, {"Customer", "PlatformAdmin"})
    rec = require_resource(db.customers, cid, "customer")
    if principal.role == "Customer" and principal.user_id != cid:
        raise err("ERR_FORBIDDEN_OWNERSHIP", "customer mismatch")
    return success(S.customer(rec), status=200)


@bp.route("/cleaning/customers/<cid>/credit-adjustments", methods=["POST"])
def credit_adjustment(cid):
    principal = authenticate()
    authorize(principal, {"PlatformAdmin"})
    rec = require_resource(db.customers, cid, "customer")
    body = get_json_body()
    require_fields(body, ["amount_cents"])
    amount = body["amount_cents"]
    if not isinstance(amount, int) or isinstance(amount, bool):
        raise err("ERR_INVALID_REQUEST", "amount_cents must be an integer")
    new_balance = rec.get("wallet_credit_cents", 0) + amount
    if new_balance < 0:
        new_balance = 0
    rec["wallet_credit_cents"] = new_balance
    db.touch(rec)
    return success(S.customer(rec), status=201)


@bp.route("/cleaning/_loyalty/set_count", methods=["POST"])
def set_loyalty_count():
    principal = authenticate()
    authorize(principal, {"PlatformAdmin"})
    body = get_json_body()
    require_fields(body, ["customer_id", "lifetime_booking_count"])
    rec = require_resource(db.customers, body["customer_id"], "customer")
    count = body["lifetime_booking_count"]
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise err("ERR_INVALID_REQUEST", "lifetime_booking_count must be a non-negative integer")
    rec["lifetime_booking_count"] = count
    db.touch(rec)
    return success(S.customer(rec), status=200)


@bp.route("/cleaning/_clock/set_current_utc", methods=["POST"])
def set_clock():
    principal = authenticate()
    authorize(principal, {"PlatformAdmin"})
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    dt = parse_iso(body["to_iso8601"])
    clock.set(dt)
    return success({}, status=200)
