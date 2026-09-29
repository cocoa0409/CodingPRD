"""Accounts and their credit ledger (PRD 3.5, 2.9)."""

from flask import Blueprint

import constants as C
import lookups
import response
import validation
from auth import deny, require_auth
from db import db, new_record
from serializers import view
from services import ledger
from util import money

bp = Blueprint("customers", __name__)


@bp.route("/customers", methods=["POST"])
def create_customer():
    require_auth("BillingAnalyst", "PlantAdmin")
    b = validation.body()
    account_code = validation.f_str(b, "account_code")
    name = validation.f_str(b, "name")
    region = validation.f_enum(b, "market_region", C.MARKET_REGIONS)
    credit_limit = validation.f_num(b, "credit_limit_usd", ge=0)
    pass_through = validation.f_bool(b, "pass_through_enabled", default=True)
    reel_program = validation.f_enum(
        b, "reel_program", C.REEL_PROGRAMS, required=False, default="RETURNABLE"
    )

    rec = new_record()
    rec.update({
        "account_code": account_code,
        "name": name,
        "market_region": region,
        "credit_limit_usd": credit_limit,
        "pass_through_enabled": pass_through,
        "reel_program": reel_program,
        "open_ar_usd": money("0"),
        "deposit_charged_total_usd": money("0"),
        "reel_deposit_balance_usd": money("0"),
        "credit_memo_balance_usd": money("0"),
        "forfeited_deposit_total_usd": money("0"),
        "credit_exposure_usd": money("0"),
        "status": "ACTIVE",
    })
    db.customers[rec["id"]] = rec
    return response.created(view("customer", rec))


@bp.route("/customers/<customer_id>", methods=["GET"])
def get_customer(customer_id):
    actor = require_auth("BillingAnalyst", "ShippingClerk", "PlantAdmin", "Customer")
    # Ownership is rung 2 of the ladder and therefore precedes existence.
    if actor.is_customer and customer_id != actor.user_id:
        deny()
    rec = lookups.customer(customer_id)
    return response.ok(view("customer", rec))


@bp.route("/customers/<customer_id>", methods=["PATCH"])
def patch_customer(customer_id):
    require_auth("BillingAnalyst", "PlantAdmin")
    b = validation.body()
    credit_limit = validation.f_num(b, "credit_limit_usd", required=False, default=None, ge=0)
    pass_through = validation.f_bool(b, "pass_through_enabled", default=None)
    reel_program = validation.f_enum(
        b, "reel_program", C.REEL_PROGRAMS, required=False, default=None
    )

    rec = lookups.customer(customer_id)
    if credit_limit is not None:
        rec["credit_limit_usd"] = credit_limit
    if pass_through is not None:
        rec["pass_through_enabled"] = pass_through
    if reel_program is not None:
        rec["reel_program"] = reel_program

    ledger.recompute_credit(rec)
    return response.ok(view("customer", rec))
